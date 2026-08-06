import pytest
from app import db
from app.models import Reminder
from datetime import date


@pytest.fixture
def sample_reminder(app, test_user, sample_vehicle):
    reminder = Reminder(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='MOT Due',
        reminder_type='mot',
        due_date=date(2025, 6, 1),
        recurrence='none',
        notify_days_before=7,
    )
    db.session.add(reminder)
    db.session.commit()
    return reminder


class TestReminderIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/reminders/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/reminders/')
        assert resp.status_code == 200

    def test_index_shows_reminders(self, auth_client, sample_reminder):
        resp = auth_client.get('/reminders/')
        assert resp.status_code == 200
        assert b'MOT Due' in resp.data


class TestReminderNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/reminders/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/reminders/new')
        assert resp.status_code == 200

    def test_create_reminder(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/reminders/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'title': 'Service Due',
            'reminder_type': 'service',
            'due_date': '2025-12-01',
            'recurrence': 'none',
            'notify_days_before': '7',
        }, follow_redirects=True)
        assert resp.status_code == 200
        reminder = Reminder.query.filter_by(title='Service Due').first()
        assert reminder is not None
        assert reminder.user_id == test_user.id


class TestReminderEdit:
    def test_edit_requires_auth(self, client, sample_reminder):
        resp = client.get(f'/reminders/{sample_reminder.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_reminder):
        resp = auth_client.get(f'/reminders/{sample_reminder.id}/edit')
        assert resp.status_code == 200

    def test_edit_reminder(self, auth_client, sample_reminder):
        resp = auth_client.post(f'/reminders/{sample_reminder.id}/edit', data={
            'title': 'Updated MOT',
            'reminder_type': 'mot',
            'due_date': '2025-07-01',
            'recurrence': 'yearly',
            'notify_days_before': '14',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_reminder)
        assert sample_reminder.title == 'Updated MOT'
        assert sample_reminder.recurrence == 'yearly'


class TestReminderDelete:
    def test_delete_requires_auth(self, client, sample_reminder):
        resp = client.post(f'/reminders/{sample_reminder.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_reminder(self, auth_client, sample_reminder):
        reminder_id = sample_reminder.id
        resp = auth_client.post(f'/reminders/{reminder_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert Reminder.query.get(reminder_id) is None


class TestReminderComplete:
    def test_complete_requires_auth(self, client, sample_reminder):
        resp = client.post(f'/reminders/{sample_reminder.id}/complete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_complete_reminder(self, auth_client, sample_reminder):
        resp = auth_client.post(f'/reminders/{sample_reminder.id}/complete', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_reminder)
        assert sample_reminder.is_completed is True

    def test_uncomplete_reminder(self, auth_client, sample_reminder):
        sample_reminder.is_completed = True
        db.session.commit()

        resp = auth_client.post(f'/reminders/{sample_reminder.id}/uncomplete', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_reminder)
        assert sample_reminder.is_completed is False


class TestReminderFlexibleRecurrence:
    """#184 — recurrence is now a unit + interval pair (e.g., every 2 years)."""

    def test_create_with_interval(self, auth_client, sample_vehicle):
        resp = auth_client.post('/reminders/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'title': 'French MOT',
            'reminder_type': 'mot',
            'due_date': '2025-06-01',
            'recurrence': 'yearly',
            'recurrence_interval': '2',
            'notify_days_before': '14',
        }, follow_redirects=True)
        assert resp.status_code == 200
        r = Reminder.query.filter_by(title='French MOT').first()
        assert r is not None
        assert r.recurrence == 'yearly'
        assert r.recurrence_interval == 2

    def test_complete_uses_interval_for_next_occurrence(self, auth_client, sample_vehicle, test_user):
        r = Reminder(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            title='Biennial MOT', reminder_type='mot',
            due_date=date(2025, 6, 1),
            recurrence='yearly', recurrence_interval=2,
        )
        db.session.add(r)
        db.session.commit()
        auth_client.post(f'/reminders/{r.id}/complete', follow_redirects=True)
        next_r = Reminder.query.filter(Reminder.title == 'Biennial MOT', Reminder.is_completed == False).first()
        assert next_r is not None
        assert next_r.due_date == date(2027, 6, 1)
        assert next_r.recurrence_interval == 2

    def test_legacy_quarterly_still_resolves(self):
        from app.routes.reminders import calculate_next_due_date
        # Reminders created before 0.22.4 may have recurrence='quarterly'
        # and recurrence_interval=1; should still advance by 3 months.
        next_due = calculate_next_due_date(date(2025, 1, 1), 'quarterly', 1)
        assert next_due == date(2025, 4, 1)

    def test_legacy_biannual_still_resolves(self):
        from app.routes.reminders import calculate_next_due_date
        next_due = calculate_next_due_date(date(2025, 1, 1), 'biannual', 1)
        assert next_due == date(2025, 7, 1)

    def test_daily_interval(self):
        from app.routes.reminders import calculate_next_due_date
        assert calculate_next_due_date(date(2025, 6, 1), 'daily', 10) == date(2025, 6, 11)

    def test_weekly_interval(self):
        from app.routes.reminders import calculate_next_due_date
        assert calculate_next_due_date(date(2025, 6, 1), 'weekly', 3) == date(2025, 6, 22)


class TestReminderRecurrenceDuplicates:
    """#232 — re-completing a recurring reminder must not duplicate the next occurrence."""

    def _make_recurring(self, test_user, sample_vehicle):
        r = Reminder(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            title='Biannual Service', reminder_type='service',
            due_date=date(2026, 7, 18),
            recurrence='monthly', recurrence_interval=6,
        )
        db.session.add(r)
        db.session.commit()
        return r

    def test_single_completion_creates_one_next_occurrence(self, auth_client, sample_vehicle, test_user):
        r = self._make_recurring(test_user, sample_vehicle)
        auth_client.post(f'/reminders/{r.id}/complete', follow_redirects=True)

        next_occurrences = Reminder.query.filter(
            Reminder.title == 'Biannual Service',
            Reminder.is_completed == False,
        ).all()
        assert len(next_occurrences) == 1
        assert next_occurrences[0].due_date == date(2027, 1, 18)

    def test_tick_untick_tick_creates_exactly_one_next_occurrence(self, auth_client, sample_vehicle, test_user):
        r = self._make_recurring(test_user, sample_vehicle)

        # Tick
        auth_client.post(f'/reminders/{r.id}/complete', follow_redirects=True)
        # Untick
        auth_client.post(f'/reminders/{r.id}/uncomplete', follow_redirects=True)
        # Tick again
        auth_client.post(f'/reminders/{r.id}/complete', follow_redirects=True)

        next_occurrences = Reminder.query.filter(
            Reminder.title == 'Biannual Service',
            Reminder.due_date == date(2027, 1, 18),
            Reminder.is_completed == False,
        ).all()
        assert len(next_occurrences) == 1
