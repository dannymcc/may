"""Tests for app/models.py"""
import pytest
from datetime import date, timedelta, datetime

from app import db
from app.utils import utcnow
from app.models import (
    User, Vehicle, FuelLog, Expense, Reminder, MaintenanceSchedule,
    RecurringExpense, FuelStation, FuelPriceHistory, Trip, ChargingSession,
    AppSettings,
    FUEL_TYPES, EXPENSE_CATEGORIES, VEHICLE_TYPES, ODOMETER_UNITS,
    REMINDER_TYPES, RECURRENCE_OPTIONS, TRIP_PURPOSES, CHARGER_TYPES,
    MAINTENANCE_TYPES, TRACKING_UNITS, VEHICLE_SPEC_TYPES,
)


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

class TestUserPassword:
    def test_set_and_check_correct_password(self, test_user):
        assert test_user.check_password('TestPass123!') is True

    def test_check_wrong_password(self, test_user):
        assert test_user.check_password('wrongpassword') is False

    def test_password_is_hashed(self, test_user):
        assert test_user.password_hash != 'TestPass123!'

    def test_set_password_updates_hash(self, test_user):
        test_user.set_password('NewPass456!')
        assert test_user.check_password('NewPass456!') is True
        assert test_user.check_password('TestPass123!') is False


class TestUserApiKey:
    def test_generate_api_key_format(self, test_user):
        key = test_user.generate_api_key()
        assert key.startswith('may_')
        assert len(key) > 10

    def test_api_key_stored_on_user(self, test_user):
        key = test_user.generate_api_key()
        assert test_user.api_key == key

    def test_api_key_created_at_set(self, test_user):
        test_user.generate_api_key()
        assert test_user.api_key_created_at is not None

    def test_get_by_api_key(self, app, test_user):
        key = test_user.generate_api_key()
        db.session.commit()
        found = User.get_by_api_key(key)
        assert found is not None
        assert found.id == test_user.id

    def test_get_by_api_key_none(self, app):
        assert User.get_by_api_key(None) is None

    def test_revoke_api_key(self, test_user):
        test_user.generate_api_key()
        test_user.revoke_api_key()
        assert test_user.api_key is None
        assert test_user.api_key_created_at is None


class TestUserResetToken:
    def test_generate_reset_token(self, test_user):
        token = test_user.generate_reset_token()
        assert token is not None
        assert len(token) > 20

    def test_reset_token_expiry_set(self, test_user):
        test_user.generate_reset_token()
        assert test_user.password_reset_expires is not None
        # Should expire about 1 hour from now
        diff = test_user.password_reset_expires - utcnow()
        assert timedelta(minutes=55) < diff < timedelta(minutes=65)

    def test_get_by_reset_token_valid(self, app, test_user):
        token = test_user.generate_reset_token()
        db.session.commit()
        found = User.get_by_reset_token(token)
        assert found is not None
        assert found.id == test_user.id

    def test_get_by_reset_token_none(self, app):
        assert User.get_by_reset_token(None) is None

    def test_get_by_reset_token_expired(self, app, test_user):
        test_user.generate_reset_token()
        # Move expiry to the past
        test_user.password_reset_expires = utcnow() - timedelta(hours=2)
        db.session.commit()
        found = User.get_by_reset_token(test_user.password_reset_token)
        assert found is None

    def test_clear_reset_token(self, test_user):
        test_user.generate_reset_token()
        test_user.clear_reset_token()
        assert test_user.password_reset_token is None
        assert test_user.password_reset_expires is None


# ---------------------------------------------------------------------------
# Vehicle model
# ---------------------------------------------------------------------------

