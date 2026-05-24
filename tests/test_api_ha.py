"""Tests for the Home Assistant API endpoints."""
import pytest
from datetime import date, timedelta
from app import db as _db_ext
from app.models import User, Vehicle, FuelLog, MaintenanceSchedule, Reminder


def make_ha_headers(api_key):
    return {'Authorization': f'Bearer {api_key}'}


@pytest.fixture
def ha_user(app):
    """A user with a generated API key for HA testing."""
    user = User(
        username='hauser',
        email='ha@example.com',
    )
    user.set_password('HaPass123!')
    _db_ext.session.add(user)
    _db_ext.session.commit()
    user.generate_api_key()
    _db_ext.session.commit()
    return user


@pytest.fixture
def ha_headers(ha_user):
    return make_ha_headers(ha_user.api_key)


@pytest.fixture
def ha_vehicle(ha_user):
    vehicle = Vehicle(
        owner_id=ha_user.id,
        name='HA Test Car',
        vehicle_type='car',
        make='Ford',
        model='Focus',
        year=2022,
        fuel_type='petrol',
    )
    _db_ext.session.add(vehicle)
    _db_ext.session.commit()
    return vehicle


@pytest.fixture
def ha_fuel_log(ha_user, ha_vehicle):
    log = FuelLog(
        vehicle_id=ha_vehicle.id,
        user_id=ha_user.id,
        date=date(2024, 1, 10),
        odometer=5000.0,
        volume=40.0,
        price_per_unit=1.60,
        total_cost=64.0,
        is_full_tank=True,
    )
    _db_ext.session.add(log)
    log2 = FuelLog(
        vehicle_id=ha_vehicle.id,
        user_id=ha_user.id,
        date=date(2024, 2, 10),
        odometer=5500.0,
        volume=38.0,
        price_per_unit=1.62,
        total_cost=61.56,
        is_full_tank=True,
    )
    _db_ext.session.add(log2)
    _db_ext.session.commit()
    return log


class TestHaAuth:
    def test_no_token_returns_401(self, client):
        resp = client.get('/api/ha/status')
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        resp = client.get('/api/ha/status', headers={'Authorization': 'Bearer bad-token'})
        assert resp.status_code == 401

    def test_missing_bearer_scheme_returns_401(self, client, ha_user):
        resp = client.get('/api/ha/status', headers={'Authorization': ha_user.api_key})
        assert resp.status_code == 401

    def test_valid_token_returns_200(self, client, ha_headers):
        resp = client.get('/api/ha/status', headers=ha_headers)
        assert resp.status_code == 200


