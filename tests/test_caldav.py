"""Tests for the CalDAV facade.

Split into two halves:

* Pure logic (enrichment, sidecar telemetry) -- no optional dependencies.
* Protocol round-trips -- skipped unless ``radicale`` and ``vobject`` are
  installed.

The test that matters most is ``test_sidecar_survives_a_stripping_client``.
Everything else in this module is scaffolding around that one guarantee.
"""

import base64
from datetime import date, datetime, timedelta

import pytest

from app import db
from app.caldav import enrichment, sidecar as sidecar_mod
from app.caldav.models import CalDavCollection, CalDavObject, CalDavSidecar
from app.models import Reminder

radicale = pytest.importorskip('radicale', reason='CalDAV extras not installed')
vobject = pytest.importorskip('vobject', reason='CalDAV extras not installed')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth(username, password):
    token = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': f'Basic {token}'}


def _dav(client, method, path, user='testuser', password='TestPass123!',
         data=None, headers=None, depth=None):
    hdrs = _auth(user, password)
    if depth is not None:
        hdrs['Depth'] = str(depth)
    if data is not None:
        hdrs.setdefault('Content-Type', 'text/calendar; charset=utf-8')
    hdrs.update(headers or {})
    return client.open(path, method=method, data=data, headers=hdrs)


