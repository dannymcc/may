"""Issue #282: hour-metered machines must not be serviced to a distance.

Issue #323 made ``Vehicle.tracking_unit`` authoritative for the consumption
and running-cost maths. Two things were left behind, and both are what the
reporter of #282 actually runs into:

* a maintenance schedule could only state its interval in kilometres or
  miles, and ``calculate_next_due`` ran that interval through the km/mi
  conversion before adding it to a reading that was in engine hours;
* every figure derived from an hour reading was still labelled with a
  distance unit, and every form still called the reading an odometer.
"""
from datetime import date

from flask_babel import force_locale

from app import db
from app.models import (
    MAINTENANCE_DUE_SOON_HOURS, MaintenanceSchedule, Vehicle,
)


def _hours_vehicle(test_user, odometer_unit='mi', name='Tractor'):
    vehicle = Vehicle(
        owner_id=test_user.id, name=name, vehicle_type='car',
        fuel_type='diesel', tracking_unit='hours', odometer_unit=odometer_unit,
    )
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


def _schedule(test_user, vehicle, **kwargs):
    schedule = MaintenanceSchedule(
        vehicle_id=vehicle.id, user_id=test_user.id,
        name='Oil change', maintenance_type='oil_change', **kwargs)
    db.session.add(schedule)
    db.session.commit()
    return schedule


class TestHoursMaintenanceInterval:
    def test_hours_interval_added_without_conversion(self, app, test_user):
        """250 hours after 1000 hours is 1250 hours, whatever odometer_unit says."""
        schedule = _schedule(test_user, _hours_vehicle(test_user, 'mi'),
                             interval_hours=250, last_performed_odometer=1000.0)

        schedule.calculate_next_due()

        assert schedule.next_due_odometer == 1250.0

    def test_hours_interval_independent_of_odometer_unit(self, app, test_user):
        """The distance-only odometer_unit preference must not move the figure."""
        km_schedule = _schedule(
            test_user, _hours_vehicle(test_user, 'km', 'Tractor km'),
            interval_hours=250, last_performed_odometer=1000.0)
        mi_schedule = _schedule(
            test_user, _hours_vehicle(test_user, 'mi', 'Tractor mi'),
            interval_hours=250, last_performed_odometer=1000.0)

        km_schedule.calculate_next_due()
        mi_schedule.calculate_next_due()

        assert km_schedule.next_due_odometer == mi_schedule.next_due_odometer

    def test_distance_intervals_ignored_on_an_hours_vehicle(self, app, test_user):
        """A stray km/mi interval must not be read as hours, nor converted.

        A vehicle restored from a backup, or switched to hours before
        anything was logged, can carry a distance interval that means
        nothing here.
        """
        schedule = _schedule(test_user, _hours_vehicle(test_user, 'mi'),
                             interval_km=8000, interval_miles=5000,
                             last_performed_odometer=1000.0)

        schedule.calculate_next_due()

        assert schedule.next_due_odometer is None

    def test_hours_interval_ignored_on_a_distance_vehicle(self, app, test_user, sample_vehicle):
        """The mirror image: a car keeps servicing to km/miles."""
        assert sample_vehicle.tracks_hours() is False
        schedule = _schedule(test_user, sample_vehicle, interval_hours=250,
                             interval_km=8000, last_performed_odometer=10000.0)

        schedule.calculate_next_due()

        unit = sample_vehicle.get_effective_odometer_unit()
        expected = 8000 if unit == 'km' else 8000 * 0.621371
        assert schedule.next_due_odometer == 10000.0 + expected

    def test_months_interval_still_applies_to_an_hours_vehicle(self, app, test_user):
        """Servicing a tractor once a year is still a perfectly good rule."""
        schedule = _schedule(test_user, _hours_vehicle(test_user),
                             interval_months=12,
                             last_performed_date=date(2026, 1, 1),
                             last_performed_odometer=1000.0)

        schedule.calculate_next_due()

        assert schedule.next_due_date == date(2027, 1, 1)


class TestHoursDueSoonMargin:
    def test_due_soon_margin_is_hours_not_five_hundred(self, app, test_user):
        """500 hours ahead would flag every tractor service as due soon."""
        schedule = _schedule(test_user, _hours_vehicle(test_user),
                             next_due_odometer=1250.0)

        assert schedule.is_due_soon(current_odometer=1000.0) is False
        assert schedule.is_due_soon(
            current_odometer=1250.0 - MAINTENANCE_DUE_SOON_HOURS) is True

    def test_distance_vehicle_keeps_the_five_hundred_margin(self, app, test_user, sample_vehicle):
        schedule = _schedule(test_user, sample_vehicle, next_due_odometer=11000.0)

        assert schedule.is_due_soon(current_odometer=10400.0) is False
        assert schedule.is_due_soon(current_odometer=10500.0) is True

    def test_explicit_distance_argument_still_wins(self, app, test_user):
        schedule = _schedule(test_user, _hours_vehicle(test_user),
                             next_due_odometer=1250.0)

        assert schedule.is_due_soon(current_odometer=1000.0, distance=300) is True