class TestVehicleIsElectric:
    def test_electric_is_electric(self, app, test_user):
        v = Vehicle(owner_id=test_user.id, name='EV', vehicle_type='car', fuel_type='electric')
        assert v.is_electric() is True

    def test_plugin_hybrid_is_electric(self, app, test_user):
        v = Vehicle(owner_id=test_user.id, name='PHEV', vehicle_type='car', fuel_type='plugin_hybrid')
        assert v.is_electric() is True

    def test_hybrid_is_electric(self, app, test_user):
        v = Vehicle(owner_id=test_user.id, name='HEV', vehicle_type='car', fuel_type='hybrid')
        assert v.is_electric() is True

    def test_petrol_not_electric(self, sample_vehicle):
        assert sample_vehicle.is_electric() is False

    def test_diesel_not_electric(self, app, test_user):
        v = Vehicle(owner_id=test_user.id, name='Diesel', vehicle_type='car', fuel_type='diesel')
        assert v.is_electric() is False

    def test_lpg_not_electric(self, app, test_user):
        v = Vehicle(owner_id=test_user.id, name='LPG', vehicle_type='car', fuel_type='lpg')
        assert v.is_electric() is False


class TestVehicleOdometerUnit:
    def test_vehicle_unit_set_returns_vehicle_unit(self, app, test_user):
        v = Vehicle(
            owner_id=test_user.id,
            name='Test', vehicle_type='car',
            fuel_type='petrol', odometer_unit='mi'
        )
        db.session.add(v)
        db.session.commit()
        assert v.get_effective_odometer_unit() == 'mi'

    def test_vehicle_unit_none_falls_back_to_user(self, app, test_user):
        # test_user has distance_unit='mi' per fixture
        v = Vehicle(
            owner_id=test_user.id,
            name='Test', vehicle_type='car',
            fuel_type='petrol', odometer_unit=None
        )
        db.session.add(v)
        db.session.commit()
        assert v.get_effective_odometer_unit() == 'mi'

    def test_no_owner_falls_back_to_km(self, app):
        v = Vehicle(name='Test', vehicle_type='car', fuel_type='petrol')
        # Don't commit — no owner set
        assert v.get_effective_odometer_unit() == 'km'

    def test_vehicle_km_override(self, app, test_user):
        # test_user uses 'mi' but vehicle explicitly set to 'km'
        v = Vehicle(
            owner_id=test_user.id,
            name='Test', vehicle_type='car',
            fuel_type='petrol', odometer_unit='km'
        )
        db.session.add(v)
        db.session.commit()
        assert v.get_effective_odometer_unit() == 'km'

    def test_get_total_distance_converts_units(self, app, test_user):
        """#173 — dashboard requests a specific unit and must get a converted value."""
        v = Vehicle(
            owner_id=test_user.id,
            name='KmCar', vehicle_type='car',
            fuel_type='petrol', odometer_unit='km'
        )
        db.session.add(v)
        db.session.commit()
        from app.models import FuelLog
        db.session.add_all([
            FuelLog(vehicle_id=v.id, user_id=test_user.id,
                    date=date(2026, 1, 1), odometer=10000, volume=40, is_full_tank=True),
            FuelLog(vehicle_id=v.id, user_id=test_user.id,
                    date=date(2026, 1, 15), odometer=11000, volume=42, is_full_tank=True),
        ])
        db.session.commit()
        # 1000 km raw
        assert abs(v.get_total_distance() - 1000) < 0.01
        # Asked in km — same value
        assert abs(v.get_total_distance('km') - 1000) < 0.01
        # Asked in miles — converted
        assert abs(v.get_total_distance('mi') - 621.371) < 0.05