class TestHaStatus:
    def test_status_response(self, client, ha_headers, ha_user):
        resp = client.get('/api/ha/status', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'online'
        assert data['user'] == ha_user.username
        assert 'version' in data


class TestHaVehicles:
    def test_list_vehicles_empty(self, client, ha_headers):
        resp = client.get('/api/ha/vehicles', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'vehicles' in data
        assert data['count'] == 0

    def test_list_vehicles_with_vehicle(self, client, ha_headers, ha_vehicle):
        resp = client.get('/api/ha/vehicles', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1
        v = data['vehicles'][0]
        assert v['name'] == 'HA Test Car'
        assert 'current_odometer' in v
        assert 'fuel_type' in v
        assert v['unit_distance'] == 'km'
        assert v['unit_volume'] == 'L'
        assert v['currency'] == 'USD'

    def test_vehicle_detail(self, client, ha_headers, ha_vehicle):
        resp = client.get(f'/api/ha/vehicles/{ha_vehicle.id}', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['id'] == ha_vehicle.id
        assert data['name'] == 'HA Test Car'
        assert data['unit_distance'] == 'km'
        assert data['unit_volume'] == 'L'
        assert data['currency'] == 'USD'

    def test_vehicle_detail_not_found(self, client, ha_headers):
        resp = client.get('/api/ha/vehicles/99999', headers=ha_headers)
        assert resp.status_code == 404

    def test_vehicle_detail_other_user(self, client, ha_headers, sample_vehicle):
        """Cannot access another user's vehicle."""
        resp = client.get(f'/api/ha/vehicles/{sample_vehicle.id}', headers=ha_headers)
        assert resp.status_code == 404


class TestHaVehicleStats:
    def test_vehicle_stats_no_fuel_logs(self, client, ha_headers, ha_vehicle):
        resp = client.get(f'/api/ha/vehicles/{ha_vehicle.id}/stats', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['vehicle_id'] == ha_vehicle.id
        assert 'total_distance' in data
        assert 'avg_consumption' in data

    def test_vehicle_stats_with_fuel_logs(self, client, ha_headers, ha_vehicle, ha_fuel_log):
        resp = client.get(f'/api/ha/vehicles/{ha_vehicle.id}/stats', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['fill_count'] == 2
        assert data['total_fuel'] > 0
        assert data['distance_unit'] == 'km'
        assert data['volume_unit'] == 'L'
        assert data['currency'] == 'USD'

    def test_vehicle_stats_not_found(self, client, ha_headers):
        resp = client.get('/api/ha/vehicles/99999/stats', headers=ha_headers)
        assert resp.status_code == 404

    def test_vehicle_stats_with_days_param(self, client, ha_headers, ha_vehicle, ha_fuel_log):
        resp = client.get(f'/api/ha/vehicles/{ha_vehicle.id}/stats?days=365', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['period_days'] == 365


class TestHaAlerts:
    @pytest.fixture
    def due_maintenance(self, ha_user, ha_vehicle):
        schedule = MaintenanceSchedule(
            vehicle_id=ha_vehicle.id,
            user_id=ha_user.id,
            name='Oil Change',
            maintenance_type='oil_change',
            next_due_date=date.today() - timedelta(days=1),
            is_active=True,
        )
        _db_ext.session.add(schedule)
        _db_ext.session.commit()
        return schedule

    @pytest.fixture
    def overdue_reminder(self, ha_user, ha_vehicle):
        reminder = Reminder(
            vehicle_id=ha_vehicle.id,
            user_id=ha_user.id,
            title='MOT',
            reminder_type='mot',
            due_date=date.today() - timedelta(days=2),
            notify_days_before=7,
            is_completed=False,
        )
        _db_ext.session.add(reminder)
        _db_ext.session.commit()
        return reminder

    def test_alerts_no_issues(self, client, ha_headers):
        resp = client.get('/api/ha/alerts', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'alerts' in data
        assert 'count' in data
        assert 'has_alerts' in data
        assert data['count'] == 0
        assert data['has_alerts'] is False

    def test_alerts_requires_auth(self, client):
        resp = client.get('/api/ha/alerts')
        assert resp.status_code == 401

    def test_alerts_include_maintenance_and_reminder(self, client, ha_headers, due_maintenance, overdue_reminder):
        resp = client.get('/api/ha/alerts', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 2
        statuses = {(item['type'], item['status']) for item in data['alerts']}
        assert ('maintenance', 'overdue') in statuses
        assert ('reminder', 'overdue') in statuses


class TestHaSummary:
    def test_summary_no_vehicles(self, client, ha_headers):
        resp = client.get('/api/ha/summary', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'total_vehicles' in data
        assert 'total_fuel_cost' in data
        assert 'alerts_count' in data
        assert data['total_vehicles'] == 0

    def test_summary_with_vehicle(self, client, ha_headers, ha_vehicle, ha_fuel_log):
        resp = client.get('/api/ha/summary', headers=ha_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total_vehicles'] == 1


class TestHaAddFuel:
    def test_add_fuel_success(self, client, ha_headers, ha_vehicle):
        resp = client.post(
            '/api/ha/fuel/add',
            json={
                'vehicle_id': ha_vehicle.id,
                'date': '2024-03-01',
                'odometer': 6000.0,
                'volume': 42.0,
                'price_per_unit': 1.65,
                'total_cost': 69.30,
            },
            headers=ha_headers,
            content_type='application/json'
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['success'] is True
        assert 'id' in data
        log = FuelLog.query.get(data['id'])
        assert log is not None
        assert log.user_id == ha_vehicle.owner_id

    def test_add_fuel_missing_required_field(self, client, ha_headers, ha_vehicle):
        resp = client.post(
            '/api/ha/fuel/add',
            json={
                'vehicle_id': ha_vehicle.id,
                'date': '2024-03-01',
                # missing odometer and other required fields
            },
            headers=ha_headers,
            content_type='application/json'
        )
        assert resp.status_code == 400

    def test_add_fuel_no_body(self, client, ha_headers):
        # Flask returns 415 when no Content-Type is set, 400 when JSON body is empty
        resp = client.post('/api/ha/fuel/add', headers=ha_headers)
        assert resp.status_code in (400, 415)

    def test_add_fuel_vehicle_not_found(self, client, ha_headers):
        resp = client.post(
            '/api/ha/fuel/add',
            json={
                'vehicle_id': 99999,
                'date': '2024-03-01',
                'odometer': 6000.0,
                'volume': 42.0,
                'price_per_unit': 1.65,
                'total_cost': 69.30,
            },
            headers=ha_headers,
            content_type='application/json'
        )
        assert resp.status_code == 404

    def test_add_fuel_other_users_vehicle(self, client, ha_headers, sample_vehicle):
        """Cannot add fuel to another user's vehicle."""
        resp = client.post(
            '/api/ha/fuel/add',
            json={
                'vehicle_id': sample_vehicle.id,
                'date': '2024-03-01',
                'odometer': 6000.0,
                'volume': 42.0,
                'price_per_unit': 1.65,
                'total_cost': 69.30,
            },
            headers=ha_headers,
            content_type='application/json'
        )
        assert resp.status_code == 404

    def test_add_fuel_no_auth(self, client, ha_vehicle):
        resp = client.post(
            '/api/ha/fuel/add',
            json={
                'vehicle_id': ha_vehicle.id,
                'date': '2024-03-01',
                'odometer': 6000.0,
                'volume': 42.0,
                'price_per_unit': 1.65,
                'total_cost': 69.30,
            },
            content_type='application/json'
        )
        assert resp.status_code == 401
