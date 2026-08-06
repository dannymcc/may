"""Tests for auth and admin routes in app/routes/auth.py."""
import pytest
from app.models import User, AppSettings
from app import db


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

class TestLoginRoute:
    def test_get_login_renders(self, client):
        response = client.get('/auth/login')
        assert response.status_code == 200

    def test_valid_login_redirects(self, client, test_user):
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'TestPass123!',
        })
        assert response.status_code == 302

    def test_invalid_password_shows_error(self, client, test_user):
        response = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'wrongpassword',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Invalid username or password' in response.data

    def test_nonexistent_user_shows_error(self, client):
        response = client.post('/auth/login', data={
            'username': 'doesnotexist',
            'password': 'SomePass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Invalid username or password' in response.data

    def test_authenticated_user_redirected_from_login(self, auth_client):
        response = auth_client.get('/auth/login')
        assert response.status_code == 302


class TestRegisterRoute:
    def test_get_register_renders_when_enabled(self, client, app):
        with app.app_context():
            AppSettings.set('registration_enabled', 'true')
            db.session.commit()
        response = client.get('/auth/register')
        assert response.status_code == 200

    def test_get_register_redirects_when_disabled(self, client, app):
        with app.app_context():
            AppSettings.set('registration_enabled', 'false')
            db.session.commit()
        response = client.get('/auth/register')
        assert response.status_code == 302

    def test_register_creates_user(self, client, app):
        with app.app_context():
            AppSettings.set('registration_enabled', 'true')
            db.session.commit()
        response = client.post('/auth/register', data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'NewPass123!',
            'confirm_password': 'NewPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Registration successful' in response.data
        with app.app_context():
            assert User.query.filter_by(username='newuser').first() is not None

    def test_register_rejects_duplicate_username(self, client, test_user, app):
        with app.app_context():
            AppSettings.set('registration_enabled', 'true')
            db.session.commit()
        response = client.post('/auth/register', data={
            'username': 'testuser',
            'email': 'other@example.com',
            'password': 'NewPass123!',
            'confirm_password': 'NewPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Username already exists' in response.data

    def test_register_rejects_duplicate_email(self, client, test_user, app):
        with app.app_context():
            AppSettings.set('registration_enabled', 'true')
            db.session.commit()
        response = client.post('/auth/register', data={
            'username': 'brandnewuser',
            'email': 'test@example.com',
            'password': 'NewPass123!',
            'confirm_password': 'NewPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Email already registered' in response.data

    def test_register_password_mismatch(self, client, app):
        with app.app_context():
            AppSettings.set('registration_enabled', 'true')
            db.session.commit()
        response = client.post('/auth/register', data={
            'username': 'anotheruser',
            'email': 'another@example.com',
            'password': 'NewPass123!',
            'confirm_password': 'DifferentPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Passwords do not match' in response.data


class TestForgotPasswordRoute:
    def test_get_forgot_password_redirects_when_smtp_not_configured(self, client):
        # SMTP is not configured in test env, so it redirects
        response = client.get('/auth/forgot-password')
        assert response.status_code == 302

    def test_get_forgot_password_renders_when_smtp_configured(self, client, app):
        with app.app_context():
            AppSettings.set('smtp_enabled', 'true')
            AppSettings.set('smtp_host', 'smtp.example.com')
            AppSettings.set('smtp_username', 'user@example.com')
            db.session.commit()
        response = client.get('/auth/forgot-password')
        assert response.status_code == 200

    def test_post_forgot_password_accepts_valid_email(self, client, test_user, app):
        with app.app_context():
            AppSettings.set('smtp_enabled', 'true')
            AppSettings.set('smtp_host', 'smtp.example.com')
            AppSettings.set('smtp_username', 'user@example.com')
            db.session.commit()
        response = client.post('/auth/forgot-password', data={
            'email': 'test@example.com',
        }, follow_redirects=True)
        assert response.status_code == 200
        # Always shows same message to prevent enumeration
        assert b'If an account with that email exists' in response.data

    def test_post_forgot_password_nonexistent_email(self, client, app):
        with app.app_context():
            AppSettings.set('smtp_enabled', 'true')
            AppSettings.set('smtp_host', 'smtp.example.com')
            AppSettings.set('smtp_username', 'user@example.com')
            db.session.commit()
        response = client.post('/auth/forgot-password', data={
            'email': 'nobody@example.com',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'If an account with that email exists' in response.data


class TestLogoutRoute:
    def test_logout_redirects_to_login(self, auth_client):
        response = auth_client.get('/auth/logout', follow_redirects=False)
        assert response.status_code == 302
        assert '/auth/login' in response.headers['Location']

    def test_logout_unauthenticated_redirects(self, client):
        response = client.get('/auth/logout')
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Authenticated user routes
# ---------------------------------------------------------------------------

class TestSettingsRoute:
    def test_get_settings_renders(self, auth_client):
        response = auth_client.get('/auth/settings')
        assert response.status_code == 200

    def test_get_settings_unauthenticated_redirects(self, client):
        response = client.get('/auth/settings')
        assert response.status_code == 302

    def test_post_settings_updates_preferences(self, auth_client, test_user, app):
        response = auth_client.post('/auth/settings', data={
            'distance_unit': 'mi',
            'volume_unit': 'gal',
            'consumption_unit': 'mpg',
            'currency': 'USD',
            'language': 'en',
            'date_format': 'MM/DD/YYYY',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Settings updated successfully' in response.data
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            assert user.distance_unit == 'mi'
            assert user.currency == 'USD'

    def test_post_settings_updates_currency(self, auth_client, test_user, app):
        response = auth_client.post('/auth/settings', data={
            'distance_unit': 'km',
            'volume_unit': 'L',
            'consumption_unit': 'L/100km',
            'currency': 'EUR',
            'language': 'en',
            'date_format': 'DD/MM/YYYY',
        }, follow_redirects=True)
        assert response.status_code == 200
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            assert user.currency == 'EUR'

    def test_post_settings_password_mismatch(self, auth_client):
        response = auth_client.post('/auth/settings', data={
            'distance_unit': 'km',
            'volume_unit': 'L',
            'consumption_unit': 'L/100km',
            'currency': 'USD',
            'language': 'en',
            'date_format': 'DD/MM/YYYY',
            'new_password': 'NewPass123!',
            'confirm_new_password': 'DifferentPass456!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Passwords do not match' in response.data


class TestNotificationsRoute:
    def test_post_notifications_updates_prefs(self, auth_client, test_user, app):
        response = auth_client.post('/auth/notifications', data={
            'email_reminders': 'true',
            'reminder_days_before': '14',
            'notification_method': 'email',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Notification preferences updated' in response.data
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            assert user.email_reminders is True
            assert user.reminder_days_before == 14

    def test_post_notifications_unauthenticated_redirects(self, client):
        response = client.post('/auth/notifications', data={
            'email_reminders': 'true',
        })
        assert response.status_code == 302

    def test_post_notifications_invalid_webhook_rejected(self, auth_client):
        response = auth_client.post('/auth/notifications', data={
            'email_reminders': 'false',
            'reminder_days_before': '7',
            'notification_method': 'webhook',
            'webhook_url': 'http://localhost/hook',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Invalid webhook URL' in response.data


class TestMenuPreferencesRoute:
    def test_post_menu_preferences_updates(self, auth_client, test_user, app):
        response = auth_client.post('/auth/menu-preferences', data={
            'start_page': 'fuel',
            'show_menu_vehicles': 'on',
            'show_menu_fuel': 'on',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Menu preferences updated' in response.data
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            assert user.start_page == 'fuel'
            assert user.show_menu_vehicles is True
            assert user.show_menu_fuel is True

    def test_post_menu_preferences_hidden_items(self, auth_client, test_user, app):
        response = auth_client.post('/auth/menu-preferences', data={
            'start_page': 'dashboard',
            # Not sending show_menu_fuel means it's off
        }, follow_redirects=True)
        assert response.status_code == 200
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            assert user.show_menu_fuel is False

    def test_post_menu_preferences_unauthenticated_redirects(self, client):
        response = client.post('/auth/menu-preferences', data={
            'start_page': 'dashboard',
        })
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Admin-only routes
# ---------------------------------------------------------------------------

class TestBrandingRoute:
    def test_post_branding_admin_succeeds(self, admin_client, app):
        response = admin_client.post('/auth/branding', data={
            'app_name': 'MyFleet',
            'app_tagline': 'Fleet Manager',
            'primary_color': '#ff0000',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Branding settings updated successfully' in response.data
        with app.app_context():
            assert AppSettings.get('app_name') == 'MyFleet'

    def test_uploaded_logo_used_as_favicon(self, auth_client, app):
        # #259 — a branding logo should become the tab icon.
        with app.app_context():
            AppSettings.set('logo_filename', 'my-logo.png')
        resp = auth_client.get('/auth/login', follow_redirects=True)
        assert b'rel="icon" href="/api/uploads/my-logo.png"' in resp.data
        with app.app_context():
            AppSettings.set('logo_filename', '')

    def test_default_favicon_without_logo(self, auth_client):
        resp = auth_client.get('/auth/login', follow_redirects=True)
        assert b'rel="icon"' in resp.data
        assert b'icons/icon.svg' in resp.data

    def test_post_branding_non_admin_forbidden(self, auth_client):
        response = auth_client.post('/auth/branding', data={
            'app_name': 'Hacked',
        }, follow_redirects=True)
        # Should redirect to dashboard with access denied flash
        assert response.status_code == 200
        assert b'Access denied' in response.data

    def test_post_branding_unauthenticated_redirects(self, client):
        response = client.post('/auth/branding', data={
            'app_name': 'Test',
        })
        assert response.status_code == 302


class TestRegistrationSettingsRoute:
    def test_post_registration_settings_admin_enable(self, admin_client, app):
        response = admin_client.post('/auth/registration-settings', data={
            'registration_enabled': 'on',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Registration settings updated' in response.data
        with app.app_context():
            assert AppSettings.get('registration_enabled') == 'true'

    def test_post_registration_settings_admin_disable(self, admin_client, app):
        response = admin_client.post('/auth/registration-settings', data={},
                                     follow_redirects=True)
        assert response.status_code == 200
        with app.app_context():
            assert AppSettings.get('registration_enabled') == 'false'

    def test_post_registration_settings_non_admin_forbidden(self, auth_client):
        response = auth_client.post('/auth/registration-settings', data={
            'registration_enabled': 'on',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data


class TestUsersListRoute:
    def test_get_users_admin_succeeds(self, admin_client):
        response = admin_client.get('/auth/users')
        assert response.status_code == 200

    def test_get_users_non_admin_forbidden(self, auth_client):
        response = auth_client.get('/auth/users', follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data

    def test_get_users_unauthenticated_redirects(self, client):
        response = client.get('/auth/users')
        assert response.status_code == 302


class TestToggleAdminRoute:
    def test_toggle_admin_on_another_user(self, admin_client, test_user, app):
        response = admin_client.post(
            f'/auth/users/{test_user.id}/toggle-admin',
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Admin status updated' in response.data
        with app.app_context():
            user = User.query.get(test_user.id)
            assert user.is_admin is True

    def test_toggle_admin_on_self_no_change(self, admin_client, admin_user, app):
        original_status = admin_user.is_admin
        response = admin_client.post(
            f'/auth/users/{admin_user.id}/toggle-admin',
            follow_redirects=True
        )
        assert response.status_code == 200
        with app.app_context():
            user = User.query.get(admin_user.id)
            assert user.is_admin == original_status

    def test_toggle_admin_non_admin_forbidden(self, auth_client, test_user):
        response = auth_client.post(
            f'/auth/users/{test_user.id}/toggle-admin',
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Access denied' in response.data


class TestDeleteUserRoute:
    def test_delete_user_admin_succeeds(self, admin_client, test_user, app):
        user_id = test_user.id
        response = admin_client.post(
            f'/auth/users/{user_id}/delete',
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'deleted' in response.data
        with app.app_context():
            assert User.query.get(user_id) is None

    def test_delete_self_prevented(self, admin_client, admin_user, app):
        user_id = admin_user.id
        response = admin_client.post(
            f'/auth/users/{user_id}/delete',
            follow_redirects=True
        )
        assert response.status_code == 200
        with app.app_context():
            assert User.query.get(user_id) is not None

    def test_delete_user_non_admin_forbidden(self, auth_client, test_user):
        response = auth_client.post(
            f'/auth/users/{test_user.id}/delete',
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Access denied' in response.data


class TestCreateUserRoute:
    def test_get_create_user_admin_succeeds(self, admin_client):
        response = admin_client.get('/auth/users/create')
        assert response.status_code == 200

    def test_post_create_user_admin_succeeds(self, admin_client, app):
        response = admin_client.post('/auth/users/create', data={
            'username': 'createdbyAdmin',
            'email': 'created@example.com',
            'password': 'CreatedPass123!',
            'confirm_password': 'CreatedPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'created successfully' in response.data
        with app.app_context():
            assert User.query.filter_by(username='createdbyAdmin').first() is not None

    def test_post_create_user_duplicate_username(self, admin_client, test_user):
        response = admin_client.post('/auth/users/create', data={
            'username': 'testuser',
            'email': 'unique@example.com',
            'password': 'CreatedPass123!',
            'confirm_password': 'CreatedPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Username already exists' in response.data

    def test_post_create_user_password_mismatch(self, admin_client):
        response = admin_client.post('/auth/users/create', data={
            'username': 'mismatchuser',
            'email': 'mismatch@example.com',
            'password': 'PassA123!',
            'confirm_password': 'PassB456!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Passwords do not match' in response.data

    def test_post_create_user_missing_fields(self, admin_client):
        response = admin_client.post('/auth/users/create', data={
            'username': '',
            'email': '',
            'password': '',
            'confirm_password': '',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'required' in response.data

    def test_get_create_user_non_admin_forbidden(self, auth_client):
        response = auth_client.get('/auth/users/create', follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data

    def test_post_create_user_non_admin_forbidden(self, auth_client):
        response = auth_client.post('/auth/users/create', data={
            'username': 'hackuser',
            'email': 'hack@example.com',
            'password': 'HackPass123!',
            'confirm_password': 'HackPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data


# ---------------------------------------------------------------------------
# Reset password routes
# ---------------------------------------------------------------------------

class TestResetPasswordRoute:
    def test_get_reset_password_invalid_token_redirects(self, client):
        response = client.get('/auth/reset-password/invalidtoken123', follow_redirects=True)
        assert response.status_code == 200
        assert b'Invalid or expired reset link' in response.data

    def test_get_reset_password_valid_token_renders(self, client, test_user, app):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            token = user.generate_reset_token()
            db.session.commit()
        response = client.get(f'/auth/reset-password/{token}')
        assert response.status_code == 200

    def test_post_reset_password_valid(self, client, test_user, app):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            token = user.generate_reset_token()
            db.session.commit()
        response = client.post(f'/auth/reset-password/{token}', data={
            'password': 'NewValid123!',
            'confirm_password': 'NewValid123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'password has been reset' in response.data

    def test_post_reset_password_mismatch(self, client, test_user, app):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            token = user.generate_reset_token()
            db.session.commit()
        response = client.post(f'/auth/reset-password/{token}', data={
            'password': 'NewValid123!',
            'confirm_password': 'Different456!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Passwords do not match' in response.data

    def test_post_reset_password_invalid_token_redirects(self, client):
        response = client.post('/auth/reset-password/badtoken', data={
            'password': 'NewValid123!',
            'confirm_password': 'NewValid123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Invalid or expired reset link' in response.data

    def test_authenticated_user_redirected(self, auth_client, test_user, app):
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            token = user.generate_reset_token()
            db.session.commit()
        response = auth_client.get(f'/auth/reset-password/{token}')
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# check-updates route
# ---------------------------------------------------------------------------

class TestCheckUpdatesRoute:
    def test_check_updates_authenticated_returns_json(self, auth_client):
        response = auth_client.get('/auth/check-updates')
        # May succeed or fail depending on network, but should return JSON
        assert response.status_code == 200
        data = response.get_json()
        assert 'success' in data

    def test_check_updates_unauthenticated_redirects(self, client):
        response = client.get('/auth/check-updates')
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# SMTP settings route (admin-only)
# ---------------------------------------------------------------------------

class TestSmtpSettingsRoute:
    def test_post_smtp_settings_admin_succeeds(self, admin_client, app):
        response = admin_client.post('/auth/smtp-settings', data={
            'smtp_enabled': 'on',
            'smtp_host': 'smtp.example.com',
            'smtp_port': '587',
            'smtp_username': 'user@example.com',
            'smtp_password': 'secret',
            'smtp_sender': 'noreply@example.com',
            'smtp_sender_name': 'May App',
            'smtp_tls': 'on',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Notification settings updated' in response.data
        with app.app_context():
            assert AppSettings.get('smtp_host') == 'smtp.example.com'

    def test_post_smtp_settings_non_admin_forbidden(self, auth_client):
        response = auth_client.post('/auth/smtp-settings', data={
            'smtp_host': 'smtp.evil.com',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data

    def test_post_smtp_settings_unauthenticated_redirects(self, client):
        response = client.post('/auth/smtp-settings', data={})
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Branding remove-logo route (admin-only)
# ---------------------------------------------------------------------------

class TestRemoveLogoRoute:
    def test_post_remove_logo_admin_succeeds(self, admin_client, app):
        # Set a fake logo filename first
        with app.app_context():
            AppSettings.set('logo_filename', '')
            db.session.commit()
        response = admin_client.post('/auth/branding/remove-logo', follow_redirects=True)
        assert response.status_code == 200
        assert b'Logo removed successfully' in response.data

    def test_post_remove_logo_non_admin_forbidden(self, auth_client):
        response = auth_client.post('/auth/branding/remove-logo', follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data


# ---------------------------------------------------------------------------
# DVLA settings route (admin-only)
# ---------------------------------------------------------------------------

class TestDvlaSettingsRoute:
    def test_post_dvla_settings_admin_succeeds(self, admin_client, app):
        response = admin_client.post('/auth/dvla-settings', data={
            'dvla_api_key': 'test-dvla-key-123',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'DVLA settings updated' in response.data
        with app.app_context():
            assert AppSettings.get('dvla_api_key') == 'test-dvla-key-123'

    def test_post_dvla_settings_non_admin_forbidden(self, auth_client):
        response = auth_client.post('/auth/dvla-settings', data={
            'dvla_api_key': 'stolen-key',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data


# ---------------------------------------------------------------------------
# Tessie settings route (admin-only)
# ---------------------------------------------------------------------------

class TestTessieSettingsRoute:
    def test_post_tessie_settings_admin_succeeds(self, admin_client, app):
        response = admin_client.post('/auth/tessie-settings', data={
            'tessie_api_token': 'tessie-token-abc',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Tessie settings updated' in response.data
        with app.app_context():
            assert AppSettings.get('tessie_api_token') == 'tessie-token-abc'

    def test_post_tessie_settings_non_admin_forbidden(self, auth_client):
        response = auth_client.post('/auth/tessie-settings', data={
            'tessie_api_token': 'stolen',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data


# ---------------------------------------------------------------------------
# Edit user route (admin-only)
# ---------------------------------------------------------------------------

class TestEditUserRoute:
    def test_get_edit_user_admin_renders(self, admin_client, test_user):
        response = admin_client.get(f'/auth/users/{test_user.id}/edit')
        assert response.status_code == 200

    def test_post_edit_user_update_email(self, admin_client, test_user, app):
        response = admin_client.post(f'/auth/users/{test_user.id}/edit', data={
            'email': 'updated@example.com',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'updated successfully' in response.data
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            assert user.email == 'updated@example.com'

    def test_post_edit_user_update_password(self, admin_client, test_user, app):
        response = admin_client.post(f'/auth/users/{test_user.id}/edit', data={
            'email': 'test@example.com',
            'new_password': 'UpdatedPass123!',
            'confirm_new_password': 'UpdatedPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'updated successfully' in response.data

    def test_post_edit_user_password_mismatch(self, admin_client, test_user):
        response = admin_client.post(f'/auth/users/{test_user.id}/edit', data={
            'email': 'test@example.com',
            'new_password': 'PassA123!',
            'confirm_new_password': 'PassB456!',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Passwords do not match' in response.data

    def test_post_edit_user_duplicate_email(self, admin_client, test_user, admin_user):
        response = admin_client.post(f'/auth/users/{test_user.id}/edit', data={
            'email': 'admin@example.com',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Email already in use' in response.data

    def test_get_edit_user_non_admin_forbidden(self, auth_client, test_user):
        response = auth_client.get(f'/auth/users/{test_user.id}/edit', follow_redirects=True)
        assert response.status_code == 200
        assert b'Access denied' in response.data

    def test_get_edit_user_unauthenticated_redirects(self, client, test_user):
        response = client.get(f'/auth/users/{test_user.id}/edit')
        assert response.status_code == 302