class TestLastOdometerSources:
    """#286 — an odometer recorded against a maintenance expense counts too."""

    def _fuel_log(self, test_user, vehicle, odometer, day=1):
        return FuelLog(vehicle_id=vehicle.id, user_id=test_user.id,
                       date=date(2026, 1, day), odometer=odometer,
                       volume=40, is_full_tank=True)

    def _expense(self, test_user, vehicle, odometer, day=1):
        return Expense(vehicle_id=vehicle.id, user_id=test_user.id,
                       date=date(2026, 1, day), category='maintenance',
                       description='Oil change', cost=80, odometer=odometer)

    def test_expense_odometer_becomes_last_odometer(self, app, test_user, sample_vehicle):
        db.session.add_all([
            self._fuel_log(test_user, sample_vehicle, 10000),
            self._expense(test_user, sample_vehicle, 12500, day=20),
        ])
        db.session.commit()
        assert sample_vehicle.get_last_odometer() == 12500

    def test_expense_without_odometer_is_ignored(self, app, test_user, sample_vehicle):
        db.session.add_all([
            self._fuel_log(test_user, sample_vehicle, 10000),
            self._expense(test_user, sample_vehicle, None, day=20),
        ])
        db.session.commit()
        assert sample_vehicle.get_last_odometer() == 10000

    def test_only_expenses_without_odometer_gives_zero(self, app, test_user, sample_vehicle):
        db.session.add(self._expense(test_user, sample_vehicle, None))
        db.session.commit()
        assert sample_vehicle.get_last_odometer() == 0

    def test_higher_fuel_log_still_wins(self, app, test_user, sample_vehicle):
        db.session.add_all([
            self._fuel_log(test_user, sample_vehicle, 13000, day=25),
            self._expense(test_user, sample_vehicle, 12500, day=20),
        ])
        db.session.commit()
        assert sample_vehicle.get_last_odometer() == 13000

    def test_tessie_vehicle_ignores_expenses(self, app, test_user, monkeypatch):
        from app.services.tessie import TessieService
        monkeypatch.setattr(TessieService, 'is_configured', staticmethod(lambda: True))
        v = Vehicle(owner_id=test_user.id, name='Tesla', vehicle_type='car',
                    fuel_type='electric', odometer_unit='km',
                    tessie_enabled=True, tessie_vin='5YJ3TEST',
                    tessie_last_odometer=10000)
        db.session.add(v)
        db.session.commit()
        db.session.add(self._expense(test_user, v, 99000, day=20))
        db.session.commit()
        assert v.get_last_odometer() == 10000


class TestTessieOdometerUnit:
    def _tessie_vehicle(self, test_user, monkeypatch, unit):
        from app.services.tessie import TessieService
        monkeypatch.setattr(TessieService, 'is_configured', staticmethod(lambda: True))
        v = Vehicle(
            owner_id=test_user.id,
            name='Tesla', vehicle_type='car', fuel_type='electric',
            odometer_unit=unit,
            tessie_enabled=True, tessie_vin='5YJ3TEST', tessie_last_odometer=10000,
        )
        db.session.add(v)
        db.session.commit()
        return v

    def test_default_unit_matches_vehicle_for_miles(self, app, test_user, monkeypatch):
        # #245 — Tessie reports km; a miles vehicle must get miles back by
        # default so the value is comparable with logged odometer readings.
        v = self._tessie_vehicle(test_user, monkeypatch, 'mi')
        assert v.get_last_odometer() == round(10000 * 0.621371)

    def test_default_unit_matches_vehicle_for_km(self, app, test_user, monkeypatch):
        v = self._tessie_vehicle(test_user, monkeypatch, 'km')
        assert v.get_last_odometer() == 10000

    def test_explicit_unit_still_wins(self, app, test_user, monkeypatch):
        v = self._tessie_vehicle(test_user, monkeypatch, 'mi')
        assert v.get_last_odometer(distance_unit='km') == 10000


class TestVehicleRelationships:
    def test_vehicle_has_owner(self, sample_vehicle, test_user):
        assert sample_vehicle.owner.id == test_user.id

    def test_vehicle_fuel_logs_empty_initially(self, sample_vehicle):
        assert sample_vehicle.fuel_logs.count() == 0

    def test_vehicle_expenses_empty_initially(self, sample_vehicle):
        assert sample_vehicle.expenses.count() == 0


# ---------------------------------------------------------------------------
# FuelLog model
# ---------------------------------------------------------------------------

