"""Issue #324: the presentation surfaces #282 did not reach.

#282 labelled an hours-metered vehicle's own page, its maintenance list, the
calendar feed, the PDF report and most logging forms in engine hours. It
deliberately stopped short of four things, and this module covers them:

* the trip and charging forms, which still called the reading an odometer
  and sized it in the account's distance unit;
* the remaining forms, which took the *unit* from the vehicle but still
  called the field "Odometer" — a machine with no odometer to read;
* the CSV exports, which stamped every row with the vehicle's distance
  unit, filing engine hours under a distance heading;
* totals that span several vehicles, which added engine hours to miles and
  labelled the result as a distance.

A distance-metered vehicle must come through all of this unchanged.
"""
import io
import zipfile
from datetime import date

import pytest

from app import db
from app.models import Expense, FuelLog, Trip, Vehicle
from app.utils import shared_reading_unit


@pytest.fixture
def tractor(app, test_user):
    """An hours-metered vehicle.

    Its odometer_unit is deliberately 'mi' — meaningless for a machine with
    no odometer, but it is exactly what a stray distance label would be
    drawn from, so any 'mi' against this vehicle is the bug.
    """
    vehicle = Vehicle(
        owner_id=test_user.id, name='Tractor', vehicle_type='car',
        fuel_type='diesel', tracking_unit='hours', odometer_unit='mi',
    )
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


@pytest.fixture
def electric_tractor(app, test_user):
    """Electric plant: chargeable, and still metered in engine hours."""
    vehicle = Vehicle(
        owner_id=test_user.id, name='Yard shunter', vehicle_type='car',
        fuel_type='electric', tracking_unit='hours', odometer_unit='mi',
    )
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


class TestSharedReadingUnit:
    def test_one_metering_gives_a_unit(self, app, sample_vehicle, tractor):
        assert shared_reading_unit([sample_vehicle], 'mi') == 'mi'
        assert shared_reading_unit([tractor], 'mi') == 'h'

    def test_mixed_metering_gives_none(self, app, sample_vehicle, tractor):
        # Neither unit describes the sum, so the caller must say so.
        assert shared_reading_unit([sample_vehicle, tractor], 'mi') is None

    def test_no_vehicles_gives_none(self, app):
        assert shared_reading_unit([], 'mi') is None


class TestLoggingFormsAskForTheRightThing:
    """The word, not just the unit in the bracket."""

    def test_trip_form_asks_for_engine_hours(self, auth_client, tractor):
        # Assert on the rendered label, not the page: the script block
        # carries every wording as a constant for the on-change swap.
        body = auth_client.get('/trips/new').get_data(as_text=True)
        assert '<span id="start-reading-label">Start Hours</span>' in body
        assert '<span id="end-reading-label">End Hours</span>' in body
        assert 'data-hours-metered="true"' in body

    def test_charging_form_asks_for_engine_hours(self, auth_client, electric_tractor):
        body = auth_client.get('/charging/new').get_data(as_text=True)
        assert '<span id="odometer-reading-label">Engine hours</span>' in body
        assert 'data-odometer-unit="h"' in body

    def test_fuel_form_asks_for_engine_hours(self, auth_client, tractor):
        body = auth_client.get('/fuel/new').get_data(as_text=True)
        assert 'Engine hours' in body
        assert 'data-reading-label="Engine hours"' in body

    def test_expense_form_asks_for_engine_hours(self, auth_client, tractor):
        body = auth_client.get('/expenses/new').get_data(as_text=True)
        assert 'Engine hours' in body
        assert 'data-reading-label="Engine hours"' in body

    def test_note_form_asks_for_engine_hours(self, auth_client, tractor):
        body = auth_client.get('/notes/new').get_data(as_text=True)
        assert 'Engine hours' in body

    def test_allowance_form_asks_for_hours_not_distance(self, auth_client, tractor):
        # An allowance records a span covered, so it takes the span label.
        body = auth_client.get('/allowance/new').get_data(as_text=True)
        assert 'data-span-label="Hours"' in body

    def test_distance_vehicle_forms_are_unchanged(self, auth_client, sample_vehicle):
        # No rendered label may say hours for a vehicle with an odometer.
        for url in ('/fuel/new', '/expenses/new', '/notes/new'):
            body = auth_client.get(url).get_data(as_text=True)
            assert '>Engine hours<' not in body, url
            assert 'data-reading-label="Odometer"' in body, url

    def test_distance_vehicle_trip_form_keeps_its_wording(self, auth_client, sample_vehicle):
        body = auth_client.get('/trips/new').get_data(as_text=True)
        assert '<span id="start-reading-label">Start Odometer</span>' in body
        assert '<span id="end-reading-label">End Odometer</span>' in body
        assert 'data-hours-metered="false"' in body


