"""Repro for issue #323: Vehicle.tracking_unit is not authoritative.

Vehicle.tracking_unit ('mileage' | 'hours') is stored on the model and set
from the vehicle form, but nothing in the consumption maths in
app/models.py checks it. Vehicle._valid_consumption_segments,
get_average_consumption and FuelLog.get_consumption all treat the
`odometer` column as a distance unconditionally, running it through
_distance_in(distance, odometer_unit, 'km'/'mi') regardless of
tracking_unit. For an 'hours' vehicle this means its hour readings get
silently scaled by the km<->mi conversion factor, as if 50 engine hours
were 50 miles.

These tests assert an invariant that must hold no matter which exact
hours-based formula the eventual fix adopts: an hours-tracked vehicle's
computed consumption must not change just because its (purely cosmetic,
distance-only) odometer_unit preference is 'km' vs 'mi' — hours never
convert by a distance factor. Today it does change, because the code
runs hours through the distance-conversion path.
"""
from datetime import date

from app import db
from app.models import Vehicle, FuelLog


class TestHoursTrackingUnitConsumption:
    def _hours_vehicle(self, test_user, odometer_unit):
        v = Vehicle(
            owner_id=test_user.id, name='Tractor', vehicle_type='car',
            fuel_type='diesel', tracking_unit='hours', odometer_unit=odometer_unit,
        )
        db.session.add(v)
        db.session.commit()
        db.session.add_all([
            FuelLog(vehicle_id=v.id, user_id=test_user.id, date=date(2026, 1, 1),
                    odometer=0, volume=20.0, is_full_tank=True),
            FuelLog(vehicle_id=v.id, user_id=test_user.id, date=date(2026, 1, 15),
                    odometer=50, volume=20.0, is_full_tank=True),
        ])
        db.session.commit()
        return v

    def test_average_consumption_independent_of_odometer_unit(self, app, test_user):
        """50 engine hours must not behave as 50 miles (issue #323 / #282).

        Two vehicles with identical hour readings and fuel but different
        (irrelevant, distance-only) odometer_unit settings must produce the
        same consumption figure. Today they don't: the km vehicle reads 50
        as 50 km, the mi vehicle reads 50 as 50 miles and converts it to
        ~80.5 km before dividing, because the code has no idea the vehicle
        is tracking hours.
        """
        km_vehicle = self._hours_vehicle(test_user, 'km')
        mi_vehicle = self._hours_vehicle(test_user, 'mi')

        km_result = km_vehicle.get_average_consumption()
        mi_result = mi_vehicle.get_average_consumption()

        assert km_result is not None
        assert mi_result is not None
        assert abs(km_result - mi_result) < 0.01, (
            f"hours-tracked consumption changed with odometer_unit alone "
            f"(km={km_result!r}, mi={mi_result!r}) — 50 hours is being "
            f"treated as a distance and converted like miles"
        )

    def test_fuel_log_get_consumption_independent_of_odometer_unit(self, app, test_user):
        """Same invariant, exercised through FuelLog.get_consumption directly."""
        km_vehicle = self._hours_vehicle(test_user, 'km')
        mi_vehicle = self._hours_vehicle(test_user, 'mi')

        km_log = km_vehicle.fuel_logs.order_by(FuelLog.odometer.desc()).first()
        mi_log = mi_vehicle.fuel_logs.order_by(FuelLog.odometer.desc()).first()

        km_result = km_log.get_consumption()
        mi_result = mi_log.get_consumption()

        assert km_result is not None
        assert mi_result is not None
        assert abs(km_result - mi_result) < 0.01, (
            f"FuelLog.get_consumption for an hours-tracked vehicle changed "
            f"with odometer_unit alone (km={km_result!r}, mi={mi_result!r})"
        )

    def test_mileage_vehicle_unaffected(self, app, test_user, sample_vehicle):
        """Regression guard: a 'mileage' vehicle (the default) must keep
        behaving exactly as it does today — this is the acceptance
        criterion that today's fix must not break."""
        assert sample_vehicle.tracking_unit == 'mileage'
        db.session.add_all([
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2024, 1, 1), odometer=10000.0, volume=40.0, is_full_tank=True),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2024, 1, 15), odometer=10500.0, volume=35.0, is_full_tank=True),
        ])
        db.session.commit()
        # Same figure documented in TestFuelLogConsumption.test_get_consumption_with_previous_log
        assert abs(sample_vehicle.get_average_consumption() - 7.0) < 0.01


