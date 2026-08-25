import pytest
from app import db
from app.models import Vehicle, ChargingSession
from datetime import date


@pytest.fixture
def ev_vehicle(app, test_user):
    vehicle = Vehicle(
        owner_id=test_user.id,
        name='Tesla Model 3',
        vehicle_type='car',
        make='Tesla',
        model='Model 3',
        year=2023,
        fuel_type='electric',
    )
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


@pytest.fixture
def sample_session(app, test_user, ev_vehicle):
    session = ChargingSession(
        vehicle_id=ev_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 3, 1),
        kwh_added=40.0,
        total_cost=8.0,
        charger_type='ac_home',
    )
    db.session.add(session)
    db.session.commit()
    return session


class TestEVStats:
    """#175 — EV cost/consumption stats must include charging."""

    def test_total_cost_includes_charging(self, app, test_user, ev_vehicle):
        # Pure EV: no fuel logs, but two charging sessions
        ev_vehicle.odometer_unit = 'km'
        db.session.commit()
        db.session.add_all([
            ChargingSession(vehicle_id=ev_vehicle.id, user_id=test_user.id,
                            date=date(2026, 4, 1), odometer=10000, kwh_added=30, total_cost=6.0),
            ChargingSession(vehicle_id=ev_vehicle.id, user_id=test_user.id,
                            date=date(2026, 4, 15), odometer=10500, kwh_added=40, total_cost=8.0),
        ])
        db.session.commit()
        assert ev_vehicle.get_total_cost() == 14.0

    def test_average_charging_consumption_km(self, app, test_user, ev_vehicle):
        ev_vehicle.odometer_unit = 'km'
        db.session.commit()
        db.session.add_all([
            ChargingSession(vehicle_id=ev_vehicle.id, user_id=test_user.id,
                            date=date(2026, 4, 1), odometer=10000, kwh_added=30),
            ChargingSession(vehicle_id=ev_vehicle.id, user_id=test_user.id,
                            date=date(2026, 4, 15), odometer=10500, kwh_added=40),
        ])
        db.session.commit()
        # 70 kWh over 500 km = 14 kWh / 100 km
        consumption = ev_vehicle.get_average_charging_consumption()
        assert consumption is not None
        assert abs(consumption - 14.0) < 0.01

    def test_average_charging_consumption_mi_to_km(self, app, test_user, ev_vehicle):
        """Vehicle in miles, asked for kWh/100km — must convert."""
        ev_vehicle.odometer_unit = 'mi'
        db.session.commit()
        db.session.add_all([
            ChargingSession(vehicle_id=ev_vehicle.id, user_id=test_user.id,
                            date=date(2026, 4, 1), odometer=10000, kwh_added=30),
            ChargingSession(vehicle_id=ev_vehicle.id, user_id=test_user.id,
                            date=date(2026, 4, 15), odometer=10500, kwh_added=40),
        ])
        db.session.commit()
        # 70 kWh over 500 mi = 804.672 km → ~8.70 kWh/100km
        consumption = ev_vehicle.get_average_charging_consumption('km')
        assert consumption is not None
        assert abs(consumption - 8.70) < 0.05

    def test_cost_per_kwh(self, app, test_user, ev_vehicle):
        db.session.add_all([
            ChargingSession(vehicle_id=ev_vehicle.id, user_id=test_user.id,
                            date=date(2026, 4, 1), kwh_added=30, total_cost=9.0),
            ChargingSession(vehicle_id=ev_vehicle.id, user_id=test_user.id,
                            date=date(2026, 4, 15), kwh_added=20, total_cost=4.0),
        ])
        db.session.commit()
        # 13 / 50 = 0.26
        assert abs(ev_vehicle.get_cost_per_kwh() - 0.26) < 0.001

    def test_no_sessions_returns_none(self, app, test_user, ev_vehicle):
        assert ev_vehicle.get_average_charging_consumption() is None
        assert ev_vehicle.get_cost_per_kwh() is None

    def test_fuel_index_lists_charging(self, auth_client, sample_session):
        resp = auth_client.get('/fuel/')
        assert resp.status_code == 200
        assert b'Charging History' in resp.data
        assert b'Tesla Model 3' in resp.data


class TestChargingIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/charging/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/charging/')
        assert resp.status_code == 200

    def test_index_shows_sessions(self, auth_client, sample_session):
        resp = auth_client.get('/charging/')
        assert resp.status_code == 200

    def test_index_orders_same_day_sessions_by_odometer(self, auth_client, test_user, ev_vehicle):
        """Charging sessions logged on the same date should be listed by
        odometer (most recently reached reading first), not by insertion
        order — same issue as #325 for trips (#329)."""
        earlier = ChargingSession(
            vehicle_id=ev_vehicle.id,
            user_id=test_user.id,
            date=date(2026, 8, 22),
            odometer=10000.0,
            kwh_added=20.0,
            location='Morning charge',
        )
        db.session.add(earlier)
        db.session.commit()

        later = ChargingSession(
            vehicle_id=ev_vehicle.id,
            user_id=test_user.id,
            date=date(2026, 8, 22),
            odometer=10200.0,
            kwh_added=15.0,
            location='Afternoon charge',
        )
        db.session.add(later)
        db.session.commit()

        resp = auth_client.get('/charging/')
        assert resp.status_code == 200
        html = resp.data.decode()
        # The session with the higher (later) odometer reading should be
        # listed before the earlier same-day session.
        assert html.index('Afternoon charge') < html.index('Morning charge')

    def test_index_still_orders_by_date_first(self, auth_client, test_user, ev_vehicle):
        """The odometer tie-break must not displace the date ordering (#329)."""
        older = ChargingSession(
            vehicle_id=ev_vehicle.id,
            user_id=test_user.id,
            date=date(2026, 8, 1),
            odometer=20000.0,
            kwh_added=20.0,
            location='Older high-odometer charge',
        )
        newer = ChargingSession(
            vehicle_id=ev_vehicle.id,
            user_id=test_user.id,
            date=date(2026, 8, 22),
            odometer=10000.0,
            kwh_added=15.0,
            location='Newer low-odometer charge',
        )
        db.session.add_all([older, newer])
        db.session.commit()

        resp = auth_client.get('/charging/')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert html.index('Newer low-odometer charge') < html.index('Older high-odometer charge')


class TestChargingNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/charging/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, ev_vehicle):
        resp = auth_client.get('/charging/new')
        assert resp.status_code == 200

    def test_redirects_if_no_ev(self, auth_client, sample_vehicle):
        # sample_vehicle is petrol, so no EV — should redirect
        resp = auth_client.get('/charging/new', follow_redirects=False)
        assert resp.status_code == 302

    def test_create_charging_session(self, auth_client, ev_vehicle, test_user):
        resp = auth_client.post('/charging/new', data={
            'vehicle_id': str(ev_vehicle.id),
            'date': '2024-04-01',
            'kwh_added': '35.0',
            'total_cost': '7.00',
            'charger_type': 'ac_home',
        }, follow_redirects=True)
        assert resp.status_code == 200
        session = ChargingSession.query.filter_by(
            vehicle_id=ev_vehicle.id,
            kwh_added=35.0
        ).first()
        assert session is not None
        assert session.user_id == test_user.id


class TestChargingEdit:
    def test_edit_requires_auth(self, client, sample_session):
        resp = client.get(f'/charging/{sample_session.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_session):
        resp = auth_client.get(f'/charging/{sample_session.id}/edit')
        assert resp.status_code == 200

    def test_edit_charging_session(self, auth_client, sample_session):
        resp = auth_client.post(f'/charging/{sample_session.id}/edit', data={
            'date': '2024-03-01',
            'kwh_added': '45.0',
            'total_cost': '9.00',
            'charger_type': 'dc_fast',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_session)
        assert sample_session.kwh_added == 45.0
        assert sample_session.charger_type == 'dc_fast'


class TestChargingDelete:
    def test_delete_requires_auth(self, client, sample_session):
        resp = client.post(f'/charging/{sample_session.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_charging_session(self, auth_client, sample_session):
        session_id = sample_session.id
        resp = auth_client.post(f'/charging/{session_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(ChargingSession, session_id) is None
