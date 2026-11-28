"""Resend as an email provider for notifications and password resets."""
import io
import json
from urllib.error import HTTPError

import pytest

from app import db
from app.models import AppSettings
from app.services import notifications
from app.services.notifications import NotificationService


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def captured(monkeypatch):
    """Record requests to Resend instead of sending them."""
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append({'url': req.full_url, 'method': req.get_method(),
                     'headers': {k.lower(): v for k, v in req.header_items()},
                     'body': json.loads(req.data.decode('utf-8'))})
        return FakeResponse()

    monkeypatch.setattr(notifications, 'urlopen', fake_urlopen)
    return sent


def _use_resend(key='re_test_key', sender='noreply@example.com', name='Garage'):
    AppSettings.set('email_provider', 'resend')
    AppSettings.set('resend_api_key', key)
    AppSettings.set('resend_sender', sender)
    AppSettings.set('resend_sender_name', name)


class TestProviderSelection:
    def test_smtp_remains_the_default(self, app):
        assert NotificationService.email_provider() == 'smtp'
        assert NotificationService.email_configured() is False

    def test_unknown_provider_falls_back_to_smtp(self, app):
        AppSettings.set('email_provider', 'carrier-pigeon')
        assert NotificationService.email_provider() == 'smtp'

    def test_resend_needs_key_and_sender(self, app):
        _use_resend(sender='')
        assert NotificationService.email_configured() is False
        AppSettings.set('resend_sender', 'noreply@example.com')
        assert NotificationService.email_configured() is True


class TestSendResend:
    def test_send_email_routes_to_resend(self, app, captured):
        _use_resend()
        ok, error = NotificationService.send_email('driver@example.com', 'Subject', 'Plain body', '<p>HTML</p>')
        assert (ok, error) == (True, None)
        request = captured[0]
        assert request['url'] == 'https://api.resend.com/emails'
        assert request['method'] == 'POST'
        assert request['headers']['authorization'] == 'Bearer re_test_key'
        assert request['headers']['user-agent'].startswith('May-Vehicle-Manager')
        assert request['body'] == {'from': 'Garage <noreply@example.com>', 'to': ['driver@example.com'],
                                   'subject': 'Subject', 'text': 'Plain body', 'html': '<p>HTML</p>'}

    def test_plain_text_only_omits_html(self, app, captured):
        _use_resend()
        NotificationService.send_email('driver@example.com', 'Subject', 'Body')
        assert 'html' not in captured[0]['body']

    def test_angle_brackets_cannot_break_the_from_header(self, app, captured):
        _use_resend(name='Evil <attacker@example.org>')
        NotificationService.send_email('driver@example.com', 'S', 'B')
        assert captured[0]['body']['from'] == 'Evil attacker@example.org <noreply@example.com>'

    def test_unconfigured_resend_does_not_call_the_api(self, app, captured):
        AppSettings.set('email_provider', 'resend')
        ok, error = NotificationService.send_email('driver@example.com', 'S', 'B')
        assert (ok, error) == (False, 'Resend not configured')
        assert captured == []

    def test_api_error_message_is_reported(self, app, monkeypatch):
        _use_resend()

        def reject(req, timeout=None):
            body = io.BytesIO(json.dumps({'statusCode': 403, 'name': 'validation_error',
                                          'message': 'The example.com domain is not verified.'}).encode())
            raise HTTPError(req.full_url, 403, 'Forbidden', {}, body)

        monkeypatch.setattr(notifications, 'urlopen', reject)
        ok, error = NotificationService.send_email('driver@example.com', 'S', 'B')
        assert ok is False
        assert error == 'Resend HTTP 403: The example.com domain is not verified.'

    def test_reminder_notifications_go_through_resend(self, app, captured, test_user, sample_vehicle):
        from datetime import date
        from app.models import Reminder
        from app.services.reminder_processor import process_due_reminders
        _use_resend()
        db.session.add(Reminder(vehicle_id=sample_vehicle.id, user_id=test_user.id, title='MOT due',
                                reminder_type='mot', due_date=date.today(), notify_days_before=7))
        db.session.commit()
        stats = process_due_reminders()
        assert stats['sent'] == 1
        assert captured[0]['body']['to'] == ['test@example.com']
        assert 'MOT due' in captured[0]['body']['subject']


