import json
import pytest
from app import db
from app.models import Trip, TripTemplate
from datetime import date


@pytest.fixture
def sample_trip(app, test_user, sample_vehicle):
    trip = Trip(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 2, 1),
        start_odometer=10000.0,
        end_odometer=10150.0,
        purpose='business',
        description='Client meeting',
    )
    db.session.add(trip)
    db.session.commit()
    return trip


class TestTripIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/trips/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/trips/')
        assert resp.status_code == 200

    def test_index_shows_trips(self, auth_client, sample_trip):
        resp = auth_client.get('/trips/')
        assert resp.status_code == 200
        assert b'Client meeting' in resp.data

    def test_index_orders_same_day_trips_by_odometer(self, auth_client, test_user, sample_vehicle):
        """Trips logged on the same date should be listed by odometer
        (most recently driven first), not by insertion order (#325)."""
        earlier = Trip(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 2, 1),
            start_odometer=10000.0,
            end_odometer=10050.0,
            purpose='business',
            description='Morning trip',
        )
        db.session.add(earlier)
        db.session.commit()

        later = Trip(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 2, 1),
            start_odometer=10050.0,
            end_odometer=10120.0,
            purpose='business',
            description='Afternoon trip',
        )
        db.session.add(later)
        db.session.commit()

        resp = auth_client.get('/trips/')
        assert resp.status_code == 200
        html = resp.data.decode()
        # The trip with the higher (later) odometer reading should be
        # listed before the earlier same-day trip.
        assert html.index('Afternoon trip') < html.index('Morning trip')

    def test_index_still_orders_by_date_first(self, auth_client, test_user, sample_vehicle):
        """The odometer tie-break must not displace the date ordering (#325)."""
        older = Trip(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 2, 1),
            start_odometer=20000.0,
            end_odometer=20100.0,
            purpose='business',
            description='Older high-odometer trip',
        )
        newer = Trip(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 3, 1),
            start_odometer=10000.0,
            end_odometer=10100.0,
            purpose='business',
            description='Newer low-odometer trip',
        )
        db.session.add_all([older, newer])
        db.session.commit()

        resp = auth_client.get('/trips/')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert html.index('Newer low-odometer trip') < html.index('Older high-odometer trip')


class TestTripNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/trips/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/trips/new')
        assert resp.status_code == 200

    def test_create_trip(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/trips/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-01',
            'start_odometer': '12000',
            'end_odometer': '12200',
            'purpose': 'business',
            'description': 'Business trip',
            'start_location': 'Office',
            'end_location': 'Client',
        }, follow_redirects=True)
        assert resp.status_code == 200
        trip = Trip.query.filter_by(description='Business trip').first()
        assert trip is not None
        assert trip.start_odometer == 12000.0
        assert trip.end_odometer == 12200.0
        assert trip.user_id == test_user.id

class TestTripNewNoEndOdometer:
    def test_new_requires_auth(self, client):
        resp = client.get('/trips/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/trips/new')
        assert resp.status_code == 200

    def test_create_trip(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/trips/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-01',
            'start_odometer': '12000',
            'purpose': 'business',
            'description': 'No end odometer trip',
            'start_location': 'Office',
            'end_location': 'Client',
        }, follow_redirects=True)
        assert resp.status_code == 200
        trip = Trip.query.filter_by(description='No end odometer trip').first()
        assert trip is not None
        assert trip.start_odometer == 12000.0
        assert trip.end_odometer == None
        assert trip.user_id == test_user.id