class TestScheduleInterval:
    def test_hours_vehicle_reports_its_interval_in_hours(self, app, test_user):
        schedule = _schedule(test_user, _hours_vehicle(test_user),
                             interval_hours=250, interval_km=8000)

        assert schedule.get_interval() == (250, 'h')

    def test_distance_vehicle_reports_km_then_miles(self, app, test_user, sample_vehicle):
        km = _schedule(test_user, sample_vehicle, interval_km=8000, interval_miles=5000)
        assert km.get_interval() == (8000, 'km')

        miles = _schedule(test_user, sample_vehicle, interval_miles=5000)
        assert miles.get_interval() == (5000, 'mi')

    def test_no_reading_interval_reports_nothing(self, app, test_user, sample_vehicle):
        assert _schedule(test_user, sample_vehicle, interval_months=12).get_interval() is None

    def test_schedule_resolves_its_vehicle_before_it_is_flushed(self, app, test_user):
        """calculate_next_due runs on a schedule whose relationship is unset."""
        vehicle = _hours_vehicle(test_user)
        unsaved = MaintenanceSchedule(
            vehicle_id=vehicle.id, user_id=test_user.id, name='Oil change',
            maintenance_type='oil_change', interval_hours=250,
            last_performed_odometer=1000.0)

        unsaved.calculate_next_due()

        assert unsaved.next_due_odometer == 1250.0


class TestMaintenanceRoutes:
    def test_new_schedule_accepts_an_hours_interval(self, app, auth_client, test_user):
        vehicle = _hours_vehicle(test_user)

        resp = auth_client.post('/maintenance/new', data={
            'vehicle_id': str(vehicle.id), 'name': 'Oil change',
            'maintenance_type': 'oil_change', 'interval_hours': '250',
            'last_performed_odometer': '1000',
        }, follow_redirects=True)

        assert resp.status_code == 200
        schedule = MaintenanceSchedule.query.filter_by(vehicle_id=vehicle.id).one()
        assert schedule.interval_hours == 250
        assert schedule.next_due_odometer == 1250.0

    def test_edit_schedule_accepts_an_hours_interval(self, app, auth_client, test_user):
        vehicle = _hours_vehicle(test_user)
        schedule = _schedule(test_user, vehicle, interval_hours=250,
                             last_performed_odometer=1000.0)

        resp = auth_client.post(f'/maintenance/{schedule.id}/edit', data={
            'vehicle_id': str(vehicle.id), 'name': 'Oil change',
            'maintenance_type': 'oil_change', 'interval_hours': '500',
            'last_performed_odometer': '1000',
        }, follow_redirects=True)

        assert resp.status_code == 200
        db.session.refresh(schedule)
        assert schedule.interval_hours == 500
        assert schedule.next_due_odometer == 1500.0

    def test_form_starts_on_the_right_unit_without_scripts(self, app, auth_client, test_user):
        """The interval boxes must be right before any script runs."""
        vehicle = _hours_vehicle(test_user)

        body = auth_client.get(f'/maintenance/new?vehicle_id={vehicle.id}').data.decode()

        assert 'data-interval-distance class="hidden"' in body
        assert 'data-interval-hours class="hidden"' not in body
        assert 'data-tracks-hours="1"' in body
        assert 'Engine hours' in body

    def test_form_hides_the_hours_box_for_a_distance_vehicle(self, app, auth_client, sample_vehicle):
        body = auth_client.get(
            f'/maintenance/new?vehicle_id={sample_vehicle.id}').data.decode()

        assert 'data-interval-hours class="hidden"' in body
        assert 'data-interval-distance class="hidden"' not in body

    def test_index_lists_the_interval_in_hours(self, app, auth_client, test_user):
        vehicle = _hours_vehicle(test_user)
        _schedule(test_user, vehicle, interval_hours=250,
                  last_performed_odometer=1000.0, next_due_odometer=1250.0)

        body = auth_client.get('/maintenance/').data.decode()

        assert 'Every 250 h' in body
        assert '1,250 h' in body
        assert '1,250 mi' not in body


class TestHoursDisplayLabels:
    """The figures were corrected by #323; the labels beside them were not."""

    def test_reading_unit_is_hours(self, app, test_user):
        assert _hours_vehicle(test_user, 'mi').get_reading_unit() == 'h'
        assert _hours_vehicle(test_user, 'km', 'Two').get_reading_unit() == 'h'

    def test_reading_unit_unchanged_for_a_distance_vehicle(self, app, sample_vehicle):
        assert (sample_vehicle.get_reading_unit()
                == sample_vehicle.get_effective_odometer_unit())

    def test_reading_and_span_labels(self, app, test_user, sample_vehicle):
        # The labels are lazy so they translate at render time; force a
        # locale to resolve them outside a request.
        hours = _hours_vehicle(test_user)
        with force_locale('en'):
            assert str(hours.get_reading_label()) == 'Engine hours'
            assert str(hours.get_span_label()) == 'Hours'
            assert str(sample_vehicle.get_reading_label()) == 'Odometer'
            assert str(sample_vehicle.get_span_label()) == 'Distance'

    def test_consumption_unit_is_litres_per_hour(self, app, test_user):
        assert _hours_vehicle(test_user).get_consumption_unit() == 'L / h'

    def test_consumption_unit_defers_to_the_account_for_a_distance_vehicle(self, app, sample_vehicle):
        # None so the template falls back to the account preference it holds.
        assert sample_vehicle.get_consumption_unit() is None

    def test_vehicle_page_labels_readings_in_hours(self, app, auth_client, test_user):
        vehicle = _hours_vehicle(test_user, 'mi')

        body = auth_client.get(f'/vehicles/{vehicle.id}').data.decode()

        assert 'Total Hours' in body
        assert 'Cost per h' in body
        # Never the 'mi' its irrelevant odometer_unit still carries.
        assert 'Total Distance' not in body
        assert 'Cost per mi' not in body
