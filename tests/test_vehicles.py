import pytest
from app import db
from app.models import Vehicle


class TestVehicleIndex:
    def test_list_requires_auth(self, client):
        resp = client.get('/vehicles/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_list_returns_200(self, auth_client):
        resp = auth_client.get('/vehicles/')
        assert resp.status_code == 200

    def test_list_shows_vehicles(self, auth_client, sample_vehicle):
        resp = auth_client.get('/vehicles/')
        assert b'Test Car' in resp.data


class TestVehicleNew:
    def test_get_new_form_requires_auth(self, client):
        resp = client.get('/vehicles/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client):
        resp = auth_client.get('/vehicles/new')
        assert resp.status_code == 200

    def test_create_vehicle(self, auth_client, test_user):
        resp = auth_client.post('/vehicles/new', data={
            'name': 'My New Car',
            'vehicle_type': 'car',
            'make': 'Honda',
            'model': 'Civic',
            'year': '2022',
            'fuel_type': 'petrol',
            'tracking_unit': 'mileage',
        }, follow_redirects=True)
        assert resp.status_code == 200
        vehicle = Vehicle.query.filter_by(name='My New Car').first()
        assert vehicle is not None
        assert vehicle.make == 'Honda'
        assert vehicle.owner_id == test_user.id


class TestVehicleView:
    def test_view_requires_auth(self, client, sample_vehicle):
        resp = client.get(f'/vehicles/{sample_vehicle.id}', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_view_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Test Car' in resp.data

    def test_view_404_for_nonexistent(self, auth_client):
        resp = auth_client.get('/vehicles/99999')
        assert resp.status_code == 404


class TestVehicleEdit:
    def test_edit_requires_auth(self, client, sample_vehicle):
        resp = client.get(f'/vehicles/{sample_vehicle.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}/edit')
        assert resp.status_code == 200

    def test_edit_form_renders_null_fields_blank(self, auth_client, sample_vehicle):
        # Nullable numeric fields (tank capacity etc.) must render as empty
        # strings, not the literal text "None", which blocks validation on
        # save (#241).
        sample_vehicle.tank_capacity = None
        db.session.commit()
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}/edit')
        assert resp.status_code == 200
        assert b'value="None"' not in resp.data

    def test_edit_vehicle(self, auth_client, sample_vehicle):
        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': 'Updated Car',
            'vehicle_type': 'car',
            'make': 'Toyota',
            'model': 'Camry',
            'year': '2024',
            'fuel_type': 'petrol',
            'tracking_unit': 'mileage',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.name == 'Updated Car'
        assert sample_vehicle.model == 'Camry'


class TestVehicleDelete:
    def test_delete_requires_auth(self, client, sample_vehicle):
        resp = client.post(f'/vehicles/{sample_vehicle.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_vehicle(self, auth_client, sample_vehicle):
        vehicle_id = sample_vehicle.id
        resp = auth_client.post(f'/vehicles/{vehicle_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert Vehicle.query.get(vehicle_id) is None


class TestVehicleArchive:
    def test_archive_vehicle(self, auth_client, sample_vehicle):
        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/archive', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.is_active is False

    def test_unarchive_vehicle(self, auth_client, sample_vehicle):
        sample_vehicle.is_active = False
        db.session.commit()

        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/unarchive', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.is_active is True

    def test_archived_vehicles_shown_with_param(self, auth_client, sample_vehicle):
        sample_vehicle.is_active = False
        db.session.commit()

        resp = auth_client.get('/vehicles/?archived=true')
        assert resp.status_code == 200
        assert b'Test Car' in resp.data


class TestVehicleSharing:
    def test_is_shared_defaults_false(self, sample_vehicle):
        assert sample_vehicle.is_shared is False

    def test_shared_vehicle_visible_to_other_user(self, app, test_user, sample_vehicle):
        from app.models import User
        other = User(username='other_user', email='other@example.com')
        other.set_password('OtherPass123!')
        db.session.add(other)
        db.session.commit()

        # Not shared yet — other user should not see it
        assert sample_vehicle not in other.get_all_vehicles()

        # Mark as shared
        sample_vehicle.is_shared = True
        db.session.commit()

        assert sample_vehicle in other.get_all_vehicles()

    def test_edit_vehicle_sets_is_shared(self, auth_client, sample_vehicle):
        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': sample_vehicle.name,
            'vehicle_type': sample_vehicle.vehicle_type,
            'fuel_type': sample_vehicle.fuel_type,
            'tracking_unit': 'mileage',
            'is_active': 'on',
            'is_shared': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.is_shared is True

    def test_edit_vehicle_clears_is_shared(self, auth_client, sample_vehicle):
        sample_vehicle.is_shared = True
        db.session.commit()

        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': sample_vehicle.name,
            'vehicle_type': sample_vehicle.vehicle_type,
            'fuel_type': sample_vehicle.fuel_type,
            'tracking_unit': 'mileage',
            'is_active': 'on',
            # is_shared omitted → checkbox unchecked
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.is_shared is False

    def test_shared_badge_shown_in_vehicle_list(self, auth_client, sample_vehicle):
        sample_vehicle.is_shared = True
        db.session.commit()
        resp = auth_client.get('/vehicles/')
        assert resp.status_code == 200
        assert b'Shared' in resp.data


class TestVehicleViewMaintenancePanel:
    def test_view_shows_maintenance_panel(self, auth_client, app, test_user, sample_vehicle):
        from app.models import MaintenanceSchedule
        from datetime import date, timedelta
        schedule = MaintenanceSchedule(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            name='Oil Change',
            maintenance_type='oil_change',
            next_due_date=date.today() + timedelta(days=15),
            is_active=True,
        )
        db.session.add(schedule)
        db.session.commit()
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Upcoming Maintenance' in resp.data
        assert b'Oil Change' in resp.data

    def test_view_hides_maintenance_panel_when_empty(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Upcoming Maintenance' not in resp.data