class TestFuelLogConsumption:
    def test_get_consumption_single_log_returns_none(self, sample_fuel_log):
        # Only one log, no previous entry to compare against
        result = sample_fuel_log.get_consumption()
        assert result is None

    def test_get_consumption_with_previous_log(self, app, test_user, sample_vehicle):
        log1 = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 1), odometer=10000.0,
            volume=40.0, is_full_tank=True,
        )
        log2 = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 15), odometer=10500.0,
            volume=35.0, is_full_tank=True,
        )
        db.session.add_all([log1, log2])
        db.session.commit()

        # consumption = (35 / 500) * 100 = 7.0 L/100km
        consumption = log2.get_consumption()
        assert consumption is not None
        assert abs(consumption - 7.0) < 0.01

    def test_get_consumption_km_per_litre(self, app, test_user, sample_vehicle):
        """km/L unit added for #212: 500 km on 35 L = 14.29 km/L."""
        log1 = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 1), odometer=10000.0,
            volume=40.0, is_full_tank=True,
        )
        log2 = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 15), odometer=10500.0,
            volume=35.0, is_full_tank=True,
        )
        db.session.add_all([log1, log2])
        db.session.commit()

        consumption = log2.get_consumption('km/L', 'L')
        assert consumption is not None
        assert abs(consumption - 500.0 / 35.0) < 0.01
        avg = sample_vehicle.get_average_consumption('km/L', 'L')
        assert abs(avg - 500.0 / 35.0) < 0.01

    def test_get_consumption_not_full_tank_returns_none(self, app, test_user, sample_vehicle):
        log = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 1), odometer=10000.0,
            volume=20.0, is_full_tank=False,
        )
        db.session.add(log)
        db.session.commit()
        assert log.get_consumption() is None

    def test_get_consumption_no_volume_returns_none(self, app, test_user, sample_vehicle):
        log = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 1), odometer=10000.0,
            volume=None, is_full_tank=True,
        )
        db.session.add(log)
        db.session.commit()
        assert log.get_consumption() is None

    def test_fuel_log_to_dict(self, sample_fuel_log):
        d = sample_fuel_log.to_dict()
        assert d['odometer'] == 10000.0
        assert d['volume'] == 40.0
        assert d['total_cost'] == 60.0
        assert d['is_full_tank'] is True
        assert 'id' in d
        assert 'vehicle_id' in d


# ---------------------------------------------------------------------------
# Reminder model
# ---------------------------------------------------------------------------

class TestReminderOverdue:
    def _make_reminder(self, test_user, sample_vehicle, due_date, is_completed=False):
        r = Reminder(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            title='Test Reminder',
            reminder_type='mot',
            due_date=due_date,
            is_completed=is_completed,
        )
        db.session.add(r)
        db.session.commit()
        return r

    def test_overdue_past_date(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle, date.today() - timedelta(days=1))
        assert r.is_overdue() is True

    def test_not_overdue_future_date(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle, date.today() + timedelta(days=7))
        assert r.is_overdue() is False

    def test_not_overdue_today(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle, date.today())
        assert r.is_overdue() is False

    def test_completed_reminder_not_overdue(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle,
                                date.today() - timedelta(days=5), is_completed=True)
        assert r.is_overdue() is False


class TestReminderUpcoming:
    def _make_reminder(self, test_user, sample_vehicle, due_date, is_completed=False):
        r = Reminder(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            title='Test Reminder',
            reminder_type='mot',
            due_date=due_date,
            is_completed=is_completed,
        )
        db.session.add(r)
        db.session.commit()
        return r

    def test_upcoming_within_7_days(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle, date.today() + timedelta(days=5))
        assert r.is_upcoming(days=7) is True

    def test_not_upcoming_beyond_window(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle, date.today() + timedelta(days=30))
        assert r.is_upcoming(days=7) is False

    def test_upcoming_today(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle, date.today())
        assert r.is_upcoming(days=7) is True

    def test_completed_not_upcoming(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle,
                                date.today() + timedelta(days=3), is_completed=True)
        assert r.is_upcoming() is False

    def test_overdue_not_upcoming(self, app, test_user, sample_vehicle):
        r = self._make_reminder(test_user, sample_vehicle, date.today() - timedelta(days=2))
        assert r.is_upcoming() is False


# ---------------------------------------------------------------------------
# MaintenanceSchedule model
# ---------------------------------------------------------------------------

