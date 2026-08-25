"""Tests for internal API endpoints (session-authenticated)."""
import pytest
from app import db as _db_ext
from app.models import User, Vehicle


class TestApiDocs:
    def test_docs_page_renders(self, auth_client):
        resp = auth_client.get('/api/docs')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'id="trips"' in body
        assert 'id="charging"' in body

    def test_docs_page_requires_login(self, client):
        resp = client.get('/api/docs')
        assert resp.status_code in (302, 401)


class TestToggleDarkMode:
    def test_toggle_dark_mode_on(self, auth_client, test_user):
        initial = test_user.dark_mode
        resp = auth_client.post('/api/toggle-dark-mode')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'dark_mode' in data
        assert data['dark_mode'] == (not initial)

    def test_toggle_dark_mode_twice(self, auth_client, test_user):
        initial = test_user.dark_mode
        auth_client.post('/api/toggle-dark-mode')
        resp = auth_client.post('/api/toggle-dark-mode')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['dark_mode'] == initial

    def test_toggle_dark_mode_unauthenticated(self, client):
        resp = client.post('/api/toggle-dark-mode')
        assert resp.status_code in (302, 401)


class TestApiKeyManagement:
    def test_generate_api_key(self, auth_client, test_user):
        resp = auth_client.post('/api/key/generate')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'api_key' in data
        assert 'created_at' in data
        assert len(data['api_key']) > 10

    def test_generate_api_key_unauthenticated(self, client):
        resp = client.post('/api/key/generate')
        assert resp.status_code in (302, 401)

    def test_revoke_api_key(self, auth_client, test_user):
        # First generate a key
        auth_client.post('/api/key/generate')
        resp = auth_client.post('/api/key/revoke')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_revoke_api_key_unauthenticated(self, client):
        resp = client.post('/api/key/revoke')
        assert resp.status_code in (302, 401)


class TestVehicleStats:
    def test_get_vehicle_stats(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/api/vehicles/{sample_vehicle.id}/stats')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'consumption' in data
        assert 'expenses_by_category' in data
        assert 'total_fuel_cost' in data
        assert 'total_expense_cost' in data

    def test_vehicle_stats_labels_each_consumption_point(
            self, auth_client, test_user, app):
        """#319 — the trend chart needs the fuel type of every point so it can
        plot diesel and AdBlue as separate, labelled series."""
        from datetime import date
        from app.models import FuelLog

        vehicle = Vehicle(
            owner_id=test_user.id, name='Diesel Van', vehicle_type='car',
            fuel_type='diesel', secondary_fuel_type='adblue', odometer_unit='km',
        )
        _db_ext.session.add(vehicle)
        _db_ext.session.commit()
        for odometer, volume, fuel_type in ((10000, 50, 'diesel'),
                                            (10100, 10, 'adblue'),
                                            (10500, 45, 'diesel'),
                                            (10600, 5, 'adblue')):
            _db_ext.session.add(FuelLog(
                vehicle_id=vehicle.id, user_id=test_user.id, date=date(2024, 1, 1),
                odometer=odometer, volume=volume, fuel_type=fuel_type,
                is_full_tank=True,
            ))
        _db_ext.session.commit()

        resp = auth_client.get(f'/api/vehicles/{vehicle.id}/stats')
        assert resp.status_code == 200
        points = resp.get_json()['consumption']
        by_type = {p['fuel_type']: p for p in points}
        assert set(by_type) == {'diesel', 'adblue'}
        assert by_type['diesel']['consumption'] == 9.0
        assert by_type['adblue']['consumption'] == 1.0
        assert by_type['adblue']['fuel_type_label'] == 'AdBlue/DEF'

    def test_get_vehicle_stats_unauthenticated(self, client, sample_vehicle):
        resp = client.get(f'/api/vehicles/{sample_vehicle.id}/stats')
        assert resp.status_code in (302, 401)

    def test_get_vehicle_stats_not_found(self, auth_client):
        resp = auth_client.get('/api/vehicles/99999/stats')
        assert resp.status_code == 404

    def test_get_vehicle_stats_other_users_vehicle(self, auth_client, admin_user, app):
        """Access to another user's vehicle should be denied."""
        other_vehicle = Vehicle(
            owner_id=admin_user.id,
            name='Admin Car',
            vehicle_type='car',
        )
        _db_ext.session.add(other_vehicle)
        _db_ext.session.commit()
        resp = auth_client.get(f'/api/vehicles/{other_vehicle.id}/stats')
        assert resp.status_code == 403


class TestLastOdometer:
    def test_get_last_odometer_no_logs(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/api/vehicles/{sample_vehicle.id}/last-odometer')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'odometer' in data

    def test_get_last_odometer_with_logs(self, auth_client, sample_vehicle, sample_fuel_log):
        resp = auth_client.get(f'/api/vehicles/{sample_vehicle.id}/last-odometer')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['odometer'] == sample_fuel_log.odometer

    def test_get_last_odometer_unauthenticated(self, client, sample_vehicle):
        resp = client.get(f'/api/vehicles/{sample_vehicle.id}/last-odometer')
        assert resp.status_code in (302, 401)

    def test_get_last_odometer_not_found(self, auth_client):
        resp = auth_client.get('/api/vehicles/99999/last-odometer')
        assert resp.status_code == 404


class TestProcessReminders:
    def test_process_reminders_as_admin(self, admin_client):
        resp = admin_client.post('/api/reminders/process')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'stats' in data

    def test_process_reminders_with_api_key(self, client, test_user):
        api_key = test_user.generate_api_key()
        _db_ext.session.commit()
        resp = client.post(
            '/api/reminders/process',
            headers={'Authorization': f'Bearer {api_key}'}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_process_reminders_with_internal_token(self, client, app):
        resp = client.post(
            '/api/reminders/process',
            headers={'X-Internal-Token': app.config['SECRET_KEY']}
        )
        assert resp.status_code == 200

    def test_process_reminders_unauthorized(self, client):
        resp = client.post('/api/reminders/process')
        assert resp.status_code == 401
