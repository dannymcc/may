"""Tests for the public REST API v1 (API key authenticated)."""
import pytest
from datetime import date
from app import db as _db_ext
from app.models import User, Vehicle, FuelLog, Expense, Trip, ChargingSession


class TestApiKeyAuth:
    def test_no_api_key_returns_401(self, client):
        resp = client.get('/api/v1/vehicles')
        assert resp.status_code == 401
        data = resp.get_json()
        assert data['code'] == 'missing_api_key'

    def test_invalid_api_key_returns_401(self, client):
        resp = client.get('/api/v1/vehicles', headers={'X-API-Key': 'invalid-key'})
        assert resp.status_code == 401
        data = resp.get_json()
        assert data['code'] == 'invalid_api_key'

    def test_bearer_token_auth(self, client, api_headers, test_user):
        """API key also works as Bearer token."""
        api_key = api_headers['X-API-Key']
        resp = client.get(
            '/api/v1/vehicles',
            headers={'Authorization': f'Bearer {api_key}'}
        )
        assert resp.status_code == 200


class TestV1Vehicles:
    def test_list_vehicles_empty(self, client, api_headers):
        resp = client.get('/api/v1/vehicles', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'vehicles' in data
        assert 'count' in data
        assert data['count'] == 0

    def test_list_vehicles_with_vehicle(self, client, api_headers, sample_vehicle):
        resp = client.get('/api/v1/vehicles', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1
        assert data['vehicles'][0]['name'] == 'Test Car'

    def test_get_vehicle(self, client, api_headers, sample_vehicle):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['id'] == sample_vehicle.id
        assert data['name'] == 'Test Car'

    def test_get_vehicle_not_found(self, client, api_headers):
        resp = client.get('/api/v1/vehicles/99999', headers=api_headers)
        assert resp.status_code == 404

    def test_get_vehicle_other_user(self, client, api_headers, admin_user, app):
        """Cannot access another user's vehicle."""
        other_vehicle = Vehicle(
            owner_id=admin_user.id,
            name='Admin Car',
            vehicle_type='car',
        )
        _db_ext.session.add(other_vehicle)
        _db_ext.session.commit()
        resp = client.get(f'/api/v1/vehicles/{other_vehicle.id}', headers=api_headers)
        assert resp.status_code == 404

    def test_create_vehicle(self, client, api_headers):
        resp = client.post(
            '/api/v1/vehicles',
            json={'name': 'New Car', 'vehicle_type': 'car'},
            headers=api_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['name'] == 'New Car'
        assert data['vehicle_type'] == 'car'
        assert 'id' in data

    def test_create_vehicle_missing_name(self, client, api_headers):
        resp = client.post(
            '/api/v1/vehicles',
            json={'vehicle_type': 'car'},
            headers=api_headers
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['code'] == 'validation_error'

    def test_create_vehicle_missing_type(self, client, api_headers):
        resp = client.post(
            '/api/v1/vehicles',
            json={'name': 'No Type'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_vehicle_invalid_type(self, client, api_headers):
        resp = client.post(
            '/api/v1/vehicles',
            json={'name': 'Bad', 'vehicle_type': 'spaceship'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_vehicle_no_body(self, client, api_headers):
        # Flask returns 415 when no Content-Type is set, 400 when JSON body is empty/invalid
        resp = client.post('/api/v1/vehicles', headers=api_headers)
        assert resp.status_code in (400, 415)

    def test_update_vehicle(self, client, api_headers, sample_vehicle):
        resp = client.put(
            f'/api/v1/vehicles/{sample_vehicle.id}',
            json={'name': 'Updated Car'},
            headers=api_headers
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'Updated Car'

    def test_update_vehicle_no_body(self, client, api_headers, sample_vehicle):
        resp = client.put(
            f'/api/v1/vehicles/{sample_vehicle.id}',
            headers=api_headers
        )
        assert resp.status_code in (400, 415)

    def test_update_vehicle_not_owner(self, client, api_headers, admin_user, app):
        """Non-owner cannot update a vehicle they can access (shared)."""
        other_vehicle = Vehicle(
            owner_id=admin_user.id,
            name='Admin Car',
            vehicle_type='car',
        )
        _db_ext.session.add(other_vehicle)
        _db_ext.session.commit()
        # 404 because it's not in user's vehicles list
        resp = client.put(
            f'/api/v1/vehicles/{other_vehicle.id}',
            json={'name': 'Hacked'},
            headers=api_headers
        )
        assert resp.status_code in (403, 404)

    def test_delete_vehicle(self, client, api_headers, test_user):
        vehicle = Vehicle(
            owner_id=test_user.id,
            name='To Delete',
            vehicle_type='van',
        )
        _db_ext.session.add(vehicle)
        _db_ext.session.commit()
        vid = vehicle.id
        resp = client.delete(f'/api/v1/vehicles/{vid}', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_delete_vehicle_not_found(self, client, api_headers):
        resp = client.delete('/api/v1/vehicles/99999', headers=api_headers)
        assert resp.status_code == 404


class TestV1FuelLogs:
    def test_list_fuel_logs_empty(self, client, api_headers, sample_vehicle):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/fuel', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'fuel_logs' in data
        assert 'total' in data
        assert data['total'] == 0

    def test_list_fuel_logs_with_entry(self, client, api_headers, sample_vehicle, sample_fuel_log):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/fuel', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1
        assert data['fuel_logs'][0]['odometer'] == 10000.0

    def test_list_fuel_logs_vehicle_not_found(self, client, api_headers):
        resp = client.get('/api/v1/vehicles/99999/fuel', headers=api_headers)
        assert resp.status_code == 404

    def test_create_fuel_log(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/fuel',
            json={
                'date': '2024-02-01',
                'odometer': 11000,
                'volume': 45.0,
                'price_per_unit': 1.55,
                'total_cost': 69.75,
            },
            headers=api_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['odometer'] == 11000.0
        assert 'id' in data

    def test_create_fuel_log_with_sales_tax(self, client, api_headers, sample_vehicle):
        """Sales tax comes back on the created log and can be cleared later (#225)."""
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/fuel',
            json={
                'date': '2024-02-02',
                'odometer': 11500,
                'volume': 45.0,
                'price_per_unit': 1.55,
                'total_cost': 69.75,
                'sales_tax': 9.07,
            },
            headers=api_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['sales_tax'] == 9.07

        resp = client.put(
            f"/api/v1/fuel/{data['id']}",
            json={'sales_tax': None},
            headers=api_headers
        )
        assert resp.status_code == 200
        assert resp.get_json()['sales_tax'] is None

    def test_create_fuel_log_missing_date(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/fuel',
            json={'odometer': 11000},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_fuel_log_missing_odometer(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/fuel',
            json={'date': '2024-02-01'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_fuel_log_invalid_date(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/fuel',
            json={'date': 'not-a-date', 'odometer': 11000},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_get_fuel_log(self, client, api_headers, sample_fuel_log):
        resp = client.get(f'/api/v1/fuel/{sample_fuel_log.id}', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['id'] == sample_fuel_log.id

    def test_get_fuel_log_not_found(self, client, api_headers):
        resp = client.get('/api/v1/fuel/99999', headers=api_headers)
        assert resp.status_code == 404

    def test_update_fuel_log(self, client, api_headers, sample_fuel_log):
        resp = client.put(
            f'/api/v1/fuel/{sample_fuel_log.id}',
            json={'odometer': 10500},
            headers=api_headers
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['odometer'] == 10500.0

    def test_update_fuel_log_invalid_date(self, client, api_headers, sample_fuel_log):
        resp = client.put(
            f'/api/v1/fuel/{sample_fuel_log.id}',
            json={'date': 'bad-date'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_update_fuel_log_no_body(self, client, api_headers, sample_fuel_log):
        resp = client.put(
            f'/api/v1/fuel/{sample_fuel_log.id}',
            headers=api_headers
        )
        assert resp.status_code in (400, 415)

    def test_delete_fuel_log(self, client, api_headers, sample_vehicle, test_user):
        log = FuelLog(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 3, 1),
            odometer=12000.0,
            volume=40.0,
            price_per_unit=1.50,
            total_cost=60.0,
        )
        _db_ext.session.add(log)
        _db_ext.session.commit()
        resp = client.delete(f'/api/v1/fuel/{log.id}', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_delete_fuel_log_not_found(self, client, api_headers):
        resp = client.delete('/api/v1/fuel/99999', headers=api_headers)
        assert resp.status_code == 404


class TestV1Expenses:
    def test_list_expenses_empty(self, client, api_headers, sample_vehicle):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/expenses', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'expenses' in data
        assert data['total'] == 0

    def test_list_expenses_with_entry(self, client, api_headers, sample_vehicle, sample_expense):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/expenses', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1

    def test_list_expenses_vehicle_not_found(self, client, api_headers):
        resp = client.get('/api/v1/vehicles/99999/expenses', headers=api_headers)
        assert resp.status_code == 404

    def test_create_expense(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/expenses',
            json={
                'date': '2024-03-01',
                'category': 'maintenance',
                'description': 'Tyre change',
                'cost': 120.0,
            },
            headers=api_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['description'] == 'Tyre change'
        assert 'id' in data

    def test_create_expense_missing_required(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/expenses',
            json={'date': '2024-03-01', 'category': 'maintenance'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_expense_invalid_category(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/expenses',
            json={
                'date': '2024-03-01',
                'category': 'unicorn',
                'description': 'Test',
                'cost': 10.0,
            },
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_expense_invalid_date(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/expenses',
            json={
                'date': 'not-a-date',
                'category': 'maintenance',
                'description': 'Test',
                'cost': 10.0,
            },
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_get_expense(self, client, api_headers, sample_expense):
        resp = client.get(f'/api/v1/expenses/{sample_expense.id}', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['id'] == sample_expense.id

    def test_get_expense_not_found(self, client, api_headers):
        resp = client.get('/api/v1/expenses/99999', headers=api_headers)
        assert resp.status_code == 404

    def test_update_expense(self, client, api_headers, sample_expense):
        resp = client.put(
            f'/api/v1/expenses/{sample_expense.id}',
            json={'cost': 100.0},
            headers=api_headers
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['cost'] == 100.0

    def test_update_expense_invalid_category(self, client, api_headers, sample_expense):
        resp = client.put(
            f'/api/v1/expenses/{sample_expense.id}',
            json={'category': 'invalid'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_update_expense_no_body(self, client, api_headers, sample_expense):
        resp = client.put(
            f'/api/v1/expenses/{sample_expense.id}',
            headers=api_headers
        )
        assert resp.status_code in (400, 415)

    def test_delete_expense(self, client, api_headers, sample_vehicle, test_user):
        expense = Expense(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 4, 1),
            category='cleaning',
            description='Car wash',
            cost=15.0,
        )
        _db_ext.session.add(expense)
        _db_ext.session.commit()
        resp = client.delete(f'/api/v1/expenses/{expense.id}', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_delete_expense_not_found(self, client, api_headers):
        resp = client.delete('/api/v1/expenses/99999', headers=api_headers)
        assert resp.status_code == 404


class TestV1Trips:
    def test_list_trips_requires_api_key(self, client, sample_vehicle):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/trips')
        assert resp.status_code == 401

    def test_list_trips_empty(self, client, api_headers, sample_vehicle):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/trips', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'trips' in data
        assert data['total'] == 0

    def test_list_trips_with_entry(self, client, api_headers, sample_vehicle, sample_trip):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/trips', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1
        assert data['trips'][0]['distance'] == 50.0

    def test_list_trips_filter_by_purpose(self, client, api_headers, sample_vehicle, sample_trip):
        resp = client.get(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips?purpose=personal',
            headers=api_headers
        )
        assert resp.status_code == 200
        assert resp.get_json()['total'] == 0

    def test_list_trips_vehicle_not_found(self, client, api_headers):
        resp = client.get('/api/v1/vehicles/99999/trips', headers=api_headers)
        assert resp.status_code == 404

    def test_create_trip(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={
                'date': '2024-03-05',
                'start_odometer': 20000,
                'end_odometer': 20120,
                'purpose': 'business',
                'description': 'Site survey',
            },
            headers=api_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['purpose'] == 'business'
        assert data['distance'] == 120.0
        assert 'id' in data

    def test_create_trip_missing_required(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={'date': '2024-03-05', 'purpose': 'business'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_trip_invalid_purpose(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={
                'date': '2024-03-05',
                'start_odometer': 20000,
                'purpose': 'unicorn',
            },
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_trip_invalid_date(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={
                'date': 'not-a-date',
                'start_odometer': 20000,
                'purpose': 'business',
            },
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_trip_non_string_date(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={
                'date': 20240305,
                'start_odometer': 20000,
                'purpose': 'business',
            },
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_trip_invalid_odometer(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={
                'date': '2024-03-05',
                'start_odometer': 'abc',
                'purpose': 'business',
            },
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_trip_zero_start_odometer(self, client, api_headers, sample_vehicle):
        """A zero start odometer is a real value, not a missing one."""
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={
                'date': '2024-03-05',
                'start_odometer': 0,
                'purpose': 'personal',
            },
            headers=api_headers
        )
        assert resp.status_code == 201
        assert resp.get_json()['start_odometer'] == 0

    def test_get_trip(self, client, api_headers, sample_trip):
        resp = client.get(f'/api/v1/trips/{sample_trip.id}', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['id'] == sample_trip.id

    def test_get_trip_not_found(self, client, api_headers):
        resp = client.get('/api/v1/trips/99999', headers=api_headers)
        assert resp.status_code == 404

    def test_get_trip_other_user(self, client, api_headers, admin_user):
        """Cannot access another user's trip."""
        other_vehicle = Vehicle(
            owner_id=admin_user.id,
            name='Admin Car',
            vehicle_type='car',
        )
        _db_ext.session.add(other_vehicle)
        _db_ext.session.commit()
        trip = Trip(
            vehicle_id=other_vehicle.id,
            user_id=admin_user.id,
            date=date(2024, 2, 1),
            start_odometer=100.0,
            purpose='personal',
        )
        _db_ext.session.add(trip)
        _db_ext.session.commit()
        resp = client.get(f'/api/v1/trips/{trip.id}', headers=api_headers)
        assert resp.status_code == 404

    def test_update_trip(self, client, api_headers, sample_trip):
        resp = client.put(
            f'/api/v1/trips/{sample_trip.id}',
            json={'end_odometer': 10100, 'notes': 'Return leg included'},
            headers=api_headers
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['end_odometer'] == 10100.0
        assert data['notes'] == 'Return leg included'

    def test_update_trip_invalid_purpose(self, client, api_headers, sample_trip):
        resp = client.put(
            f'/api/v1/trips/{sample_trip.id}',
            json={'purpose': 'invalid'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_update_trip_no_body(self, client, api_headers, sample_trip):
        resp = client.put(f'/api/v1/trips/{sample_trip.id}', headers=api_headers)
        assert resp.status_code in (400, 415)

    def test_delete_trip(self, client, api_headers, sample_trip):
        resp = client.delete(f'/api/v1/trips/{sample_trip.id}', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert _db_ext.session.get(Trip, sample_trip.id) is None

    def test_delete_trip_not_found(self, client, api_headers):
        resp = client.delete('/api/v1/trips/99999', headers=api_headers)
        assert resp.status_code == 404

    def test_create_trip_with_fuel_levels(self, client, api_headers, sample_vehicle):
        """Fuel gauge readings are accepted and fuel used is derived (#273)."""
        sample_vehicle.tank_capacity = 50.0
        _db_ext.session.commit()
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={
                'date': '2024-03-05',
                'start_odometer': 20000,
                'end_odometer': 20120,
                'start_fuel_level': 90,
                'end_fuel_level': 70,
                'purpose': 'business',
            },
            headers=api_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['start_fuel_level'] == 90.0
        assert data['end_fuel_level'] == 70.0
        assert data['fuel_used'] == pytest.approx(10.0)

    def test_create_trip_rejects_out_of_range_fuel_level(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/trips',
            json={
                'date': '2024-03-05',
                'start_odometer': 20000,
                'start_fuel_level': 120,
                'purpose': 'business',
            },
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_update_trip_fuel_levels(self, client, api_headers, sample_trip):
        resp = client.put(
            f'/api/v1/trips/{sample_trip.id}',
            json={'start_fuel_level': 60, 'end_fuel_level': 40},
            headers=api_headers
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['start_fuel_level'] == 60.0
        assert data['end_fuel_level'] == 40.0

    def test_update_trip_rejects_out_of_range_fuel_level(self, client, api_headers, sample_trip):
        resp = client.put(
            f'/api/v1/trips/{sample_trip.id}',
            json={'end_fuel_level': -1},
            headers=api_headers
        )
        assert resp.status_code == 400


class TestV1Charging:
    def test_list_charging_requires_api_key(self, client, sample_vehicle):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/charging')
        assert resp.status_code == 401

    def test_list_charging_empty(self, client, api_headers, sample_vehicle):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/charging', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'charging_sessions' in data
        assert data['total'] == 0

    def test_list_charging_with_entry(self, client, api_headers, sample_vehicle,
                                      sample_charging_session):
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/charging', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1
        assert data['charging_sessions'][0]['kwh_added'] == 40.0

    def test_list_charging_filter_by_charger_type(self, client, api_headers, sample_vehicle,
                                                  sample_charging_session):
        resp = client.get(
            f'/api/v1/vehicles/{sample_vehicle.id}/charging?charger_type=dcfc',
            headers=api_headers
        )
        assert resp.status_code == 200
        assert resp.get_json()['total'] == 0

    def test_list_charging_vehicle_not_found(self, client, api_headers):
        resp = client.get('/api/v1/vehicles/99999/charging', headers=api_headers)
        assert resp.status_code == 404

    def test_create_charging_session(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/charging',
            json={
                'date': '2024-03-10',
                'start_time': '08:30',
                'end_time': '09:45',
                'kwh_added': 30.0,
                'cost_per_kwh': 0.25,
                'charger_type': 'level2',
                'start_soc': 20,
                'end_soc': 80,
            },
            headers=api_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        # Total cost derived from kWh and unit price
        assert data['total_cost'] == 7.5
        assert data['start_time'] == '08:30:00'
        assert data['start_soc'] == 20
        assert 'id' in data

    def test_create_charging_session_minimal(self, client, api_headers, sample_vehicle):
        """Only the date is required."""
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/charging',
            json={'date': '2024-03-11'},
            headers=api_headers
        )
        assert resp.status_code == 201
        assert resp.get_json()['date'] == '2024-03-11'

    def test_create_charging_session_missing_date(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/charging',
            json={'kwh_added': 10.0},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_charging_session_invalid_charger_type(self, client, api_headers,
                                                          sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/charging',
            json={'date': '2024-03-10', 'charger_type': 'unicorn'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_charging_session_invalid_date(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/charging',
            json={'date': 'not-a-date'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_charging_session_invalid_time(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/charging',
            json={'date': '2024-03-10', 'start_time': 'half past eight'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_create_charging_session_invalid_kwh(self, client, api_headers, sample_vehicle):
        resp = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/charging',
            json={'date': '2024-03-10', 'kwh_added': 'lots'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_get_charging_session(self, client, api_headers, sample_charging_session):
        resp = client.get(f'/api/v1/charging/{sample_charging_session.id}', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['id'] == sample_charging_session.id

    def test_get_charging_session_not_found(self, client, api_headers):
        resp = client.get('/api/v1/charging/99999', headers=api_headers)
        assert resp.status_code == 404

    def test_get_charging_session_other_user(self, client, api_headers, admin_user):
        """Cannot access another user's charging session."""
        other_vehicle = Vehicle(
            owner_id=admin_user.id,
            name='Admin EV',
            vehicle_type='car',
            fuel_type='electric',
        )
        _db_ext.session.add(other_vehicle)
        _db_ext.session.commit()
        session = ChargingSession(
            vehicle_id=other_vehicle.id,
            user_id=admin_user.id,
            date=date(2024, 2, 5),
            kwh_added=10.0,
        )
        _db_ext.session.add(session)
        _db_ext.session.commit()
        resp = client.get(f'/api/v1/charging/{session.id}', headers=api_headers)
        assert resp.status_code == 404

    def test_update_charging_session(self, client, api_headers, sample_charging_session):
        resp = client.patch(
            f'/api/v1/charging/{sample_charging_session.id}',
            json={'total_cost': 15.0, 'network': 'Home'},
            headers=api_headers
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total_cost'] == 15.0
        assert data['network'] == 'Home'

    def test_update_charging_session_invalid_charger_type(self, client, api_headers,
                                                          sample_charging_session):
        resp = client.put(
            f'/api/v1/charging/{sample_charging_session.id}',
            json={'charger_type': 'invalid'},
            headers=api_headers
        )
        assert resp.status_code == 400

    def test_update_charging_session_no_body(self, client, api_headers, sample_charging_session):
        resp = client.put(f'/api/v1/charging/{sample_charging_session.id}', headers=api_headers)
        assert resp.status_code in (400, 415)

    def test_delete_charging_session(self, client, api_headers, sample_charging_session):
        session_id = sample_charging_session.id
        resp = client.delete(f'/api/v1/charging/{session_id}', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert _db_ext.session.get(ChargingSession, session_id) is None

    def test_delete_charging_session_not_found(self, client, api_headers):
        resp = client.delete('/api/v1/charging/99999', headers=api_headers)
        assert resp.status_code == 404


class TestV1Categories:
    def test_list_categories(self, client, api_headers):
        resp = client.get('/api/v1/categories', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'categories' in data
        assert len(data['categories']) > 0
        # Each category should have id and name
        first = data['categories'][0]
        assert 'id' in first
        assert 'name' in first

    def test_list_trip_purposes(self, client, api_headers):
        resp = client.get('/api/v1/trip-purposes', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'purposes' in data
        assert 'business' in [p['id'] for p in data['purposes']]

    def test_list_trip_purposes_no_key(self, client):
        resp = client.get('/api/v1/trip-purposes')
        assert resp.status_code == 401

    def test_list_charger_types(self, client, api_headers):
        resp = client.get('/api/v1/charger-types', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'charger_types' in data
        assert 'home' in [c['id'] for c in data['charger_types']]

    def test_list_charger_types_no_key(self, client):
        resp = client.get('/api/v1/charger-types')
        assert resp.status_code == 401

    def test_list_categories_no_key(self, client):
        resp = client.get('/api/v1/categories')
        assert resp.status_code == 401