class TestMaintenanceSchedule:
    def _make_schedule(self, test_user, sample_vehicle, **kwargs):
        ms = MaintenanceSchedule(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            name='Oil Change',
            maintenance_type='oil_change',
            **kwargs,
        )
        db.session.add(ms)
        db.session.commit()
        return ms

    def test_is_due_soon_by_date(self, app, test_user, sample_vehicle):
        ms = self._make_schedule(
            test_user, sample_vehicle,
            next_due_date=date.today() + timedelta(days=7),
        )
        assert ms.is_due_soon(days=14) is True

    def test_not_due_soon_far_future(self, app, test_user, sample_vehicle):
        ms = self._make_schedule(
            test_user, sample_vehicle,
            next_due_date=date.today() + timedelta(days=60),
        )
        assert ms.is_due_soon(days=14) is False

    def test_is_due_soon_by_odometer(self, app, test_user, sample_vehicle):
        ms = self._make_schedule(
            test_user, sample_vehicle,
            next_due_odometer=10500.0,
        )
        # Current odometer is 10200, 300 away from due (distance threshold = 500)
        assert ms.is_due_soon(current_odometer=10200.0, distance=500) is True

    def test_not_due_soon_odometer_far(self, app, test_user, sample_vehicle):
        ms = self._make_schedule(
            test_user, sample_vehicle,
            next_due_odometer=15000.0,
        )
        assert ms.is_due_soon(current_odometer=10000.0, distance=500) is False

    def test_calculate_next_due_by_months(self, app, test_user, sample_vehicle):
        ms = self._make_schedule(
            test_user, sample_vehicle,
            last_performed_date=date(2024, 1, 1),
            interval_months=6,
        )
        ms.calculate_next_due()
        assert ms.next_due_date == date(2024, 7, 1)

    def test_calculate_next_due_by_km(self, app, test_user, sample_vehicle):
        ms = self._make_schedule(
            test_user, sample_vehicle,
            last_performed_odometer=10000.0,
            interval_km=5000,
        )
        ms.calculate_next_due()
        assert ms.next_due_odometer == 15000.0

    def _make_miles_vehicle(self, test_user):
        v = Vehicle(
            owner_id=test_user.id,
            name='Miles Car',
            vehicle_type='car',
            fuel_type='petrol',
            odometer_unit='mi',
        )
        db.session.add(v)
        db.session.commit()
        return v

    def test_calculate_next_due_miles_interval_miles_unit(self, app, test_user):
        """issue #230: miles-interval schedule for a miles-unit vehicle must
        add the interval as-is, not a km-converted value."""
        v = self._make_miles_vehicle(test_user)
        ms = self._make_schedule(
            test_user, v,
            last_performed_odometer=29711.0,
            interval_miles=5000,
        )
        ms.calculate_next_due()
        assert ms.next_due_odometer == 34711.0

    def test_calculate_next_due_km_interval_km_unit(self, app, test_user, sample_vehicle):
        """km-interval schedule for a km-unit vehicle stays correct."""
        ms = self._make_schedule(
            test_user, sample_vehicle,
            last_performed_odometer=29711.0,
            interval_km=5000,
        )
        ms.calculate_next_due()
        assert ms.next_due_odometer == 34711.0

    def test_calculate_next_due_km_interval_miles_unit(self, app, test_user):
        """Cross case: km interval on a miles-unit vehicle converts to miles."""
        v = self._make_miles_vehicle(test_user)
        ms = self._make_schedule(
            test_user, v,
            last_performed_odometer=10000.0,
            interval_km=8000,
        )
        ms.calculate_next_due()
        # 8000 km == 4970.968 mi added to a miles odometer
        assert ms.next_due_odometer == pytest.approx(10000 + 8000 * 0.621371, abs=0.01)

    def test_calculate_next_due_miles_interval_km_unit(self, app, test_user, sample_vehicle):
        """Cross case: miles interval on a km-unit vehicle converts to km."""
        ms = self._make_schedule(
            test_user, sample_vehicle,
            last_performed_odometer=10000.0,
            interval_miles=5000,
        )
        ms.calculate_next_due()
        # 5000 mi == 8046.72 km added to a km odometer
        assert ms.next_due_odometer == pytest.approx(10000 + 5000 * 1.609344, abs=0.01)