class TestPasswordReset:
    def test_forgot_password_works_with_resend(self, client, captured, test_user):
        _use_resend()
        assert client.get('/auth/forgot-password').status_code == 200
        client.post('/auth/forgot-password', data={'email': 'test@example.com'})
        assert captured and captured[0]['body']['to'] == ['test@example.com']
        assert 'reset' in captured[0]['body']['text'].lower()

    def test_forgot_password_is_unavailable_without_email(self, client):
        resp = client.get('/auth/forgot-password')
        assert resp.status_code == 302


class TestAdminSettings:
    def _save(self, client, **fields):
        data = {'smtp_enabled': 'true', 'email_provider': 'resend', 'resend_api_key': 're_saved',
                'resend_sender': 'noreply@example.com', 'resend_sender_name': 'Garage'}
        data.update(fields)
        return client.post('/auth/smtp-settings', data=data)

    def test_admin_saves_resend_and_the_key_is_never_shown(self, admin_client):
        assert self._save(admin_client).status_code == 302
        assert AppSettings.get('email_provider') == 'resend'
        assert AppSettings.get('resend_api_key') == 're_saved'
        page = admin_client.get('/auth/settings').get_data(as_text=True)
        assert 're_saved' not in page
        assert 'Saved. Leave blank to keep it.' in page
        assert 'id="resend-settings" class="border' in page
        assert 'id="smtp-settings" class="border border-gray-200 dark:border-gray-700 rounded-lg p-4" hidden' in page

    def test_blank_key_keeps_the_saved_one(self, admin_client):
        self._save(admin_client)
        self._save(admin_client, resend_api_key='', resend_sender_name='New name')
        assert AppSettings.get('resend_api_key') == 're_saved'
        assert AppSettings.get('resend_sender_name') == 'New name'

    def test_invalid_sender_is_rejected(self, admin_client):
        resp = self._save(admin_client, resend_sender='not-an-email')
        assert resp.status_code == 302
        assert AppSettings.get('email_provider') is None

    def test_switching_back_to_smtp(self, admin_client):
        self._save(admin_client)
        self._save(admin_client, email_provider='smtp')
        assert NotificationService.email_provider() == 'smtp'
        assert AppSettings.get('resend_api_key') == 're_saved'

    def test_non_admin_cannot_change_email_settings(self, auth_client):
        auth_client.post('/auth/smtp-settings', data={'email_provider': 'resend'})
        assert AppSettings.get('email_provider') is None


class TestResendTestEndpoint:
    def test_sends_without_saving(self, admin_client, captured):
        resp = admin_client.post('/api/resend/test', data={'resend_api_key': 're_trial',
                                                           'resend_sender': 'noreply@example.com'})
        assert resp.get_json() == {'success': True}
        assert captured[0]['headers']['authorization'] == 'Bearer re_trial'
        assert captured[0]['body']['to'] == ['admin@example.com']
        assert AppSettings.get('resend_api_key') is None
        assert AppSettings.get('email_provider') is None

    def test_blank_key_uses_the_saved_key(self, admin_client, captured):
        AppSettings.set('resend_api_key', 're_saved')
        admin_client.post('/api/resend/test', data={'resend_sender': 'noreply@example.com'})
        assert captured[0]['headers']['authorization'] == 'Bearer re_saved'

    def test_missing_details_are_explained(self, admin_client, captured):
        assert admin_client.post('/api/resend/test', data={}).get_json()['success'] is False
        assert captured == []

    def test_admin_only(self, auth_client, captured):
        resp = auth_client.post('/api/resend/test', data={'resend_api_key': 're_x',
                                                          'resend_sender': 'noreply@example.com'})
        assert resp.get_json()['success'] is False
        assert captured == []