class TestExportsDoNotMixUnits:
    def _csv(self, auth_client, name):
        response = auth_client.get('/api/export/csv')
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            return archive.read(name).decode()

    def test_fuel_rows_state_hours(self, auth_client, tractor, test_user):
        db.session.add(FuelLog(
            vehicle_id=tractor.id, user_id=test_user.id, date=date(2026, 1, 1),
            odometer=50, volume=20.0, total_cost=30.0, is_full_tank=True))
        db.session.commit()

        rows = self._csv(auth_client, 'fuel_logs.csv')
        assert ',h,' in rows
        assert ',mi,' not in rows

    def test_expense_rows_state_hours(self, auth_client, tractor, test_user):
        db.session.add(Expense(
            vehicle_id=tractor.id, user_id=test_user.id, date=date(2026, 2, 1),
            category='maintenance', description='Oil change', cost=40.0, odometer=60))
        db.session.commit()

        rows = self._csv(auth_client, 'expenses.csv')
        assert ',60.0,h,' in rows

    def test_vehicle_row_states_hours(self, auth_client, tractor):
        rows = self._csv(auth_client, 'vehicles.csv')
        assert ',h,' in rows

    def test_a_mixed_fleet_keeps_each_row_honest(
            self, auth_client, sample_vehicle, tractor, test_user):
        # The whole point of a per-row unit: both vehicles export into one
        # file and each row still says what its own number means.
        db.session.add_all([
            FuelLog(vehicle_id=tractor.id, user_id=test_user.id,
                    date=date(2026, 1, 1), odometer=50, volume=20.0, is_full_tank=True),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 1, 1), odometer=10000, volume=40.0, is_full_tank=True),
        ])
        db.session.commit()

        rows = self._csv(auth_client, 'fuel_logs.csv')
        assert ',h,' in rows
        assert ',km,' in rows

    def test_distance_only_export_is_unchanged(
            self, auth_client, sample_vehicle, sample_fuel_log):
        rows = self._csv(auth_client, 'fuel_logs.csv')
        assert ',km,' in rows
        assert ',h,' not in rows


class TestTotalsDoNotMixUnits:
    def test_dashboard_discloses_a_mixed_fleet(self, auth_client, sample_vehicle, tractor):
        body = auth_client.get('/dashboard').get_data(as_text=True)
        assert 'mixed units' in body

    def test_dashboard_distance_only_fleet_is_unchanged(self, auth_client, sample_vehicle):
        body = auth_client.get('/dashboard').get_data(as_text=True)
        assert 'mixed units' not in body
        assert 'Cost per mi' in body

    def test_dashboard_hours_only_fleet_reads_in_hours(self, auth_client, tractor):
        body = auth_client.get('/dashboard').get_data(as_text=True)
        assert 'mixed units' not in body
        assert 'Cost per h' in body

    def _two_trips(self, test_user, sample_vehicle, tractor):
        db.session.add_all([
            Trip(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                 date=date(2026, 3, 1), start_odometer=10000, end_odometer=10050,
                 purpose='business'),
            Trip(vehicle_id=tractor.id, user_id=test_user.id,
                 date=date(2026, 3, 2), start_odometer=50, end_odometer=58,
                 purpose='business'),
        ])
        db.session.commit()

    def test_trip_list_and_report_disclose_mixed_totals(
            self, auth_client, sample_vehicle, tractor, test_user):
        self._two_trips(test_user, sample_vehicle, tractor)

        assert 'mixed units' in auth_client.get('/trips/').get_data(as_text=True)
        assert 'mixed units' in auth_client.get('/trips/report').get_data(as_text=True)

    def test_trip_rows_carry_their_own_vehicle_unit(
            self, auth_client, sample_vehicle, tractor, test_user):
        self._two_trips(test_user, sample_vehicle, tractor)

        body = auth_client.get('/trips/').get_data(as_text=True)
        assert '50.0 km' in body
        assert '8.0 h' in body

    def test_trip_totals_for_one_metering_are_unchanged(
            self, auth_client, sample_vehicle, test_user):
        db.session.add(Trip(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 3, 1), start_odometer=10000, end_odometer=10050,
            purpose='business'))
        db.session.commit()

        body = auth_client.get('/trips/').get_data(as_text=True)
        assert 'mixed units' not in body


class TestHomeAssistant:
    def test_odometer_unit_follows_the_vehicle(self, client, tractor, test_user):
        # current_odometer is the raw stored reading, so for this vehicle it
        # is engine hours whatever the account prefers.
        if not test_user.api_key:
            test_user.generate_api_key()
            db.session.commit()

        response = client.get(
            f'/api/ha/vehicles/{tractor.id}',
            headers={'Authorization': f'Bearer {test_user.api_key}'})
        assert response.status_code == 200
        assert response.get_json()['unit_distance'] == 'h'

    def test_distance_vehicle_unit_is_unchanged(self, client, sample_vehicle, test_user):
        if not test_user.api_key:
            test_user.generate_api_key()
            db.session.commit()

        response = client.get(
            f'/api/ha/vehicles/{sample_vehicle.id}',
            headers={'Authorization': f'Bearer {test_user.api_key}'})
        assert response.status_code == 200
        assert response.get_json()['unit_distance'] == 'km'