# ---------------------------------------------------------------------------
# RecurringExpense model
# ---------------------------------------------------------------------------

class TestRecurringExpense:
    def _make_recurring(self, test_user, sample_vehicle, frequency='monthly',
                        start_date=None, **kwargs):
        if start_date is None:
            start_date = date(2024, 1, 1)
        r = RecurringExpense(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            name='Insurance',
            category='insurance',
            amount=50.0,
            frequency=frequency,
            start_date=start_date,
            **kwargs,
        )
        db.session.add(r)
        db.session.commit()
        return r

    def test_calculate_next_due_monthly(self, app, test_user, sample_vehicle):
        r = self._make_recurring(test_user, sample_vehicle,
                                 frequency='monthly',
                                 start_date=date(2024, 1, 15))
        r.calculate_next_due()
        assert r.next_due == date(2024, 2, 15)

    def test_calculate_next_due_weekly(self, app, test_user, sample_vehicle):
        r = self._make_recurring(test_user, sample_vehicle,
                                 frequency='weekly',
                                 start_date=date(2024, 1, 1))
        r.calculate_next_due()
        assert r.next_due == date(2024, 1, 8)

    def test_calculate_next_due_quarterly(self, app, test_user, sample_vehicle):
        r = self._make_recurring(test_user, sample_vehicle,
                                 frequency='quarterly',
                                 start_date=date(2024, 1, 1))
        r.calculate_next_due()
        assert r.next_due == date(2024, 4, 1)

    def test_calculate_next_due_yearly(self, app, test_user, sample_vehicle):
        r = self._make_recurring(test_user, sample_vehicle,
                                 frequency='yearly',
                                 start_date=date(2024, 1, 1))
        r.calculate_next_due()
        assert r.next_due == date(2025, 1, 1)

    def test_is_due_when_past_next_due(self, app, test_user, sample_vehicle):
        r = self._make_recurring(test_user, sample_vehicle,
                                 next_due=date.today() - timedelta(days=1))
        assert r.is_due() is True

    def test_not_due_when_future(self, app, test_user, sample_vehicle):
        r = self._make_recurring(test_user, sample_vehicle,
                                 next_due=date.today() + timedelta(days=30))
        assert r.is_due() is False

    def test_inactive_not_due(self, app, test_user, sample_vehicle):
        r = self._make_recurring(test_user, sample_vehicle,
                                 next_due=date.today() - timedelta(days=1),
                                 is_active=False)
        assert r.is_due() is False

    def test_calculate_next_due_past_end_date_deactivates(self, app, test_user, sample_vehicle):
        r = self._make_recurring(test_user, sample_vehicle,
                                 frequency='monthly',
                                 start_date=date(2024, 1, 1),
                                 end_date=date(2024, 1, 31))
        # next_due would be 2024-02-01, which is past end_date
        r.calculate_next_due()
        assert r.is_active is False


# ---------------------------------------------------------------------------
# FuelStation model
# ---------------------------------------------------------------------------

class TestFuelStation:
    def test_create_station(self, app, test_user):
        station = FuelStation(
            user_id=test_user.id,
            name='Shell Garage',
            brand='Shell',
            city='London',
        )
        db.session.add(station)
        db.session.commit()
        assert station.id is not None
        assert station.is_favorite is False
        assert station.times_used == 0

    def test_toggle_favorite(self, app, test_user):
        station = FuelStation(user_id=test_user.id, name='BP Station')
        db.session.add(station)
        db.session.commit()

        station.is_favorite = True
        db.session.commit()
        assert station.is_favorite is True

        station.is_favorite = False
        db.session.commit()
        assert station.is_favorite is False

    def test_increment_usage(self, app, test_user):
        station = FuelStation(user_id=test_user.id, name='Esso')
        db.session.add(station)
        db.session.commit()

        station.increment_usage()
        assert station.times_used == 1
        assert station.last_used is not None

        station.increment_usage()
        assert station.times_used == 2