class TestHoursTractorFigures:
    """The tractor case from #282, with the numbers spelled out.

    The unit is derived from the owning vehicle at read time, so an
    hours-tracked vehicle's span is engine hours and never touches the
    km/mi conversion.
    """

    def _tractor(self, test_user):
        v = Vehicle(
            owner_id=test_user.id, name='Tractor', vehicle_type='car',
            fuel_type='diesel', tracking_unit='hours', odometer_unit='mi',
        )
        db.session.add(v)
        db.session.commit()
        db.session.add_all([
            FuelLog(vehicle_id=v.id, user_id=test_user.id, date=date(2026, 1, 1),
                    odometer=0, volume=20.0, total_cost=30.0, is_full_tank=True),
            FuelLog(vehicle_id=v.id, user_id=test_user.id, date=date(2026, 1, 15),
                    odometer=50, volume=20.0, total_cost=30.0, is_full_tank=True),
        ])
        db.session.commit()
        return v

    def test_average_consumption_is_litres_per_hour(self, app, test_user):
        # 20 L over 50 engine hours = 0.4 L/hour. Treated as 50 miles it
        # would have come out as (20 / 80.4672) * 100 = 24.9 "L/100km".
        tractor = self._tractor(test_user)
        assert abs(tractor.get_average_consumption() - 0.4) < 0.0001

    def test_consumption_unit_preference_is_ignored_for_hours(self, app, test_user):
        """mpg, km/L and L/100km are all named for a distance a tractor
        never records, so the hours figure is the same whichever is asked
        for."""
        tractor = self._tractor(test_user)
        for unit in ('L/100km', 'mpg', 'mpg_us', 'km/L', None):
            assert abs(tractor.get_average_consumption(unit) - 0.4) < 0.0001

    def test_fuel_log_consumption_is_litres_per_hour(self, app, test_user):
        tractor = self._tractor(test_user)
        log = tractor.fuel_logs.order_by(FuelLog.odometer.desc()).first()
        assert abs(log.get_consumption() - 0.4) < 0.0001

    def test_total_distance_ignores_distance_unit(self, app, test_user):
        """50 engine hours are 50 engine hours whichever distance unit is
        asked for — there is no conversion to apply to an hour."""
        tractor = self._tractor(test_user)
        assert tractor.get_total_distance() == 50
        assert tractor.get_total_distance('km') == 50
        assert tractor.get_total_distance('mi') == 50

    def test_cost_per_unit_is_per_hour(self, app, test_user):
        # £60 of fuel over 50 engine hours = £1.20 per hour.
        tractor = self._tractor(test_user)
        assert abs(tractor.get_cost_per_distance() - 1.2) < 0.0001

    def test_charging_consumption_is_per_hundred_hours(self, app, test_user):
        """Electric plant is tracked in hours too, so kWh per 100 hours."""
        from app.models import ChargingSession

        v = Vehicle(
            owner_id=test_user.id, name='Electric loader', vehicle_type='car',
            fuel_type='electric', tracking_unit='hours', odometer_unit='mi',
        )
        db.session.add(v)
        db.session.commit()
        db.session.add_all([
            ChargingSession(vehicle_id=v.id, user_id=test_user.id,
                            date=date(2026, 1, 1), odometer=0, kwh_added=10.0),
            ChargingSession(vehicle_id=v.id, user_id=test_user.id,
                            date=date(2026, 1, 15), odometer=50, kwh_added=10.0),
        ])
        db.session.commit()
        # 20 kWh over 50 hours = 40 kWh per 100 hours; as miles it would
        # have been converted to 80.47 km and read 24.9.
        assert abs(v.get_average_charging_consumption() - 40.0) < 0.0001


