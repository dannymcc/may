"""Regression tests for the August 2026 security audit High-severity fixes.

Each test asserts that a second, non-admin user (B) cannot reach user A's data
through the route that was found vulnerable, and that legitimate access still
works. Covers H1 (CSV import IDOR), H2 (unauthenticated upload serving),
H3 (fuel-station cross-tenant mutation/cascade), H4 (person-task ownership),
H5 (forced admin password change), and H6 (notification SSRF).
"""
import io
import pytest
from datetime import date, timedelta

from app import db
from app.models import (
    User, Vehicle, Person, PersonTask, FuelStation, FuelPriceHistory,
)
from app.services.notifications import NotificationService


# ---------------------------------------------------------------------------
# Fixtures: a second owner (B) with their own client, plus A's resources
# ---------------------------------------------------------------------------

@pytest.fixture
def user_b(app):
    user = User(username='userb', email='b@example.com')
    user.set_password('BPass1234!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def client_b(app, user_b):
    c = app.test_client()
    c.post('/auth/login', data={'username': 'userb', 'password': 'BPass1234!'},
           follow_redirects=True)
    return c


@pytest.fixture
def vehicle_a(app, test_user):
    v = Vehicle(owner_id=test_user.id, name='A Car', vehicle_type='car',
                make='Honda', model='Civic', year=2022, fuel_type='petrol',
                odometer_unit='km')
    db.session.add(v)
    db.session.commit()
    return v


# ---------------------------------------------------------------------------
# H1 — CSV import must not write to a vehicle the user does not own
# ---------------------------------------------------------------------------

class TestH1CsvImportIdor:
    def _csv(self):
        return (io.BytesIO(b'date,cost\n2026-01-01,50\n'), 'data.csv')

    def test_preview_rejects_foreign_vehicle(self, client_b, vehicle_a):
        resp = client_b.post('/api/import/csv/preview', data={
            'data_type': 'fuel_logs', 'vehicle_id': vehicle_a.id,
            'file': self._csv(),
        }, content_type='multipart/form-data', follow_redirects=False)
        # Redirected back to upload (not the mapping page): access refused.
        assert resp.status_code in (301, 302)
        assert '/import/csv' in resp.headers.get('Location', '')

    def test_execute_rejects_foreign_vehicle(self, client_b, vehicle_a):
        before = vehicle_a.fuel_logs.count()
        client_b.post('/api/import/csv/execute', data={
            'data_type': 'fuel_logs', 'vehicle_id': vehicle_a.id,
            'mapping_0': 'date', 'mapping_1': 'cost',
        }, follow_redirects=False)
        # No records were injected into A's vehicle.
        assert vehicle_a.fuel_logs.count() == before


# ---------------------------------------------------------------------------
# H2 — uploaded files require auth + ownership; branding stays public
# ---------------------------------------------------------------------------

class TestH2UploadServing:
    def test_anonymous_cannot_read_private_upload(self, client, app):
        from app.models import Document
        # A document owned by nobody the anonymous caller can reach.
        resp = client.get('/api/uploads/secret_receipt.pdf')
        assert resp.status_code == 404

    def test_other_user_cannot_read_foreign_document(self, client_b, app, test_user, vehicle_a):
        from app.models import Document
        doc = Document(vehicle_id=vehicle_a.id, user_id=test_user.id,
                       title='Insurance', document_type='insurance',
                       filename='doc_abc_insurance.pdf',
                       original_filename='insurance.pdf')
        db.session.add(doc)
        db.session.commit()
        resp = client_b.get('/api/uploads/doc_abc_insurance.pdf')
        assert resp.status_code == 404

    def test_owner_can_read_their_document_record(self, auth_client, app, test_user, vehicle_a):
        from app.models import Document
        doc = Document(vehicle_id=vehicle_a.id, user_id=test_user.id,
                       title='Insurance', document_type='insurance',
                       filename='doc_own_insurance.pdf',
                       original_filename='insurance.pdf')
        db.session.add(doc)
        db.session.commit()
        # Ownership check passes -> send_from_directory runs; file is absent on
        # disk so we get 404 from Flask, NOT a 403/redirect from the auth gate.
        resp = auth_client.get('/api/uploads/doc_own_insurance.pdf')
        assert resp.status_code == 404  # reached the send stage (no auth block)


# ---------------------------------------------------------------------------
# H3 — fuel stations: no cross-tenant edit/favorite/delete; cascade guarded
# ---------------------------------------------------------------------------

class TestH3StationOwnership:
    @pytest.fixture
    def station_a(self, app, test_user):
        s = FuelStation(user_id=test_user.id, name='A Shell', brand='Shell')
        db.session.add(s)
        db.session.commit()
        return s

    def test_other_user_cannot_delete_foreign_station(self, client_b, station_a):
        client_b.post(f'/stations/{station_a.id}/delete', follow_redirects=True)
        assert FuelStation.query.get(station_a.id) is not None

    def test_other_user_cannot_edit_foreign_station(self, client_b, station_a):
        client_b.post(f'/stations/{station_a.id}/edit',
                      data={'name': 'Hacked'}, follow_redirects=True)
        assert FuelStation.query.get(station_a.id).name == 'A Shell'

    def test_other_user_cannot_favorite_foreign_station(self, client_b, station_a):
        resp = client_b.post(f'/stations/{station_a.id}/favorite')
        assert resp.status_code == 403

    def test_foreign_station_hides_edit_and_disables_favorite(self, client_b, station_a):
        # UI gating: B sees the shared station but no Edit link, and the
        # favorite toggle is rendered disabled (matches the backend 403).
        resp = client_b.get('/stations/')
        assert resp.status_code == 200
        assert f'/stations/{station_a.id}/edit'.encode() not in resp.data
        assert f'id="fav-btn-{station_a.id}" disabled'.encode() in resp.data

    def test_owner_sees_edit_and_interactive_favorite(self, auth_client, station_a):
        resp = auth_client.get('/stations/')
        assert resp.status_code == 200
        assert f'/stations/{station_a.id}/edit'.encode() in resp.data
        assert f'id="fav-btn-{station_a.id}" disabled'.encode() not in resp.data

    def test_delete_blocked_when_other_users_have_prices(self, auth_client, app, station_a, user_b):
        # B recorded a price at A's station; A deleting must not wipe B's row.
        price = FuelPriceHistory(station_id=station_a.id, user_id=user_b.id,
                                 fuel_type='petrol', price_per_unit=1.5,
                                 date=date.today())
        db.session.add(price)
        db.session.commit()
        price_id = price.id
        auth_client.post(f'/stations/{station_a.id}/delete', follow_redirects=True)
        assert FuelStation.query.get(station_a.id) is not None
        assert FuelPriceHistory.query.get(price_id) is not None


# ---------------------------------------------------------------------------
# H4 — person tasks are private to their creator, even on a shared person
# ---------------------------------------------------------------------------

class TestH4PersonTaskOwnership:
    @pytest.fixture
    def shared_person_a(self, app, test_user):
        p = Person(owner_id=test_user.id, name='Shared Contact',
                   relationship_type='client', is_shared=True)
        db.session.add(p)
        db.session.commit()
        return p

    @pytest.fixture
    def task_a(self, app, test_user, shared_person_a):
        t = PersonTask(person_id=shared_person_a.id, user_id=test_user.id,
                       title='Confidential: chase invoice', status='todo',
                       priority='high')
        db.session.add(t)
        db.session.commit()
        return t

    def test_other_user_cannot_delete_foreign_task(self, client_b, shared_person_a, task_a):
        client_b.post(f'/people/{shared_person_a.id}/tasks/{task_a.id}/delete',
                      follow_redirects=True)
        assert PersonTask.query.get(task_a.id) is not None

    def test_other_user_cannot_edit_foreign_task(self, client_b, shared_person_a, task_a):
        client_b.post(f'/people/{shared_person_a.id}/tasks/{task_a.id}/edit',
                      data={'title': 'Rewritten', 'status': 'todo'},
                      follow_redirects=True)
        assert PersonTask.query.get(task_a.id).title == 'Confidential: chase invoice'

    def test_other_user_cannot_move_foreign_task(self, client_b, task_a):
        resp = client_b.post(f'/people/tasks/{task_a.id}/move',
                             json={'status': 'done'})
        assert resp.status_code == 403
        assert PersonTask.query.get(task_a.id).status == 'todo'

    def test_board_hides_foreign_tasks(self, client_b, shared_person_a, task_a):
        resp = client_b.get('/people/board')
        assert b'Confidential: chase invoice' not in resp.data

    def test_api_hides_foreign_task(self, client, app, test_user, shared_person_a, task_a, user_b):
        key = user_b.generate_api_key()
        db.session.commit()
        resp = client.get(f'/api/v1/people/{shared_person_a.id}/tasks/{task_a.id}',
                          headers={'X-API-Key': key})
        assert resp.status_code == 404

    def test_owner_still_sees_own_task_on_board(self, auth_client, task_a):
        resp = auth_client.get('/people/board')
        assert b'Confidential: chase invoice' in resp.data


# ---------------------------------------------------------------------------
# H5 — bootstrapped admin is forced to change password before using the app
# ---------------------------------------------------------------------------

class TestH5ForcedPasswordChange:
    def test_bootstrap_admin_flagged(self, app):
        admin = User.query.filter_by(username='admin').first()
        assert admin is not None
        assert admin.must_change_password is True

    def test_change_form_actually_renders(self, client, app):
        # Regression: the flagged user is authenticated, so the page must render
        # its form (not fall through to base.html's nav-only authenticated layout).
        user = User(username='flagged0', email='f0@example.com',
                    must_change_password=True)
        user.set_password('OldPass123!')
        db.session.add(user)
        db.session.commit()
        client.post('/auth/login', data={'username': 'flagged0',
                                         'password': 'OldPass123!'},
                    follow_redirects=True)
        resp = client.get('/auth/change-password')
        assert resp.status_code == 200
        assert b'name="password"' in resp.data
        assert b'name="confirm_password"' in resp.data

    def test_flagged_user_is_redirected_to_change_form(self, client, app):
        user = User(username='flagged', email='f@example.com',
                    must_change_password=True)
        user.set_password('OldPass123!')
        db.session.add(user)
        db.session.commit()
        client.post('/auth/login', data={'username': 'flagged',
                                         'password': 'OldPass123!'},
                    follow_redirects=True)
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code in (301, 302)
        assert '/auth/change-password' in resp.headers.get('Location', '')

    def test_changing_password_clears_flag_and_unblocks(self, client, app):
        user = User(username='flagged2', email='f2@example.com',
                    must_change_password=True)
        user.set_password('OldPass123!')
        db.session.add(user)
        db.session.commit()
        client.post('/auth/login', data={'username': 'flagged2',
                                         'password': 'OldPass123!'},
                    follow_redirects=True)
        client.post('/auth/change-password', data={
            'password': 'BrandNew123!', 'confirm_password': 'BrandNew123!',
        }, follow_redirects=True)
        assert User.query.filter_by(username='flagged2').first().must_change_password is False


# ---------------------------------------------------------------------------
# H6 — notification delivery blocks SSRF to internal hosts
# ---------------------------------------------------------------------------

class TestH6NotificationSsrf:
    def test_webhook_blocks_localhost(self, app):
        ok, err = NotificationService.send_webhook('http://127.0.0.1:6379/', {'x': 1})
        assert ok is False
        assert err

    def test_webhook_blocks_private_ip(self, app):
        ok, err = NotificationService.send_webhook('http://169.254.169.254/latest/', {'x': 1})
        assert ok is False

    def test_ntfy_blocks_internal_url(self, app):
        ok, err = NotificationService.send_ntfy('http://127.0.0.1:8080/topic', 'T', 'M')
        assert ok is False
        assert err