# ---------------------------------------------------------------------------
# FuelPriceHistory model
# ---------------------------------------------------------------------------

class TestFuelPriceHistory:
    def test_create_price_record(self, app, test_user):
        station = FuelStation(user_id=test_user.id, name='Shell')
        db.session.add(station)
        db.session.commit()

        price = FuelPriceHistory(
            station_id=station.id,
            user_id=test_user.id,
            date=date(2024, 1, 15),
            fuel_type='petrol',
            price_per_unit=1.50,
        )
        db.session.add(price)
        db.session.commit()

        assert price.id is not None
        assert price.price_per_unit == 1.50
        assert price.fuel_type == 'petrol'

    def test_price_history_relationship(self, app, test_user):
        station = FuelStation(user_id=test_user.id, name='BP')
        db.session.add(station)
        db.session.commit()

        price = FuelPriceHistory(
            station_id=station.id,
            user_id=test_user.id,
            date=date(2024, 1, 15),
            fuel_type='diesel',
            price_per_unit=1.65,
        )
        db.session.add(price)
        db.session.commit()

        assert station.price_history.count() == 1
        assert station.price_history.first().price_per_unit == 1.65


# ---------------------------------------------------------------------------
# Trip model
# ---------------------------------------------------------------------------

class TestTrip:
    def test_trip_distance_property(self, app, test_user, sample_vehicle):
        trip = Trip(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 1, 10),
            start_odometer=10000.0,
            end_odometer=10150.0,
            purpose='business',
        )
        db.session.add(trip)
        db.session.commit()
        assert trip.distance == 150.0

    def test_trip_to_dict(self, app, test_user, sample_vehicle):
        trip = Trip(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 1, 10),
            start_odometer=10000.0,
            end_odometer=10150.0,
            purpose='personal',
            start_location='Home',
            end_location='Office',
        )
        db.session.add(trip)
        db.session.commit()

        d = trip.to_dict()
        assert d['distance'] == 150.0
        assert d['purpose'] == 'personal'
        assert d['start_location'] == 'Home'
        assert d['end_location'] == 'Office'
        assert 'id' in d
        assert 'vehicle_id' in d

    def test_trip_relationship_to_vehicle(self, app, test_user, sample_vehicle):
        trip = Trip(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 1, 10),
            start_odometer=10000.0,
            end_odometer=10150.0,
            purpose='commute',
        )
        db.session.add(trip)
        db.session.commit()
        assert trip.vehicle.id == sample_vehicle.id


# ---------------------------------------------------------------------------
# ChargingSession model
# ---------------------------------------------------------------------------

class TestChargingSession:
    def test_create_charging_session(self, app, test_user, sample_vehicle):
        session = ChargingSession(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 1, 10),
            kwh_added=30.5,
            start_soc=20,
            end_soc=80,
            cost_per_kwh=0.28,
            total_cost=8.54,
            charger_type='home',
        )
        db.session.add(session)
        db.session.commit()
        assert session.id is not None
        assert session.kwh_added == 30.5
        assert session.start_soc == 20
        assert session.end_soc == 80

    def test_tessie_charge_id_unique(self, app, test_user, sample_vehicle):
        s1 = ChargingSession(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 1, 10),
            kwh_added=20.0,
            tessie_charge_id='tessie_abc123',
        )
        db.session.add(s1)
        db.session.commit()

        s2 = ChargingSession(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 1, 11),
            kwh_added=25.0,
            tessie_charge_id='tessie_abc123',  # duplicate
        )
        db.session.add(s2)
        with pytest.raises(Exception):
            db.session.commit()

    def test_charging_session_to_dict(self, app, test_user, sample_vehicle):
        session = ChargingSession(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 1, 10),
            kwh_added=30.5,
            charger_type='level2',
            location='Supercharger',
        )
        db.session.add(session)
        db.session.commit()

        d = session.to_dict()
        assert d['kwh_added'] == 30.5
        assert d['charger_type'] == 'level2'
        assert d['location'] == 'Supercharger'
        assert 'id' in d
        assert 'vehicle_id' in d

    def test_charging_session_null_tessie_id_allows_multiple(self, app, test_user, sample_vehicle):
        # NULL tessie_charge_id is not subject to uniqueness constraint
        s1 = ChargingSession(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 10), kwh_added=20.0, tessie_charge_id=None,
        )
        s2 = ChargingSession(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 11), kwh_added=25.0, tessie_charge_id=None,
        )
        db.session.add_all([s1, s2])
        db.session.commit()
        assert s1.id is not None
        assert s2.id is not None