class TestTripEdit:
    def test_edit_requires_auth(self, client, sample_trip):
        resp = client.get(f'/trips/{sample_trip.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_trip):
        resp = auth_client.get(f'/trips/{sample_trip.id}/edit')
        assert resp.status_code == 200

    def test_edit_trip(self, auth_client, sample_trip):
        resp = auth_client.post(f'/trips/{sample_trip.id}/edit', data={
            'date': '2024-02-01',
            'start_odometer': '10000',
            'end_odometer': '10200',
            'purpose': 'personal',
            'description': 'Updated trip',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_trip)
        assert sample_trip.description == 'Updated trip'
        assert sample_trip.purpose == 'personal'


class TestTripDelete:
    def test_delete_requires_auth(self, client, sample_trip):
        resp = client.post(f'/trips/{sample_trip.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_trip(self, auth_client, sample_trip):
        trip_id = sample_trip.id
        resp = auth_client.post(f'/trips/{trip_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(Trip, trip_id) is None


@pytest.fixture
def sample_template(app, test_user, sample_vehicle):
    tmpl = TripTemplate(
        user_id=test_user.id,
        vehicle_id=sample_vehicle.id,
        name='Office Commute',
        purpose='commute',
        start_location='Home',
        end_location='Office',
        description='Daily commute',
        notes='Via motorway',
    )
    db.session.add(tmpl)
    db.session.commit()
    return tmpl


class TestTripTemplatesIndex:
    def test_requires_auth(self, client):
        resp = client.get('/trips/templates', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_returns_200(self, auth_client):
        resp = auth_client.get('/trips/templates')
        assert resp.status_code == 200

    def test_shows_templates(self, auth_client, sample_template):
        resp = auth_client.get('/trips/templates')
        assert resp.status_code == 200
        assert b'Office Commute' in resp.data

    def test_empty_state(self, auth_client):
        resp = auth_client.get('/trips/templates')
        assert b'No templates yet' in resp.data


class TestTripTemplatesNew:
    def test_requires_auth(self, client):
        resp = client.get('/trips/templates/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/trips/templates/new')
        assert resp.status_code == 200

    def test_create_template_with_vehicle(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/trips/templates/new', data={
            'name': 'Client Visit',
            'vehicle_id': str(sample_vehicle.id),
            'purpose': 'business',
            'start_location': 'Office',
            'end_location': 'Client HQ',
            'description': 'Weekly client visit',
            'notes': 'Bring laptop',
        }, follow_redirects=True)
        assert resp.status_code == 200
        tmpl = TripTemplate.query.filter_by(name='Client Visit').first()
        assert tmpl is not None
        assert tmpl.user_id == test_user.id
        assert tmpl.vehicle_id == sample_vehicle.id
        assert tmpl.purpose == 'business'
        assert tmpl.start_location == 'Office'
        assert tmpl.end_location == 'Client HQ'

    def test_create_template_without_vehicle(self, auth_client, test_user):
        resp = auth_client.post('/trips/templates/new', data={
            'name': 'Any Vehicle Trip',
            'vehicle_id': '',
            'purpose': 'personal',
        }, follow_redirects=True)
        assert resp.status_code == 200
        tmpl = TripTemplate.query.filter_by(name='Any Vehicle Trip').first()
        assert tmpl is not None
        assert tmpl.vehicle_id is None

    def test_create_redirects_to_index(self, auth_client, sample_vehicle):
        resp = auth_client.post('/trips/templates/new', data={
            'name': 'Test Template',
            'vehicle_id': '',
            'purpose': 'personal',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/trips/templates' in resp.headers['Location']


class TestTripTemplatesEdit:
    def test_requires_auth(self, client, sample_template):
        resp = client.get(f'/trips/templates/{sample_template.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_form_returns_200(self, auth_client, sample_template):
        resp = auth_client.get(f'/trips/templates/{sample_template.id}/edit')
        assert resp.status_code == 200
        assert b'Office Commute' in resp.data

    def test_edit_template(self, auth_client, sample_template):
        resp = auth_client.post(f'/trips/templates/{sample_template.id}/edit', data={
            'name': 'Updated Commute',
            'vehicle_id': str(sample_template.vehicle_id),
            'purpose': 'personal',
            'start_location': 'New Home',
            'end_location': 'Office',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_template)
        assert sample_template.name == 'Updated Commute'
        assert sample_template.purpose == 'personal'
        assert sample_template.start_location == 'New Home'

    def test_cannot_edit_other_users_template(self, client, app, sample_template):
        from app.models import User
        other = User(username='other2', email='other2@example.com')
        other.set_password('Pass123!')
        db.session.add(other)
        db.session.commit()
        client.post('/auth/login', data={'username': 'other2', 'password': 'Pass123!'}, follow_redirects=True)
        resp = client.post(f'/trips/templates/{sample_template.id}/edit', data={
            'name': 'Hijacked', 'vehicle_id': '', 'purpose': 'personal',
        }, follow_redirects=True)
        db.session.refresh(sample_template)
        assert sample_template.name == 'Office Commute'


class TestTripTemplatesDelete:
    def test_requires_auth(self, client, sample_template):
        resp = client.post(f'/trips/templates/{sample_template.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_template(self, auth_client, sample_template):
        tmpl_id = sample_template.id
        resp = auth_client.post(f'/trips/templates/{tmpl_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(TripTemplate, tmpl_id) is None

    def test_cannot_delete_other_users_template(self, client, app, sample_template):
        from app.models import User
        other = User(username='other3', email='other3@example.com')
        other.set_password('Pass123!')
        db.session.add(other)
        db.session.commit()
        client.post('/auth/login', data={'username': 'other3', 'password': 'Pass123!'}, follow_redirects=True)
        resp = client.post(f'/trips/templates/{sample_template.id}/delete', follow_redirects=True)
        assert db.session.get(TripTemplate, sample_template.id) is not None


class TestTripTemplatesData:
    def test_requires_auth(self, client, sample_template):
        resp = client.get(f'/trips/templates/{sample_template.id}/data', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_returns_json(self, auth_client, sample_template):
        resp = auth_client.get(f'/trips/templates/{sample_template.id}/data')
        assert resp.status_code == 200
        assert resp.content_type == 'application/json'

    def test_json_contains_template_fields(self, auth_client, sample_template):
        resp = auth_client.get(f'/trips/templates/{sample_template.id}/data')
        data = json.loads(resp.data)
        assert data['id'] == sample_template.id
        assert data['vehicle_id'] == sample_template.vehicle_id
        assert data['purpose'] == 'commute'
        assert data['start_location'] == 'Home'
        assert data['end_location'] == 'Office'
        assert data['description'] == 'Daily commute'
        assert data['notes'] == 'Via motorway'

    def test_cannot_access_other_users_template_data(self, client, app, sample_template):
        from app.models import User
        other = User(username='other4', email='other4@example.com')
        other.set_password('Pass123!')
        db.session.add(other)
        db.session.commit()
        client.post('/auth/login', data={'username': 'other4', 'password': 'Pass123!'}, follow_redirects=True)
        resp = client.get(f'/trips/templates/{sample_template.id}/data')
        assert resp.status_code == 403


class TestTripNewWithTemplate:
    def test_new_form_shows_template_selector(self, auth_client, sample_vehicle, sample_template):
        resp = auth_client.get('/trips/new')
        assert resp.status_code == 200
        assert b'Load template' in resp.data
        assert b'Office Commute' in resp.data

    def test_new_form_no_template_selector_without_templates(self, auth_client, sample_vehicle):
        resp = auth_client.get('/trips/new')
        assert resp.status_code == 200
        assert b'Load template' not in resp.data

    def test_template_id_param_accepted(self, auth_client, sample_vehicle, sample_template):
        resp = auth_client.get(f'/trips/new?template_id={sample_template.id}')
        assert resp.status_code == 200


class TestTripReport:
    def test_report_requires_auth(self, client):
        resp = client.get('/trips/report', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_report_returns_200(self, auth_client):
        resp = auth_client.get('/trips/report')
        assert resp.status_code == 200

    def test_report_with_trips(self, auth_client, sample_trip):
        resp = auth_client.get('/trips/report')
        assert resp.status_code == 200


class TestTripFuelLevel:
    """Fuel gauge readings on trips (#273)."""

    def test_fuel_used_from_levels_and_tank_capacity(self, app, sample_trip, sample_vehicle):
        sample_vehicle.tank_capacity = 50.0
        sample_trip.start_fuel_level = 80.0
        sample_trip.end_fuel_level = 60.0
        db.session.commit()
        assert sample_trip.fuel_used == pytest.approx(10.0)

    def test_fuel_used_none_without_tank_capacity(self, app, sample_trip, sample_vehicle):
        sample_vehicle.tank_capacity = None
        sample_trip.start_fuel_level = 80.0
        sample_trip.end_fuel_level = 60.0
        db.session.commit()
        assert sample_trip.fuel_used is None

    def test_fuel_used_none_without_readings(self, app, sample_trip, sample_vehicle):
        sample_vehicle.tank_capacity = 50.0
        sample_trip.start_fuel_level = 80.0
        sample_trip.end_fuel_level = None
        db.session.commit()
        assert sample_trip.fuel_used is None

    def test_fuel_used_none_when_refuelled_mid_trip(self, app, sample_trip, sample_vehicle):
        """Ending fuller than it started means a fill-up, so the figure is meaningless."""
        sample_vehicle.tank_capacity = 50.0
        sample_trip.start_fuel_level = 30.0
        sample_trip.end_fuel_level = 90.0
        db.session.commit()
        assert sample_trip.fuel_used is None

    def test_create_trip_with_fuel_levels(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/trips/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-01',
            'start_odometer': '12000',
            'end_odometer': '12200',
            'start_fuel_level': '75',
            'end_fuel_level': '50',
            'purpose': 'business',
        }, follow_redirects=True)
        assert resp.status_code == 200
        trip = Trip.query.filter_by(start_odometer=12000.0).first()
        assert trip is not None
        assert trip.start_fuel_level == 75.0
        assert trip.end_fuel_level == 50.0

    def test_create_trip_without_fuel_levels(self, auth_client, sample_vehicle):
        resp = auth_client.post('/trips/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-02',
            'start_odometer': '13000',
            'end_odometer': '13100',
            'start_fuel_level': '',
            'end_fuel_level': '',
            'purpose': 'personal',
        }, follow_redirects=True)
        assert resp.status_code == 200
        trip = Trip.query.filter_by(start_odometer=13000.0).first()
        assert trip is not None
        assert trip.start_fuel_level is None
        assert trip.end_fuel_level is None

    def test_create_trip_rejects_out_of_range_level(self, auth_client, sample_vehicle):
        resp = auth_client.post('/trips/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-03',
            'start_odometer': '14000',
            'end_odometer': '14100',
            'start_fuel_level': '150',
            'purpose': 'business',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Trip.query.filter_by(start_odometer=14000.0).first() is None

    def test_edit_trip_fuel_levels(self, auth_client, sample_trip):
        resp = auth_client.post(f'/trips/{sample_trip.id}/edit', data={
            'date': '2024-02-01',
            'start_odometer': '10000',
            'end_odometer': '10150',
            'start_fuel_level': '90',
            'end_fuel_level': '70.5',
            'purpose': 'business',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_trip)
        assert sample_trip.start_fuel_level == 90.0
        assert sample_trip.end_fuel_level == 70.5

    def test_edit_trip_rejects_out_of_range_level(self, auth_client, sample_trip):
        resp = auth_client.post(f'/trips/{sample_trip.id}/edit', data={
            'date': '2024-02-01',
            'start_odometer': '10000',
            'end_odometer': '10150',
            'start_fuel_level': '-5',
            'purpose': 'business',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_trip)
        assert sample_trip.start_fuel_level is None

    def test_index_shows_fuel_used(self, auth_client, sample_trip, sample_vehicle):
        sample_vehicle.tank_capacity = 60.0
        sample_trip.start_fuel_level = 100.0
        sample_trip.end_fuel_level = 75.0
        db.session.commit()
        resp = auth_client.get('/trips/')
        assert resp.status_code == 200
        assert b'15.0' in resp.data

    def test_index_shows_levels_without_tank_capacity(self, auth_client, sample_trip, sample_vehicle):
        sample_vehicle.tank_capacity = None
        sample_trip.start_fuel_level = 80.0
        sample_trip.end_fuel_level = 55.0
        db.session.commit()
        resp = auth_client.get('/trips/')
        assert resp.status_code == 200
        assert b'80% ' in resp.data

    def test_to_dict_includes_fuel_fields(self, app, sample_trip, sample_vehicle):
        sample_vehicle.tank_capacity = 40.0
        sample_trip.start_fuel_level = 50.0
        sample_trip.end_fuel_level = 25.0
        db.session.commit()
        data = sample_trip.to_dict()
        assert data['start_fuel_level'] == 50.0
        assert data['end_fuel_level'] == 25.0
        assert data['fuel_used'] == pytest.approx(10.0)