VTODO_TEMPLATE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VTODO
UID:{uid}
DTSTAMP:20260101T000000Z
SUMMARY:{summary}
DESCRIPTION:{description}
DUE;VALUE=DATE:{due}
STATUS:NEEDS-ACTION
END:VTODO
END:VCALENDAR
"""


def _vtodo(uid='test-todo-1@may.local', summary='Book MOT ~45m',
           description='@garage before renewal', due='20260901'):
    return VTODO_TEMPLATE.format(uid=uid, summary=summary,
                                 description=description, due=due)


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class TestEnrichment:

    def test_duration_shorthand_becomes_an_estimate(self):
        ctx = enrichment.EnrichmentContext(uid='u1', summary='Swap tyres ~90m')
        out = enrichment.run_pipeline(ctx)
        assert out['estimate_minutes'].value == 90
        assert out['estimate_minutes'].source == 'duration'
        assert out['estimate_minutes'].evidence

    def test_hours_and_minutes_combine(self):
        ctx = enrichment.EnrichmentContext(uid='u1', summary='Service [2h30m]')
        out = enrichment.run_pipeline(ctx)
        assert out['estimate_minutes'].value == 150

    def test_implausible_durations_are_rejected(self):
        ctx = enrichment.EnrichmentContext(uid='u1', summary='Wait ~9999m')
        assert 'estimate_minutes' not in enrichment.run_pipeline(ctx)

    def test_context_tags_come_from_text_and_categories(self):
        ctx = enrichment.EnrichmentContext(
            uid='u1', summary='Fix @garage', categories=['MOT'])
        out = enrichment.run_pipeline(ctx)
        assert out['contexts'].value == ['garage', 'mot']

    def test_provenance_finds_url_and_ticket(self):
        ctx = enrichment.EnrichmentContext(
            uid='u1', summary='Chase ABC-451',
            description='see https://github.com/dannymcc/may/issues/1')
        out = enrichment.run_pipeline(ctx)
        assert out['source_ref'].value == 'ABC-451'
        assert out['source_system'].value == 'github'

    def test_dependencies_are_extracted(self):
        ctx = enrichment.EnrichmentContext(
            uid='u1', summary='Tax the car',
            description='blocked by: MOT certificate')
        out = enrichment.run_pipeline(ctx)
        assert out['blocked_by'].value == ['MOT certificate']

    def test_llm_enricher_is_off_unless_asked(self):
        calls = []

        def backend(prompt, ctx):
            calls.append(prompt)
            return {'energy': {'value': 'high', 'confidence': 0.99}}

        enrichment.set_llm_backend(backend)
        try:
            ctx = enrichment.EnrichmentContext(uid='u1', summary='Plan the rebuild')
            enrichment.run_pipeline(ctx, allow_llm=False)
            assert calls == []

            out = enrichment.run_pipeline(ctx, allow_llm=True)
            assert calls, 'backend should have been invoked'
            # 0.99 beats the heuristic's 0.45.
            assert out['energy'].value == 'high'
            assert out['energy'].source == 'llm'
        finally:
            enrichment.set_llm_backend(None)

    def test_a_failing_enricher_cannot_break_a_write(self):
        def exploding(prompt, ctx):
            raise RuntimeError('provider down')

        enrichment.set_llm_backend(exploding)
        try:
            ctx = enrichment.EnrichmentContext(uid='u1', summary='Book MOT ~30m')
            out = enrichment.run_pipeline(ctx, allow_llm=True)
            assert out['estimate_minutes'].value == 30  # others still ran
        finally:
            enrichment.set_llm_backend(None)


class TestLockPrecedence:

    def test_locked_fields_are_never_overwritten(self, app, test_user):
        card = CalDavSidecar.get_or_create(test_user.id, 'u-lock@may.local')
        card.estimate_minutes = 120
        card.lock('estimate_minutes')
        db.session.commit()

        derived = {'estimate_minutes': enrichment.DerivedValue(15, confidence=0.99)}
        changed = enrichment.apply_to_sidecar(card, derived)

        assert card.estimate_minutes == 120
        assert 'estimate_minutes' not in changed
        assert 'estimate_minutes' not in card.derived

    def test_unlocked_fields_are_written_with_provenance(self, app, test_user):
        card = CalDavSidecar.get_or_create(test_user.id, 'u-free@may.local')
        derived = {'estimate_minutes': enrichment.DerivedValue(
            15, confidence=0.7, source='duration', model='duration/1')}
        enrichment.apply_to_sidecar(card, derived, digest='abc')

        assert card.estimate_minutes == 15
        meta = card.derived['estimate_minutes']
        assert meta['source'] == 'duration'
        assert meta['confidence'] == 0.7
        assert meta['computed_at']
        assert card.enriched_digest == 'abc'

    def test_list_fields_union_rather_than_replace(self, app, test_user):
        card = CalDavSidecar.get_or_create(test_user.id, 'u-list@may.local')
        card.contexts = ['garage']
        enrichment.apply_to_sidecar(
            card, {'contexts': enrichment.DerivedValue(['phone'])})
        assert card.contexts == ['garage', 'phone']


class TestTelemetry:

    def test_moving_an_open_due_date_counts_as_a_slip(self, app, test_user):
        card = CalDavSidecar.get_or_create(test_user.id, 'u-slip@may.local')
        base = datetime(2026, 9, 1)

        sidecar_mod.record_touch(card, due_at=base)
        sidecar_mod.record_touch(card, due_at=base + timedelta(days=3))
        sidecar_mod.record_touch(card, due_at=base + timedelta(days=10))

        assert card.touch_count == 3
        assert card.reschedule_count == 2
        assert card.slip_days == 10
        assert card.first_due_at == base

    def test_pulling_a_date_forward_is_not_a_slip(self, app, test_user):
        card = CalDavSidecar.get_or_create(test_user.id, 'u-early@may.local')
        base = datetime(2026, 9, 10)
        sidecar_mod.record_touch(card, due_at=base)
        sidecar_mod.record_touch(card, due_at=base - timedelta(days=4))
        assert card.reschedule_count == 0

    def test_completing_does_not_count_as_a_slip(self, app, test_user):
        card = CalDavSidecar.get_or_create(test_user.id, 'u-done@may.local')
        base = datetime(2026, 9, 1)
        sidecar_mod.record_touch(card, due_at=base)
        sidecar_mod.record_touch(card, due_at=base + timedelta(days=5), completed=True)
        assert card.reschedule_count == 0

    def test_digest_is_stable_under_whitespace(self):
        a = sidecar_mod.context_digest('Book  MOT', 'at the\ngarage')
        b = sidecar_mod.context_digest('book mot', 'at the garage')
        assert a == b


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class TestDiscovery:

    def test_unauthenticated_requests_are_challenged(self, client):
        response = client.open('/caldav/', method='PROPFIND')
        assert response.status_code == 401
        assert 'Basic' in response.headers.get('WWW-Authenticate', '')

    def test_bad_password_is_rejected(self, client, test_user):
        response = _dav(client, 'PROPFIND', '/caldav/', password='wrong')
        assert response.status_code == 401

    def test_api_key_works_as_an_app_specific_password(self, client, test_user):
        key = test_user.generate_api_key()
        db.session.commit()
        response = _dav(client, 'PROPFIND', '/caldav/', password=key, depth=0)
        assert response.status_code == 207

    def test_principal_exposes_the_default_calendars(self, client, test_user):
        response = _dav(client, 'PROPFIND', '/caldav/testuser/', depth=1)
        assert response.status_code == 207
        body = response.get_data(as_text=True)
        assert '/caldav/testuser/reminders/' in body
        assert '/caldav/testuser/events/' in body

    def test_well_known_redirects_to_the_mount_point(self, client):
        response = client.get('/.well-known/caldav')
        assert response.status_code == 301
        assert response.headers['Location'].endswith('/caldav/')

    def test_one_user_cannot_see_another(self, client, test_user, admin_user):
        response = _dav(client, 'PROPFIND', '/caldav/admin/', depth=1)
        assert response.status_code in (403, 404)


class TestProjection:

    def test_a_may_reminder_appears_as_a_vtodo(self, client, test_user, sample_vehicle):
        db.session.add(Reminder(
            user_id=test_user.id, vehicle_id=sample_vehicle.id,
            title='MOT due', reminder_type='mot',
            due_date=date(2026, 9, 1), notify_days_before=7))
        db.session.commit()

        response = _dav(client, 'PROPFIND', '/caldav/testuser/reminders/', depth=1)
        assert response.status_code == 207

        obj = CalDavObject.query.filter_by(backing_kind='reminder').one()
        item = _dav(client, 'GET', f'/caldav/testuser/reminders/{obj.href}')
        body = item.get_data(as_text=True)

        assert 'BEGIN:VTODO' in body
        assert 'SUMMARY:MOT due' in body
        assert 'DUE;VALUE=DATE:20260901' in body
        assert 'TRIGGER:-P7D' in body or 'TRIGGER:-PT10080M' in body

    def test_etag_is_stable_across_reads(self, client, test_user):
        db.session.add(Reminder(user_id=test_user.id, title='Tax',
                                reminder_type='tax', due_date=date(2026, 10, 1)))
        db.session.commit()
        _dav(client, 'PROPFIND', '/caldav/testuser/reminders/', depth=1)
        obj = CalDavObject.query.filter_by(backing_kind='reminder').one()
        path = f'/caldav/testuser/reminders/{obj.href}'

        first = _dav(client, 'GET', path)
        second = _dav(client, 'GET', path)
        assert first.headers['ETag'] == second.headers['ETag']

    def test_editing_in_may_changes_the_etag(self, client, test_user):
        reminder = Reminder(user_id=test_user.id, title='Insurance',
                            reminder_type='insurance', due_date=date(2026, 11, 1))
        db.session.add(reminder)
        db.session.commit()
        _dav(client, 'PROPFIND', '/caldav/testuser/reminders/', depth=1)
        obj = CalDavObject.query.filter_by(backing_kind='reminder').one()
        path = f'/caldav/testuser/reminders/{obj.href}'
        before = _dav(client, 'GET', path).headers['ETag']

        reminder.title = 'Insurance renewal'
        reminder.updated_at = datetime.utcnow() + timedelta(seconds=1)
        db.session.commit()

        after = _dav(client, 'GET', path).headers['ETag']
        assert before != after


class TestWriteBack:

    def test_a_client_put_creates_a_may_reminder(self, client, test_user):
        response = _dav(client, 'PUT', '/caldav/testuser/reminders/new-1.ics',
                        data=_vtodo(summary='Replace wipers', description=''))
        assert response.status_code in (201, 204)

        reminder = Reminder.query.filter_by(title='Replace wipers').one()
        assert reminder.user_id == test_user.id
        assert reminder.due_date == date(2026, 9, 1)

    def test_enrichment_populates_the_sidecar_on_put(self, client, test_user):
        _dav(client, 'PUT', '/caldav/testuser/reminders/new-2.ics', data=_vtodo())

        card = CalDavSidecar.query.filter_by(uid='test-todo-1@may.local').one()
        assert card.estimate_minutes == 45          # from "~45m"
        assert 'garage' in card.contexts            # from "@garage"
        assert card.touch_count == 1

    def test_explicit_client_values_lock_the_field(self, client, test_user):
        ics = _vtodo(summary='Book MOT ~45m').replace(
            'STATUS:NEEDS-ACTION',
            'X-MAY-ESTIMATE-MINUTES:120\r\nSTATUS:NEEDS-ACTION')
        _dav(client, 'PUT', '/caldav/testuser/reminders/new-3.ics', data=ics)

        card = CalDavSidecar.query.filter_by(uid='test-todo-1@may.local').one()
        assert card.estimate_minutes == 120
        assert card.is_locked('estimate_minutes')

    def test_sidecar_survives_a_stripping_client(self, client, test_user):
        """The headline guarantee.

        Simulates a client that reads a resource, drops every property it does
        not recognise, and PUTs the remainder back -- which is what Google and
        several mobile clients actually do. The sidecar must be unaffected and
        the next GET must serve the fields again.
        """
        path = '/caldav/testuser/reminders/strip-me.ics'
        _dav(client, 'PUT', path, data=_vtodo())

        served = _dav(client, 'GET', path).get_data(as_text=True)
        assert 'X-MAY-ESTIMATE-MINUTES:45' in served

        # The client rewrites the resource with all X-properties removed and
        # only the summary changed.
        stripped = '\r\n'.join(
            line for line in served.splitlines()
            if not line.startswith('X-MAY-')
        ).replace('SUMMARY:Book MOT ~45m', 'SUMMARY:Book MOT')
        response = _dav(client, 'PUT', path, data=stripped)
        assert response.status_code in (201, 204)

        card = CalDavSidecar.query.filter_by(uid='test-todo-1@may.local').one()
        assert card.estimate_minutes == 45, 'sidecar was lost to a stripping client'

        again = _dav(client, 'GET', path).get_data(as_text=True)
        assert 'X-MAY-ESTIMATE-MINUTES:45' in again
        assert 'SUMMARY:Book MOT' in again

    def test_rescheduling_from_a_client_records_slip(self, client, test_user):
        path = '/caldav/testuser/reminders/slip.ics'
        _dav(client, 'PUT', path, data=_vtodo(due='20260901'))
        _dav(client, 'PUT', path, data=_vtodo(due='20260908'))

        card = CalDavSidecar.query.filter_by(uid='test-todo-1@may.local').one()
        assert card.reschedule_count == 1
        assert card.slip_days == 7

    def test_delete_removes_the_may_row_and_leaves_a_tombstone(self, client, test_user):
        path = '/caldav/testuser/reminders/doomed.ics'
        _dav(client, 'PUT', path, data=_vtodo(summary='Temporary'))
        assert Reminder.query.filter_by(title='Temporary').count() == 1

        response = _dav(client, 'DELETE', path)
        assert response.status_code in (200, 204)
        assert Reminder.query.filter_by(title='Temporary').count() == 0

        obj = CalDavObject.query.filter_by(href='doomed.ics').one()
        assert obj.is_deleted

    def test_every_write_appends_a_version(self, client, test_user):
        path = '/caldav/testuser/reminders/history.ics'
        _dav(client, 'PUT', path, data=_vtodo(summary='v1'))
        _dav(client, 'PUT', path, data=_vtodo(summary='v2'))

        obj = CalDavObject.query.filter_by(href='history.ics').one()
        versions = obj.versions.all()
        assert [v.operation for v in versions] == ['create', 'update']
        assert 'v1' in versions[0].raw_ics
        assert 'v2' in versions[1].raw_ics


class TestSync:

    def _collection(self, test_user):
        return CalDavCollection.query.filter_by(
            user_id=test_user.id, name='reminders').one()

    def test_token_advances_and_reports_only_changes(self, client, test_user):
        from app.caldav.storage import Collection, Storage
        from app.caldav.config import build_configuration

        _dav(client, 'PUT', '/caldav/testuser/reminders/a.ics',
             data=_vtodo(uid='a@may.local', summary='A'))

        storage = Storage(build_configuration())
        row = self._collection(test_user)
        collection = Collection(storage, row.path, row=row, user=test_user)

        token, hrefs = collection.sync()
        assert 'a.ics' in list(hrefs)

        _dav(client, 'PUT', '/caldav/testuser/reminders/b.ics',
             data=_vtodo(uid='b@may.local', summary='B'))

        db.session.expire_all()
        row = self._collection(test_user)
        collection = Collection(storage, row.path, row=row, user=test_user)
        new_token, changed = collection.sync(token)

        changed = list(changed)
        assert changed == ['b.ics']
        assert new_token != token

    def test_a_token_from_the_future_is_rejected(self, test_user):
        from app.caldav.storage import Collection, Storage
        from app.caldav.config import build_configuration

        row = self._collection(test_user)
        collection = Collection(Storage(build_configuration()), row.path,
                                row=row, user=test_user)
        with pytest.raises(ValueError):
            collection.sync('http://radicale.org/ns/sync/999999')

    def test_a_foreign_token_is_rejected(self, test_user):
        from app.caldav.storage import Collection, Storage
        from app.caldav.config import build_configuration

        row = self._collection(test_user)
        collection = Collection(Storage(build_configuration()), row.path,
                                row=row, user=test_user)
        with pytest.raises(ValueError):
            collection.sync('urn:uuid:not-ours')