class TestMileageRegression:
    """A 'mileage' vehicle must produce byte-identical figures to before."""

    def _car(self, test_user, odometer_unit):
        v = Vehicle(
            owner_id=test_user.id, name='Car', vehicle_type='car',
            fuel_type='petrol', tracking_unit='mileage', odometer_unit=odometer_unit,
        )
        db.session.add(v)
        db.session.commit()
        db.session.add_all([
            FuelLog(vehicle_id=v.id, user_id=test_user.id, date=date(2024, 1, 1),
                    odometer=10000.0, volume=40.0, total_cost=60.0, is_full_tank=True),
            FuelLog(vehicle_id=v.id, user_id=test_user.id, date=date(2024, 1, 15),
                    odometer=10500.0, volume=35.0, total_cost=52.5, is_full_tank=True),
        ])
        db.session.commit()
        return v

    def test_km_vehicle_figures_unchanged(self, app, test_user):
        car = self._car(test_user, 'km')
        log = car.fuel_logs.order_by(FuelLog.odometer.desc()).first()
        assert car.get_average_consumption() == (35.0 / 500.0) * 100
        assert log.get_consumption() == (35.0 / 500.0) * 100
        assert car.get_average_consumption('km/L') == 500.0 / 35.0
        assert car.get_total_distance('km') == 500.0
        assert car.get_cost_per_distance() == 112.5 / 500.0

    def test_mi_vehicle_still_converts(self, app, test_user):
        """A distance-tracked vehicle keeps converting exactly as before —
        the km/mi factor is only skipped for hours."""
        car = self._car(test_user, 'mi')
        km = 500.0 * 1.609344
        assert car.get_average_consumption() == (35.0 / km) * 100
        assert car.get_average_consumption('mpg') == 500.0 / (35.0 / 4.54609)
        assert car.get_total_distance('km') == km
        assert car.get_total_distance() == 500.0

    def test_mileage_charging_consumption_unchanged(self, app, test_user):
        from app.models import ChargingSession

        car = self._car(test_user, 'mi')
        db.session.add_all([
            ChargingSession(vehicle_id=car.id, user_id=test_user.id,
                            date=date(2024, 1, 1), odometer=10000.0, kwh_added=10.0),
            ChargingSession(vehicle_id=car.id, user_id=test_user.id,
                            date=date(2024, 1, 15), odometer=10500.0, kwh_added=10.0),
        ])
        db.session.commit()
        assert car.get_average_charging_consumption() == (20.0 / 500.0) * 100
        assert car.get_average_charging_consumption('km') == (20.0 / (500.0 * 1.609344)) * 100


class TestTrackingUnitChangeGuard:
    """Changing tracking_unit once readings exist would reinterpret them,
    so the edit route refuses that field (#323)."""

    def test_change_refused_once_fuel_logs_exist(self, app, auth_client, test_user, sample_vehicle):
        db.session.add(FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 1), odometer=10000.0, volume=40.0, is_full_tank=True))
        db.session.commit()

        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': 'Renamed', 'vehicle_type': 'car', 'fuel_type': 'petrol',
            'tracking_unit': 'hours',
        }, follow_redirects=True)

        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.tracking_unit == 'mileage'
        # The rest of the edit still saves.
        assert sample_vehicle.name == 'Renamed'

    def test_change_allowed_before_any_reading(self, app, auth_client, sample_vehicle):
        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': sample_vehicle.name, 'vehicle_type': 'car', 'fuel_type': 'petrol',
            'tracking_unit': 'hours',
        }, follow_redirects=True)

        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.tracking_unit == 'hours'

    def test_unchanged_unit_saves_normally_with_readings(self, app, auth_client, test_user, sample_vehicle):
        db.session.add(FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 1), odometer=10000.0, volume=40.0, is_full_tank=True))
        db.session.commit()

        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': 'Still Fine', 'vehicle_type': 'car', 'fuel_type': 'petrol',
            'tracking_unit': 'mileage',
        }, follow_redirects=True)

        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.name == 'Still Fine'
        assert sample_vehicle.tracking_unit == 'mileage'

    def test_has_odometer_readings_sees_other_record_types(self, app, test_user, sample_vehicle, sample_trip):
        """A vehicle with no fuel logs but trips against its odometer still
        has readings that a unit change would reinterpret."""
        assert sample_vehicle.fuel_logs.first() is None
        assert sample_vehicle.has_odometer_readings() is True