# ---------------------------------------------------------------------------
# AppSettings model
# ---------------------------------------------------------------------------

class TestAppSettings:
    def test_get_nonexistent_key_returns_default(self, app):
        result = AppSettings.get('nonexistent_key', default='fallback')
        assert result == 'fallback'

    def test_get_nonexistent_key_returns_none_by_default(self, app):
        result = AppSettings.get('nonexistent_key')
        assert result is None

    def test_set_and_get(self, app):
        AppSettings.set('test_key', 'hello')
        result = AppSettings.get('test_key')
        assert result == 'hello'

    def test_set_overwrites_existing(self, app):
        AppSettings.set('my_setting', 'first')
        AppSettings.set('my_setting', 'second')
        assert AppSettings.get('my_setting') == 'second'

    def test_set_returns_setting_object(self, app):
        setting = AppSettings.set('ret_key', 'ret_val')
        assert setting.key == 'ret_key'
        assert setting.value == 'ret_val'

    def test_get_all_branding_returns_defaults(self, app):
        branding = AppSettings.get_all_branding()
        assert 'app_name' in branding
        assert branding['app_name'] == 'May'
        assert 'primary_color' in branding

    def test_get_all_branding_reflects_overrides(self, app):
        AppSettings.set('app_name', 'MyApp')
        branding = AppSettings.get_all_branding()
        assert branding['app_name'] == 'MyApp'


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_fuel_types_nonempty(self):
        assert len(FUEL_TYPES) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in FUEL_TYPES)

    def test_expense_categories_nonempty(self):
        assert len(EXPENSE_CATEGORIES) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in EXPENSE_CATEGORIES)

    def test_vehicle_types_nonempty(self):
        assert len(VEHICLE_TYPES) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in VEHICLE_TYPES)

    def test_odometer_units_nonempty(self):
        assert len(ODOMETER_UNITS) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in ODOMETER_UNITS)

    def test_reminder_types_nonempty(self):
        assert len(REMINDER_TYPES) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in REMINDER_TYPES)

    def test_recurrence_options_nonempty(self):
        assert len(RECURRENCE_OPTIONS) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in RECURRENCE_OPTIONS)

    def test_trip_purposes_nonempty(self):
        assert len(TRIP_PURPOSES) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in TRIP_PURPOSES)

    def test_charger_types_nonempty(self):
        assert len(CHARGER_TYPES) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in CHARGER_TYPES)

    def test_maintenance_types_nonempty(self):
        assert len(MAINTENANCE_TYPES) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in MAINTENANCE_TYPES)

    def test_tracking_units_nonempty(self):
        assert len(TRACKING_UNITS) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in TRACKING_UNITS)

    def test_vehicle_spec_types_nonempty(self):
        assert len(VEHICLE_SPEC_TYPES) > 0
        assert all(isinstance(item, tuple) and len(item) == 2 for item in VEHICLE_SPEC_TYPES)

    def test_fuel_types_contains_electric(self):
        keys = [k for k, _ in FUEL_TYPES]
        assert 'electric' in keys
        assert 'petrol' in keys
        assert 'diesel' in keys

    def test_odometer_units_contains_km_and_mi(self):
        keys = [k for k, _ in ODOMETER_UNITS]
        assert 'km' in keys
        assert 'mi' in keys
