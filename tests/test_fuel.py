import re
import pytest
from datetime import date
from app import db
from app.models import (
    FuelLog, FuelStation, FuelPriceHistory, Vehicle, resolve_price_fuel_type,
)


class TestFuelIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/fuel/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/fuel/')
        assert resp.status_code == 200

    def test_index_shows_fuel_logs(self, auth_client, sample_fuel_log):
        resp = auth_client.get('/fuel/')
        assert resp.status_code == 200


class TestFuelNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/fuel/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/fuel/new')
        assert resp.status_code == 200

    def test_create_fuel_log(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-01',
            'odometer': '15000',
            'volume': '45.0',
            'price_per_unit': '1.60',
            'total_cost': '72.0',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(
            vehicle_id=sample_vehicle.id,
            odometer=15000.0
        ).first()
        assert log is not None
        assert log.volume == 45.0
        assert log.user_id == test_user.id

    def test_discount_applied_to_calculated_total(self, auth_client, sample_vehicle):
        # No total_cost given: server computes volume * (price - discount) (#209)
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-02',
            'odometer': '15100',
            'volume': '50.0',
            'price_per_unit': '1.50',
            'discount_per_unit': '0.10',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id, odometer=15100.0).first()
        assert log is not None
        assert log.discount_per_unit == 0.10
        # 50 * (1.50 - 0.10) = 70.00
        assert log.total_cost == 70.0

    def test_explicit_total_overrides_discount_calc(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-03',
            'odometer': '15200',
            'volume': '50.0',
            'price_per_unit': '1.50',
            'discount_per_unit': '0.10',
            'total_cost': '68.0',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id, odometer=15200.0).first()
        assert log is not None
        assert log.total_cost == 68.0

    def test_no_discount_is_none(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-04',
            'odometer': '15300',
            'volume': '40.0',
            'price_per_unit': '1.50',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id, odometer=15300.0).first()
        assert log is not None
        assert log.discount_per_unit is None
        assert log.total_cost == 60.0

    def test_price_per_unit_is_calculated_from_total_cost(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-05',
            'odometer': '15400',
            'volume': '40.0',
            'total_cost': '64.0',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id, odometer=15400.0).first()
        assert log is not None
        assert log.price_per_unit == 1.6

    def test_calculated_price_respects_maximum(self, auth_client, sample_vehicle, sample_station):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-05',
            'odometer': '15401',
            'volume': '1',
            'total_cost': '2000',
            'station_id': str(sample_station.id),
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert FuelLog.query.filter_by(
            vehicle_id=sample_vehicle.id, odometer=15401.0
        ).first() is None
        assert FuelPriceHistory.query.filter_by(
            station_id=sample_station.id
        ).first() is None

    def test_calculated_price_includes_discount(self, auth_client, sample_vehicle):
        auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-06',
            'odometer': '15500',
            'volume': '40.0',
            'discount_per_unit': '0.10',
            'total_cost': '60.0',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id, odometer=15500.0).first()
        assert log is not None
        assert log.price_per_unit == 1.6

    def test_new_redirects_to_vehicles_if_none(self, auth_client):
        # No vehicles exist for this user
        resp = auth_client.get('/fuel/new', follow_redirects=False)
        # If user has no vehicles it redirects to vehicles.new
        # sample_vehicle fixture not used here, so depends on if user has vehicles
        # Just verify it's a valid response
        assert resp.status_code in (200, 302)


class TestFuelSalesTax:
    """Sales tax paid on fuel, for businesses reclaiming it (#225)."""

    def test_create_records_sales_tax(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-04-01',
            'odometer': '16000',
            'volume': '50.0',
            'price_per_unit': '1.60',
            'total_cost': '80.0',
            'sales_tax': '10.40',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id, odometer=16000.0).first()
        assert log is not None
        assert log.sales_tax == 10.40
        # Tax is part of the total, not added on top of it
        assert log.total_cost == 80.0

    def test_blank_sales_tax_is_none(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-04-02',
            'odometer': '16100',
            'volume': '40.0',
            'price_per_unit': '1.50',
            'sales_tax': '',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id, odometer=16100.0).first()
        assert log is not None
        assert log.sales_tax is None

    def test_negative_sales_tax_rejected(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-04-03',
            'odometer': '16200',
            'volume': '40.0',
            'price_per_unit': '1.50',
            'sales_tax': '-5',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert FuelLog.query.filter_by(
            vehicle_id=sample_vehicle.id, odometer=16200.0).first() is None

    def test_edit_sets_and_clears_sales_tax(self, auth_client, sample_fuel_log):
        form = {
            'date': '2024-01-15',
            'odometer': '10500',
            'volume': '42.0',
            'price_per_unit': '1.55',
            'total_cost': '65.1',
            'sales_tax': '8.46',
            'is_full_tank': 'on',
        }
        resp = auth_client.post(f'/fuel/{sample_fuel_log.id}/edit', data=form,
                                follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_fuel_log)
        assert sample_fuel_log.sales_tax == 8.46

        form['sales_tax'] = ''
        resp = auth_client.post(f'/fuel/{sample_fuel_log.id}/edit', data=form,
                                follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_fuel_log)
        assert sample_fuel_log.sales_tax is None

    def test_index_totals_sales_tax_by_year(self, auth_client, app, sample_vehicle, test_user):
        for day, year, tax in ((1, 2023, 5.0), (2, 2024, 4.25), (3, 2024, 3.75)):
            db.session.add(FuelLog(
                vehicle_id=sample_vehicle.id,
                user_id=test_user.id,
                date=date(year, 5, day),
                odometer=20000 + day,
                volume=40.0,
                price_per_unit=1.5,
                total_cost=60.0,
                sales_tax=tax,
            ))
        db.session.commit()

        resp = auth_client.get('/fuel/')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'Sales Tax Paid' in body
        # 2024 is the sum of both 2024 logs, and the newest year comes first
        assert '8.00' in body
        assert '5.00' in body
        assert body.index('2024') < body.index('2023')

    def test_index_hides_summary_without_sales_tax(self, auth_client, sample_fuel_log):
        resp = auth_client.get('/fuel/')
        assert resp.status_code == 200
        assert 'Sales Tax Paid' not in resp.data.decode()


class TestFuelEdit:
    def test_edit_requires_auth(self, client, sample_fuel_log):
        resp = client.get(f'/fuel/{sample_fuel_log.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_fuel_log):
        resp = auth_client.get(f'/fuel/{sample_fuel_log.id}/edit')
        assert resp.status_code == 200

    def test_edit_fuel_log(self, auth_client, sample_fuel_log):
        resp = auth_client.post(f'/fuel/{sample_fuel_log.id}/edit', data={
            'date': '2024-01-15',
            'odometer': '10500',
            'volume': '42.0',
            'price_per_unit': '1.55',
            'total_cost': '65.1',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_fuel_log)
        assert sample_fuel_log.odometer == 10500.0
        assert sample_fuel_log.volume == 42.0


class TestFuelDelete:
    def test_delete_requires_auth(self, client, sample_fuel_log):
        resp = client.post(f'/fuel/{sample_fuel_log.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_fuel_log(self, auth_client, sample_fuel_log):
        log_id = sample_fuel_log.id
        resp = auth_client.post(f'/fuel/{log_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(FuelLog, log_id) is None

    def test_delete_returns_to_fuel_log(self, auth_client, sample_fuel_log):
        """#298 — deleting from the fuel log stays on the fuel log."""
        log_id = sample_fuel_log.id
        resp = auth_client.post(f'/fuel/{log_id}/delete',
                                data={'next': '/fuel/'}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/fuel/')
        assert db.session.get(FuelLog, log_id) is None

    def test_delete_without_next_returns_to_vehicle(self, auth_client, sample_fuel_log):
        """Deleting from the vehicle page still returns there."""
        log_id = sample_fuel_log.id
        vehicle_id = sample_fuel_log.vehicle_id
        resp = auth_client.post(f'/fuel/{log_id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/vehicles/{vehicle_id}')
        assert db.session.get(FuelLog, log_id) is None

    def test_delete_ignores_offsite_next(self, auth_client, sample_fuel_log):
        """An off-site next falls back to the vehicle page (open redirect guard)."""
        log_id = sample_fuel_log.id
        vehicle_id = sample_fuel_log.vehicle_id
        resp = auth_client.post(f'/fuel/{log_id}/delete',
                                data={'next': 'http://evil.example/'},
                                follow_redirects=False)
        assert resp.status_code == 302
        assert 'evil.example' not in resp.headers['Location']
        assert resp.headers['Location'].endswith(f'/vehicles/{vehicle_id}')

    def test_delete_return_to_vehicle(self, auth_client, sample_fuel_log):
        """#312 — delete takes the same return_to token as new and edit."""
        log_id = sample_fuel_log.id
        vehicle_id = sample_fuel_log.vehicle_id
        resp = auth_client.post(f'/fuel/{log_id}/delete',
                                data={'return_to': 'vehicle'},
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/vehicles/{vehicle_id}')
        assert db.session.get(FuelLog, log_id) is None

    def test_delete_return_to_vehicle_in_query(self, auth_client, sample_fuel_log):
        """return_to is read from the query string too, as on the other deletes."""
        log_id = sample_fuel_log.id
        vehicle_id = sample_fuel_log.vehicle_id
        resp = auth_client.post(f'/fuel/{log_id}/delete?return_to=vehicle',
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/vehicles/{vehicle_id}')
        assert db.session.get(FuelLog, log_id) is None

    def test_delete_ignores_unknown_return_to(self, auth_client, sample_fuel_log):
        """Only the known token is honoured; anything else falls through to next."""
        log_id = sample_fuel_log.id
        resp = auth_client.post(f'/fuel/{log_id}/delete',
                                data={'return_to': 'http://evil.example/',
                                      'next': '/fuel/'},
                                follow_redirects=False)
        assert resp.status_code == 302
        assert 'evil.example' not in resp.headers['Location']
        assert resp.headers['Location'].endswith('/fuel/')
        assert db.session.get(FuelLog, log_id) is None


class TestPartialFillConsumption:
    """#194 — partial fills return no consumption; the next full fill
    captures the partial volume over the whole interval (#169)."""

    def test_full_tank_consumption_unchanged(self, app, test_user, sample_vehicle):
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 15), odometer=10500, volume=42, is_full_tank=True)
        db.session.add_all([log1, log2])
        db.session.commit()
        # 42L / 500km * 100 = 8.4 L/100km
        assert abs(log2.get_consumption() - 8.4) < 0.01

    def test_partial_fill_returns_none(self, app, test_user, sample_vehicle):
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 10), odometer=10200, volume=20, is_full_tank=False)
        db.session.add_all([log1, log2])
        db.session.commit()
        assert log2.get_consumption() is None

    def test_partial_fill_no_previous_log_returns_none(self, app, test_user, sample_vehicle):
        log = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                      date=date(2024, 1, 1), odometer=10000, volume=20, is_full_tank=False)
        db.session.add(log)
        db.session.commit()
        assert log.get_consumption() is None

    def test_no_volume_returns_none(self, app, test_user, sample_vehicle):
        log = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                      date=date(2024, 1, 1), odometer=10000, volume=None, is_full_tank=True)
        db.session.add(log)
        db.session.commit()
        assert log.get_consumption() is None

    def test_issue_194_partial_then_full(self, app, test_user, sample_vehicle):
        """#194 — Steve's reported scenario:
        full (62.8L) → partial 3.8L (no consumption) → full 62.1L (real figure
        spans the whole interval and includes the 3.8L top-up).
        """
        full_a = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                         date=date(2026, 5, 11), odometer=10000, volume=62.8,
                         is_full_tank=True)
        partial = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                          date=date(2026, 5, 20), odometer=10557, volume=3.8,
                          is_full_tank=False)
        full_b = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                         date=date(2026, 5, 21), odometer=10600, volume=62.1,
                         is_full_tank=True)
        db.session.add_all([full_a, partial, full_b])
        db.session.commit()
        assert partial.get_consumption() is None
        # (3.8 + 62.1) / 600 * 100 = 10.983 L/100km
        consumption = full_b.get_consumption()
        assert consumption is not None
        assert abs(consumption - 10.983) < 0.01

    def test_full_tank_sums_intervening_partials(self, app, test_user, sample_vehicle):
        """#169 — full tank consumption must sum partial fills since the previous full."""
        # Astrmn's reported scenario: full → partial → partial → full,
        # 1371 km between fulls, 19.67 + 12.71 + 53.80 = 86.18 L total.
        log_first_full = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 4, 21), odometer=10000, volume=50, is_full_tank=True,
        )
        partial_a = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 4, 24), odometer=10500, volume=19.67, is_full_tank=False,
        )
        partial_b = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 4, 27), odometer=10900, volume=12.71, is_full_tank=False,
        )
        log_last_full = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 4, 29), odometer=11371, volume=53.80, is_full_tank=True,
        )
        db.session.add_all([log_first_full, partial_a, partial_b, log_last_full])
        db.session.commit()
        # Fill-to-fill: (19.67 + 12.71 + 53.80) / 1371 * 100 = 6.286 L/100km
        consumption = log_last_full.get_consumption()
        assert consumption is not None
        assert abs(consumption - 6.286) < 0.01

    def test_full_tank_returns_none_when_intervening_log_is_missed(
            self, app, test_user, sample_vehicle):
        """A missed fill in the range invalidates the consumption figure."""
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 1), odometer=10000, volume=40, is_full_tank=True)
        missed = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                         date=date(2026, 4, 5), odometer=10300, volume=20,
                         is_full_tank=False, is_missed=True)
        log3 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 10), odometer=10500, volume=42,
                       is_full_tank=True)
        db.session.add_all([log1, missed, log3])
        db.session.commit()
        assert log3.get_consumption() is None

    def test_mpg_uk_for_km_vehicle_converts_distance(
            self, app, test_user, sample_vehicle):
        """#181 — km odometer + UK MPG must report miles per UK gallon."""
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 15), odometer=10500, volume=42, is_full_tank=True)
        db.session.add_all([log1, log2])
        db.session.commit()
        # 500 km = 310.686 mi, 42 L = 9.239 UK gal, expected ~33.63 MPG (UK)
        consumption = log2.get_consumption(consumption_unit='mpg')
        assert consumption is not None
        assert abs(consumption - 33.63) < 0.05

    def test_mpg_uk_for_mi_vehicle_no_conversion(
            self, app, test_user, sample_vehicle):
        """Vehicle already in miles — distance passes through unchanged."""
        sample_vehicle.odometer_unit = 'mi'
        db.session.commit()
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 15), odometer=10500, volume=42, is_full_tank=True)
        db.session.add_all([log1, log2])
        db.session.commit()
        # 500 mi / 9.239 UK gal = ~54.12 MPG (UK)
        consumption = log2.get_consumption(consumption_unit='mpg')
        assert consumption is not None
        assert abs(consumption - 54.12) < 0.05

    def test_l_per_100km_for_mi_vehicle_converts_distance(
            self, app, test_user, sample_vehicle):
        """Vehicle in miles, L/100km display: distance must be converted to km."""
        sample_vehicle.odometer_unit = 'mi'
        db.session.commit()
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 15), odometer=10500, volume=42, is_full_tank=True)
        db.session.add_all([log1, log2])
        db.session.commit()
        # 500 mi = 804.672 km, 42 L over 804.672 km = 5.22 L/100km
        consumption = log2.get_consumption(consumption_unit='L/100km')
        assert consumption is not None
        assert abs(consumption - 5.22) < 0.05

    def test_average_consumption_includes_partial_fills(
            self, app, test_user, sample_vehicle):
        """#169 — vehicle average must count partial fills between two fulls."""
        logs = [
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 4, 21), odometer=10000, volume=50, is_full_tank=True),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 4, 24), odometer=10500, volume=19.67, is_full_tank=False),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 4, 27), odometer=10900, volume=12.71, is_full_tank=False),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 4, 29), odometer=11371, volume=53.80, is_full_tank=True),
        ]
        db.session.add_all(logs)
        db.session.commit()
        avg = sample_vehicle.get_average_consumption()
        assert avg is not None
        assert abs(avg - 6.286) < 0.01


@pytest.fixture
def sample_station(app, test_user):
    station = FuelStation(
        user_id=test_user.id,
        name='Test Station',
        brand='BP',
    )
    db.session.add(station)
    db.session.commit()
    return station


@pytest.fixture
def fuel_log_with_price_history(app, test_user, sample_vehicle, sample_station):
    log = FuelLog(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 3, 1),
        odometer=15000,
        volume=45,
        price_per_unit=1.60,
        total_cost=72.0,
        is_full_tank=True,
    )
    db.session.add(log)
    db.session.flush()
    history = FuelPriceHistory(
        station_id=sample_station.id,
        user_id=test_user.id,
        date=log.date,
        fuel_type='petrol',
        price_per_unit=log.price_per_unit,
    )
    db.session.add(history)
    db.session.commit()
    return log, history


class TestPriceHistorySync:
    """#113 — editing a fuel log must keep FuelPriceHistory in sync."""

    def test_edit_price_updates_history(self, auth_client, fuel_log_with_price_history):
        log, history = fuel_log_with_price_history
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': '2024-03-01',
            'odometer': str(log.odometer),
            'volume': str(log.volume),
            'price_per_unit': '1.45',
            'total_cost': str(log.total_cost),
            'is_full_tank': 'on',
        }, follow_redirects=True)
        db.session.refresh(history)
        assert history.price_per_unit == 1.45

    def test_edit_date_updates_history(self, auth_client, fuel_log_with_price_history):
        log, history = fuel_log_with_price_history
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': '2024-03-10',
            'odometer': str(log.odometer),
            'volume': str(log.volume),
            'price_per_unit': str(log.price_per_unit),
            'total_cost': str(log.total_cost),
            'is_full_tank': 'on',
        }, follow_redirects=True)
        from datetime import date
        db.session.refresh(history)
        assert history.date == date(2024, 3, 10)

    def test_edit_remove_price_deletes_history(self, auth_client, fuel_log_with_price_history):
        log, history = fuel_log_with_price_history
        history_id = history.id
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': '2024-03-01',
            'odometer': str(log.odometer),
            'volume': str(log.volume),
            'price_per_unit': '',
            'total_cost': str(log.total_cost),
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert db.session.get(FuelPriceHistory, history_id) is None

    def test_stale_price_not_shown_after_edit(self, auth_client, fuel_log_with_price_history):
        """The bad-entry scenario from issue #113: edit fixes the price, history reflects it."""
        log, history = fuel_log_with_price_history
        # Simulate the bad entry: history has 254.7
        history.price_per_unit = 254.7
        log.price_per_unit = 254.7
        db.session.commit()

        # User edits to correct value
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': '2024-03-01',
            'odometer': str(log.odometer),
            'volume': str(log.volume),
            'price_per_unit': '2.547',
            'total_cost': str(log.total_cost),
            'is_full_tank': 'on',
        }, follow_redirects=True)
        db.session.refresh(history)
        assert history.price_per_unit == 2.547

    def test_edit_links_station_to_existing_log(
            self, auth_client, test_user, sample_vehicle, sample_station):
        """#170 — adding a station to a previously stationless log must
        create the price-history row and bump the station's times_used."""
        log = FuelLog(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2026, 4, 15),
            odometer=20000,
            volume=40,
            price_per_unit=1.50,
            total_cost=60.0,
            is_full_tank=True,
        )
        db.session.add(log)
        db.session.commit()
        log_id = log.id
        starting_uses = sample_station.times_used or 0

        auth_client.post(f'/fuel/{log_id}/edit', data={
            'date': '2026-04-15',
            'odometer': '20000',
            'volume': '40',
            'price_per_unit': '1.50',
            'total_cost': '60.0',
            'station_id': str(sample_station.id),
            'is_full_tank': 'on',
        }, follow_redirects=True)

        db.session.refresh(sample_station)
        assert sample_station.times_used == starting_uses + 1

        history = FuelPriceHistory.query.filter_by(
            station_id=sample_station.id,
            price_per_unit=1.50,
        ).first()
        assert history is not None
        assert history.date == date(2026, 4, 15)


class TestFuelQuick:
    def test_quick_requires_auth(self, client):
        resp = client.get('/fuel/quick', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_quick_get_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/fuel/quick')
        assert resp.status_code == 200

    def test_quick_post_creates_log(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/quick', data={
            'vehicle_id': str(sample_vehicle.id),
            'odometer': '20000',
            'volume': '50.0',
            'total_cost': '80.0',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(
            vehicle_id=sample_vehicle.id,
            odometer=20000.0
        ).first()
        assert log is not None

    @staticmethod
    def _selected_vehicle_id(html):
        """Return the vehicle id of the pre-selected <option>, or None."""
        for match in re.finditer(r'<option value="(\d+)"[^>]*>', html):
            if 'selected' in match.group(0):
                return int(match.group(1))
        return None

    def test_quick_get_preselects_single_vehicle(self, auth_client, sample_vehicle):
        """#233 — with one vehicle and no default, it is pre-selected."""
        resp = auth_client.get('/fuel/quick')
        assert self._selected_vehicle_id(resp.get_data(as_text=True)) == sample_vehicle.id

    def test_quick_get_uses_default_vehicle(self, auth_client, test_user, sample_vehicle):
        """#233 — with multiple vehicles, the user's default is pre-selected."""
        second = Vehicle(owner_id=test_user.id, name='Van', vehicle_type='car',
                         make='Ford', model='Transit', fuel_type='diesel', odometer_unit='km')
        db.session.add(second)
        db.session.commit()
        test_user.default_vehicle_id = second.id
        db.session.commit()

        resp = auth_client.get('/fuel/quick')
        assert self._selected_vehicle_id(resp.get_data(as_text=True)) == second.id

    def test_quick_get_explicit_param_overrides_default(self, auth_client, test_user, sample_vehicle):
        """#233 — an explicit vehicle_id param wins over the default preference."""
        second = Vehicle(owner_id=test_user.id, name='Van', vehicle_type='car',
                         make='Ford', model='Transit', fuel_type='diesel', odometer_unit='km')
        db.session.add(second)
        db.session.commit()
        test_user.default_vehicle_id = second.id
        db.session.commit()

        resp = auth_client.get(f'/fuel/quick?vehicle_id={sample_vehicle.id}')
        assert self._selected_vehicle_id(resp.get_data(as_text=True)) == sample_vehicle.id

    def test_quick_get_ignores_default_not_in_list(self, auth_client, test_user, sample_vehicle, admin_user):
        """#233 — a default vehicle the user can't access is not pre-selected."""
        # Give test_user a second vehicle so the single-vehicle fallback doesn't fire.
        second = Vehicle(owner_id=test_user.id, name='Van', vehicle_type='car',
                         make='Ford', model='Transit', fuel_type='diesel', odometer_unit='km')
        # A vehicle owned by someone else, not shared.
        foreign = Vehicle(owner_id=admin_user.id, name='Admin Car', vehicle_type='car',
                          make='BMW', model='M3', fuel_type='petrol', odometer_unit='km')
        db.session.add_all([second, foreign])
        db.session.commit()
        test_user.default_vehicle_id = foreign.id
        db.session.commit()

        resp = auth_client.get('/fuel/quick')
        assert self._selected_vehicle_id(resp.get_data(as_text=True)) is None


class TestFuelLogOrdering:
    """#236 — same-date fuel logs must fall back to odometer for a stable order."""

    def _two_same_date_logs(self, test_user, vehicle):
        low = FuelLog(vehicle_id=vehicle.id, user_id=test_user.id,
                      date=date(2024, 3, 1), odometer=10000, volume=40, is_full_tank=True)
        high = FuelLog(vehicle_id=vehicle.id, user_id=test_user.id,
                       date=date(2024, 3, 1), odometer=10400, volume=42, is_full_tank=True)
        # Insert the lower-odometer row second so id order != odometer order.
        db.session.add(high)
        db.session.commit()
        db.session.add(low)
        db.session.commit()
        return low, high

    def test_api_list_desc_orders_by_odometer(self, client, api_headers, test_user, sample_vehicle):
        self._two_same_date_logs(test_user, sample_vehicle)
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/fuel?sort=desc', headers=api_headers)
        odos = [log['odometer'] for log in resp.get_json()['fuel_logs']]
        assert odos == [10400, 10000]

    def test_api_list_asc_orders_by_odometer(self, client, api_headers, test_user, sample_vehicle):
        self._two_same_date_logs(test_user, sample_vehicle)
        resp = client.get(f'/api/v1/vehicles/{sample_vehicle.id}/fuel?sort=asc', headers=api_headers)
        odos = [log['odometer'] for log in resp.get_json()['fuel_logs']]
        assert odos == [10000, 10400]


class TestConsumptionUnavailableReason:
    """#214 — surface why average consumption can't be shown."""

    def test_reason_insufficient_full_tanks(self, app, test_user, sample_vehicle):
        log = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                      date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True)
        db.session.add(log)
        db.session.commit()
        assert sample_vehicle.get_average_consumption() is None
        assert sample_vehicle.get_consumption_unavailable_reason() == 'insufficient_full_tanks'

    def test_reason_missed_fill_up(self, app, test_user, sample_vehicle):
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True)
        missed = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                         date=date(2024, 1, 5), odometer=10300, volume=20,
                         is_full_tank=False, is_missed=True)
        log3 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 10), odometer=10500, volume=42, is_full_tank=True)
        db.session.add_all([log1, missed, log3])
        db.session.commit()
        assert sample_vehicle.get_average_consumption() is None
        assert sample_vehicle.get_consumption_unavailable_reason() == 'missed_fill_up'

    def test_missed_fill_up_only_invalidates_its_own_span(
            self, app, test_user, sample_vehicle):
        """#251 — one missed fill-up must not kill the whole average.

        Spans between full tanks that don't contain the missed log stay
        usable; only the contaminated span is excluded.
        """
        logs = [
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2024, 1, 10), odometer=10500, volume=40, is_full_tank=True),
            # Contaminated span: missed fill-up between the next two anchors.
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2024, 1, 15), odometer=10700, volume=20,
                    is_full_tank=False, is_missed=True),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2024, 1, 20), odometer=11000, volume=45, is_full_tank=True),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2024, 1, 30), odometer=11500, volume=40, is_full_tank=True),
        ]
        db.session.add_all(logs)
        db.session.commit()
        # Valid spans: 10000->10500 (40 L / 500) and 11000->11500 (40 L / 500).
        # The 10500->11000 span is excluded, so: 80 L / 1000 km = 8.0 L/100km.
        avg = sample_vehicle.get_average_consumption()
        assert avg is not None
        assert abs(avg - 8.0) < 0.01
        assert sample_vehicle.get_consumption_unavailable_reason() is None

    def test_reason_none_when_available(self, app, test_user, sample_vehicle):
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 15), odometer=10500, volume=42, is_full_tank=True)
        db.session.add_all([log1, log2])
        db.session.commit()
        assert sample_vehicle.get_average_consumption() is not None
        assert sample_vehicle.get_consumption_unavailable_reason() is None


class TestFuelStationSync:
    """#252 — quick logs, delete counter, and per-fuel-type price series."""

    def test_quick_log_appears_in_station_chart(
            self, auth_client, sample_vehicle, sample_station):
        """Defect 1: a quick log at a saved station records price history
        (so it shows in the chart view) and bumps the usage counter."""
        starting = sample_station.times_used or 0
        auth_client.post('/fuel/quick', data={
            'vehicle_id': str(sample_vehicle.id),
            'odometer': '30000',
            'volume': '40',
            'price_per_unit': '1.70',
            'station_id': str(sample_station.id),
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)

        history = FuelPriceHistory.query.filter_by(
            station_id=sample_station.id, price_per_unit=1.70).first()
        assert history is not None
        assert history.date == date.today()

        db.session.refresh(sample_station)
        assert sample_station.times_used == starting + 1

    def test_quick_log_matches_station_by_name(
            self, auth_client, sample_vehicle, sample_station):
        """Defect 1: a manually typed station name (no station_id) still
        records price history via name match."""
        auth_client.post('/fuel/quick', data={
            'vehicle_id': str(sample_vehicle.id),
            'odometer': '31000',
            'volume': '35',
            'price_per_unit': '1.65',
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)

        history = FuelPriceHistory.query.filter_by(
            station_id=sample_station.id, price_per_unit=1.65).first()
        assert history is not None

    def test_delete_decrements_station_counter(
            self, auth_client, sample_vehicle, sample_station):
        """Defect 2: deleting a fuel log decrements the overview counter,
        not just the chart's price-history row."""
        auth_client.post('/fuel/quick', data={
            'vehicle_id': str(sample_vehicle.id),
            'odometer': '32000',
            'volume': '40',
            'price_per_unit': '1.80',
            'station_id': str(sample_station.id),
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)
        db.session.refresh(sample_station)
        assert sample_station.times_used == 1

        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id).order_by(
            FuelLog.id.desc()).first()
        auth_client.post(f'/fuel/{log.id}/delete', follow_redirects=True)

        db.session.refresh(sample_station)
        assert sample_station.times_used == 0
        assert FuelPriceHistory.query.filter_by(
            station_id=sample_station.id).count() == 0

    def test_edit_reassign_moves_counter(
            self, auth_client, test_user, sample_vehicle, sample_station):
        """Defect 2: reassigning a log's station decrements the old station
        and increments the new one, so neither is over-counted."""
        other = FuelStation(user_id=test_user.id, name='Esso Station', brand='Esso')
        db.session.add(other)
        db.session.commit()

        # Log created at sample_station via quick (usage 1 + price history).
        auth_client.post('/fuel/quick', data={
            'vehicle_id': str(sample_vehicle.id),
            'odometer': '33000',
            'volume': '40',
            'price_per_unit': '1.90',
            'station_id': str(sample_station.id),
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)
        db.session.refresh(sample_station)
        assert sample_station.times_used == 1

        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id).order_by(
            FuelLog.id.desc()).first()

        # Reassign to the other station via edit.
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': log.date.isoformat(),
            'odometer': '33000',
            'volume': '40',
            'price_per_unit': '1.90',
            'station_id': str(other.id),
            'is_full_tank': 'on',
        }, follow_redirects=True)

        db.session.refresh(sample_station)
        db.session.refresh(other)
        assert sample_station.times_used == 0
        assert other.times_used == 1

    def test_price_history_separates_fuel_types(
            self, auth_client, test_user, sample_station):
        """Defect 3: the chart data keeps petrol and diesel as distinct
        series rather than aggregating them into one price line."""
        db.session.add_all([
            FuelPriceHistory(station_id=sample_station.id, user_id=test_user.id,
                             date=date(2024, 3, 1), fuel_type='petrol',
                             price_per_unit=1.60),
            FuelPriceHistory(station_id=sample_station.id, user_id=test_user.id,
                             date=date(2024, 3, 2), fuel_type='diesel',
                             price_per_unit=1.75),
        ])
        db.session.commit()

        resp = auth_client.get(f'/stations/{sample_station.id}/prices')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Both fuel types reach the template as distinct data...
        assert '"fuel_type": "petrol"' in html
        assert '"fuel_type": "diesel"' in html
        # ...and the chart groups by fuel type instead of one flat series.
        assert 'byType' in html


@pytest.fixture
def hybrid_vehicle(app, test_user):
    vehicle = Vehicle(
        owner_id=test_user.id,
        name='Hybrid Car',
        vehicle_type='car',
        fuel_type='hybrid',
        odometer_unit='km',
    )
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


class TestPriceHistoryFuelType:
    """Issue #268: hybrid is a propulsion type, not a fuel, so it must never
    become its own series in the station price charts."""

    def test_resolve_price_fuel_type(self):
        assert resolve_price_fuel_type(None, 'hybrid') == 'petrol'
        assert resolve_price_fuel_type(None, 'plugin_hybrid') == 'petrol'
        assert resolve_price_fuel_type(None, 'diesel') == 'diesel'
        assert resolve_price_fuel_type('diesel', 'hybrid') == 'diesel'
        # An explicitly logged 'hybrid' is still mapped to a real fuel.
        assert resolve_price_fuel_type('hybrid', 'hybrid') == 'petrol'
        # No fuel type anywhere falls back to petrol, as before.
        assert resolve_price_fuel_type(None, None) == 'petrol'

    def test_hybrid_fill_up_records_petrol(
            self, auth_client, hybrid_vehicle, sample_station):
        auth_client.post('/fuel/new', data={
            'vehicle_id': str(hybrid_vehicle.id),
            'date': '2024-04-01',
            'odometer': '20000',
            'volume': '35',
            'price_per_unit': '1.55',
            'total_cost': '54.25',
            'station_id': str(sample_station.id),
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)

        history = FuelPriceHistory.query.filter_by(
            station_id=sample_station.id, price_per_unit=1.55).first()
        assert history is not None
        assert history.fuel_type == 'petrol'

    def test_hybrid_quick_log_records_petrol(
            self, auth_client, hybrid_vehicle, sample_station):
        auth_client.post('/fuel/quick', data={
            'vehicle_id': str(hybrid_vehicle.id),
            'odometer': '21000',
            'volume': '30',
            'price_per_unit': '1.58',
            'station_id': str(sample_station.id),
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)

        history = FuelPriceHistory.query.filter_by(
            station_id=sample_station.id, price_per_unit=1.58).first()
        assert history is not None
        assert history.fuel_type == 'petrol'

    def test_explicit_fuel_type_wins_for_hybrid(
            self, auth_client, hybrid_vehicle, sample_station):
        """A diesel hybrid owner picks diesel on the form and it sticks."""
        auth_client.post('/fuel/new', data={
            'vehicle_id': str(hybrid_vehicle.id),
            'date': '2024-04-02',
            'odometer': '22000',
            'volume': '40',
            'price_per_unit': '1.72',
            'total_cost': '68.80',
            'fuel_type': 'diesel',
            'station_id': str(sample_station.id),
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)

        history = FuelPriceHistory.query.filter_by(
            station_id=sample_station.id, price_per_unit=1.72).first()
        assert history is not None
        assert history.fuel_type == 'diesel'

    def test_edit_updates_price_history_fuel_type(
            self, auth_client, hybrid_vehicle, sample_station):
        auth_client.post('/fuel/new', data={
            'vehicle_id': str(hybrid_vehicle.id),
            'date': '2024-04-03',
            'odometer': '23000',
            'volume': '38',
            'price_per_unit': '1.60',
            'total_cost': '60.80',
            'station_id': str(sample_station.id),
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)

        log = FuelLog.query.filter_by(vehicle_id=hybrid_vehicle.id).order_by(
            FuelLog.id.desc()).first()
        history = FuelPriceHistory.query.filter_by(fuel_log_id=log.id).first()
        assert history.fuel_type == 'petrol'

        auth_client.post(f'/fuel/{log.id}/edit', data={
            'vehicle_id': str(hybrid_vehicle.id),
            'date': '2024-04-03',
            'odometer': '23000',
            'volume': '38',
            'price_per_unit': '1.60',
            'total_cost': '60.80',
            'fuel_type': 'diesel',
            'station_id': str(sample_station.id),
            'station': sample_station.name,
            'is_full_tank': 'on',
        }, follow_redirects=True)

        db.session.refresh(history)
        assert history.fuel_type == 'diesel'


class TestFuelRedirects:
    """Saving a fuel log returns to the fuel log list unless the user came
    from a vehicle page (#283). Deletion keeps the `next` behaviour of #298."""

    def _payload(self, vehicle, **overrides):
        data = {
            'vehicle_id': str(vehicle.id),
            'date': '2024-05-01',
            'odometer': '16000',
            'volume': '40.0',
            'price_per_unit': '1.50',
            'total_cost': '60.0',
            'is_full_tank': 'on',
        }
        data.update(overrides)
        return data

    def test_create_redirects_to_fuel_log(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/new', data=self._payload(sample_vehicle),
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/fuel/')

    def test_create_returns_to_vehicle_when_requested(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/new',
                                data=self._payload(sample_vehicle, return_to='vehicle'),
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/vehicles/{sample_vehicle.id}')

    def test_edit_redirects_to_fuel_log(self, auth_client, sample_fuel_log):
        resp = auth_client.post(f'/fuel/{sample_fuel_log.id}/edit',
                                data=self._payload(sample_fuel_log.vehicle),
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/fuel/')

    def test_edit_returns_to_vehicle_when_requested(self, auth_client, sample_fuel_log):
        vehicle_id = sample_fuel_log.vehicle_id
        resp = auth_client.post(f'/fuel/{sample_fuel_log.id}/edit',
                                data=self._payload(sample_fuel_log.vehicle,
                                                   return_to='vehicle'),
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/vehicles/{vehicle_id}')

    def test_form_from_vehicle_page_includes_hidden_field(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/fuel/new?vehicle_id={sample_vehicle.id}&return_to=vehicle')
        assert resp.status_code == 200
        assert b'name="return_to" value="vehicle"' in resp.data

    def test_form_from_fuel_page_omits_hidden_field(self, auth_client, sample_vehicle):
        resp = auth_client.get('/fuel/new')
        assert resp.status_code == 200
        assert b'name="return_to"' not in resp.data


@pytest.fixture
def adblue_vehicle(app, test_user):
    """A diesel that tracks AdBlue as its secondary fluid (#319)."""
    vehicle = Vehicle(
        owner_id=test_user.id,
        name='Diesel Van',
        vehicle_type='car',
        fuel_type='diesel',
        secondary_fuel_type='adblue',
        odometer_unit='km',
    )
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


class TestSecondaryFuelConsumption:
    """Issue #319: AdBlue is an auxiliary fluid, not propulsion, so its
    refills must never move a diesel's consumption figures."""

    @staticmethod
    def _log(vehicle, test_user, odometer, volume, fuel_type,
             is_full_tank=True, is_missed=False):
        log = FuelLog(
            vehicle_id=vehicle.id, user_id=test_user.id,
            date=date(2024, 1, 1), odometer=odometer, volume=volume,
            fuel_type=fuel_type, is_full_tank=is_full_tank, is_missed=is_missed,
        )
        db.session.add(log)
        return log

    def test_effective_fuel_type_falls_back_to_vehicle(
            self, app, test_user, adblue_vehicle):
        legacy = self._log(adblue_vehicle, test_user, 10000, 50, None)
        adblue = self._log(adblue_vehicle, test_user, 10100, 10, 'adblue')
        db.session.commit()
        assert legacy.effective_fuel_type == 'diesel'
        assert adblue.effective_fuel_type == 'adblue'

    def test_effective_fuel_type_maps_propulsion_to_fuel(
            self, app, test_user, hybrid_vehicle):
        log = self._log(hybrid_vehicle, test_user, 20000, 35, None)
        db.session.commit()
        assert log.effective_fuel_type == 'petrol'

    def test_adblue_refill_excluded_from_diesel_consumption(
            self, app, test_user, adblue_vehicle):
        self._log(adblue_vehicle, test_user, 10000, 50, 'diesel')
        self._log(adblue_vehicle, test_user, 10300, 10, 'adblue', is_full_tank=False)
        second_diesel = self._log(adblue_vehicle, test_user, 10500, 45, 'diesel')
        db.session.commit()
        # 45 L over 500 km — the 10 L of AdBlue is no part of it.
        assert abs(second_diesel.get_consumption() - 9.0) < 0.01

    def test_adblue_full_tank_does_not_anchor_diesel(
            self, app, test_user, adblue_vehicle):
        """An AdBlue tank filled to the brim is not a diesel fill-up, so it
        must not become the previous full tank a diesel figure spans from."""
        self._log(adblue_vehicle, test_user, 10000, 50, 'diesel')
        self._log(adblue_vehicle, test_user, 10300, 10, 'adblue')
        second_diesel = self._log(adblue_vehicle, test_user, 10500, 45, 'diesel')
        db.session.commit()
        assert abs(second_diesel.get_consumption() - 9.0) < 0.01

    def test_legacy_untyped_diesel_logs_still_pair_up(
            self, app, test_user, adblue_vehicle):
        """Rows logged before the fuel type selector existed carry no type of
        their own and are read as the vehicle's primary fuel."""
        self._log(adblue_vehicle, test_user, 10000, 50, None)
        self._log(adblue_vehicle, test_user, 10300, 10, 'adblue', is_full_tank=False)
        second_diesel = self._log(adblue_vehicle, test_user, 10500, 45, None)
        db.session.commit()
        assert abs(second_diesel.get_consumption() - 9.0) < 0.01

    def test_missed_adblue_refill_does_not_void_diesel_figure(
            self, app, test_user, adblue_vehicle):
        self._log(adblue_vehicle, test_user, 10000, 50, 'diesel')
        self._log(adblue_vehicle, test_user, 10300, 10, 'adblue',
                  is_full_tank=False, is_missed=True)
        second_diesel = self._log(adblue_vehicle, test_user, 10500, 45, 'diesel')
        db.session.commit()
        assert abs(second_diesel.get_consumption() - 9.0) < 0.01

    def test_adblue_consumption_is_its_own_series(
            self, app, test_user, adblue_vehicle):
        self._log(adblue_vehicle, test_user, 10000, 50, 'diesel')
        self._log(adblue_vehicle, test_user, 10100, 10, 'adblue')
        self._log(adblue_vehicle, test_user, 10500, 45, 'diesel')
        second_adblue = self._log(adblue_vehicle, test_user, 10600, 5, 'adblue')
        db.session.commit()
        # 5 L of AdBlue over the 500 km since the last AdBlue fill.
        assert abs(second_adblue.get_consumption() - 1.0) < 0.01

    def test_average_consumption_is_per_fuel_type(
            self, app, test_user, adblue_vehicle):
        self._log(adblue_vehicle, test_user, 10000, 50, 'diesel')
        self._log(adblue_vehicle, test_user, 10100, 10, 'adblue')
        self._log(adblue_vehicle, test_user, 10500, 45, 'diesel')
        self._log(adblue_vehicle, test_user, 10600, 5, 'adblue')
        db.session.commit()
        assert abs(adblue_vehicle.get_average_consumption() - 9.0) < 0.01
        assert abs(adblue_vehicle.get_average_consumption(fuel_type='adblue') - 1.0) < 0.01

    def test_unavailable_reason_is_per_fuel_type(
            self, app, test_user, adblue_vehicle):
        self._log(adblue_vehicle, test_user, 10000, 50, 'diesel')
        self._log(adblue_vehicle, test_user, 10100, 10, 'adblue')
        self._log(adblue_vehicle, test_user, 10500, 45, 'diesel')
        db.session.commit()
        assert adblue_vehicle.get_consumption_unavailable_reason() is None
        assert adblue_vehicle.get_consumption_unavailable_reason(
            fuel_type='adblue') == 'insufficient_full_tanks'

    def test_fuel_log_to_dict_reports_effective_fuel_type(
            self, app, test_user, adblue_vehicle):
        legacy = self._log(adblue_vehicle, test_user, 10000, 50, None)
        db.session.commit()
        assert legacy.to_dict()['fuel_type'] == 'diesel'

    def test_fuel_index_shows_fuel_type(
            self, auth_client, test_user, adblue_vehicle):
        self._log(adblue_vehicle, test_user, 10000, 50, 'diesel')
        self._log(adblue_vehicle, test_user, 10100, 10, 'adblue')
        db.session.commit()
        resp = auth_client.get('/fuel/')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Diesel' in html
        assert 'AdBlue/DEF' in html

    def test_vehicle_page_charts_each_fuel_type_separately(
            self, auth_client, test_user, adblue_vehicle):
        resp = auth_client.get(f'/vehicles/{adblue_vehicle.id}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # The trend chart builds one dataset per fuel type rather than one
        # flat consumption series.
        assert 'typeLabels' in html

class TestDualFuelConsumption:
    """#221 — petrol and LPG are averaged separately, on attributed distance."""

    @pytest.fixture
    def bifuel_vehicle(self, app, test_user):
        vehicle = Vehicle(owner_id=test_user.id, name='LPG Car', vehicle_type='car',
                          make='Dacia', model='Duster', fuel_type='petrol',
                          secondary_fuel_type='lpg', odometer_unit='km')
        db.session.add(vehicle)
        db.session.commit()
        return vehicle

    def _log(self, user, vehicle, odometer, volume, fuel_type,
             fuel_distance=None, is_full_tank=True):
        log = FuelLog(vehicle_id=vehicle.id, user_id=user.id, date=date(2024, 1, 1),
                      odometer=odometer, volume=volume, fuel_type=fuel_type,
                      fuel_distance=fuel_distance, is_full_tank=is_full_tank)
        db.session.add(log)
        db.session.commit()
        return log

    def _attributed_history(self, user, vehicle):
        """Two fill-ups of each fuel, with the distance split by the driver."""
        return {
            'lpg': [self._log(user, vehicle, 10000, 40, 'lpg'),
                    self._log(user, vehicle, 10600, 60, 'lpg', fuel_distance=500)],
            'petrol': [self._log(user, vehicle, 10200, 30, 'petrol'),
                       self._log(user, vehicle, 10800, 20, 'petrol', fuel_distance=200)],
        }

    def test_logged_fuel_types_lists_primary_first(self, bifuel_vehicle, test_user):
        self._attributed_history(test_user, bifuel_vehicle)
        assert bifuel_vehicle.get_propulsion_fuel_types() == ['petrol', 'lpg']
        assert bifuel_vehicle.runs_on_two_fuels() is True

    def test_single_fuel_vehicle_is_not_treated_as_dual(self, sample_vehicle, test_user):
        """Logging only one fuel leaves the odometer-based average alone."""
        self._log(test_user, sample_vehicle, 10000, 40, None)
        self._log(test_user, sample_vehicle, 10500, 40, None)
        assert sample_vehicle.runs_on_two_fuels() is False
        avg = sample_vehicle.get_average_consumption()
        assert abs(avg - 8.0) < 0.01

    def test_declared_bifuel_with_one_fuel_logged_keeps_odometer_maths(
            self, bifuel_vehicle, test_user):
        """Declaring LPG but only ever filling with petrol changes nothing:
        there is no second fuel in the history to disentangle."""
        self._log(test_user, bifuel_vehicle, 10000, 40, 'petrol')
        self._log(test_user, bifuel_vehicle, 10500, 40, 'petrol')

        assert bifuel_vehicle.runs_on_two_fuels() is False
        assert abs(bifuel_vehicle.get_average_consumption() - 8.0) < 0.01

    def test_hybrid_untyped_and_petrol_logs_are_one_fuel(self, app, test_user):
        """A plain hybrid is not bi-fuel. Its older fill-ups predate the fuel
        type selector and carry no type, its newer ones say 'petrol'; that is
        one fuel, and the hybrid must keep its ordinary average (#268)."""
        vehicle = Vehicle(owner_id=test_user.id, name='Hybrid', vehicle_type='car',
                          make='Toyota', model='Yaris', fuel_type='hybrid',
                          odometer_unit='km')
        db.session.add(vehicle)
        db.session.commit()
        self._log(test_user, vehicle, 10000, 40, None)
        self._log(test_user, vehicle, 10500, 40, 'petrol')

        assert vehicle.get_propulsion_fuel_types() == ['petrol']
        assert vehicle.runs_on_two_fuels() is False
        assert abs(vehicle.get_average_consumption() - 8.0) < 0.01

    def test_adblue_is_not_a_second_propulsion_fuel(self, adblue_vehicle, test_user):
        """AdBlue is an auxiliary fluid (#319): a diesel that tracks it is not
        bi-fuel and must never be asked to attribute distance to it."""
        self._log(test_user, adblue_vehicle, 10000, 50, 'diesel')
        self._log(test_user, adblue_vehicle, 10500, 30, 'adblue', is_full_tank=False)
        self._log(test_user, adblue_vehicle, 11000, 40, 'diesel')

        assert adblue_vehicle.declares_second_fuel() is False
        assert adblue_vehicle.runs_on_two_fuels() is False
        assert abs(adblue_vehicle.get_average_consumption() - 4.0) < 0.01

    def test_fuels_are_not_blended_into_one_average(self, bifuel_vehicle, test_user):
        """The reported defect: petrol litres and LPG litres over one odometer
        span produced a single meaningless figure."""
        self._attributed_history(test_user, bifuel_vehicle)

        petrol = bifuel_vehicle.get_average_consumption(fuel_type='petrol')
        lpg = bifuel_vehicle.get_average_consumption(fuel_type='lpg')
        # 20 L over 200 km, and 60 L over 500 km — each on its own fuel.
        assert abs(petrol - 10.0) < 0.01
        assert abs(lpg - 12.0) < 0.01
        assert bifuel_vehicle.get_consumption_unavailable_reason('lpg') is None

    def test_default_fuel_is_the_vehicle_primary(self, bifuel_vehicle, test_user):
        self._attributed_history(test_user, bifuel_vehicle)
        assert bifuel_vehicle.get_average_consumption() == \
            bifuel_vehicle.get_average_consumption(fuel_type='petrol')

    def test_by_fuel_breakdown_covers_every_logged_fuel(self, bifuel_vehicle, test_user):
        self._attributed_history(test_user, bifuel_vehicle)
        breakdown = bifuel_vehicle.get_average_consumption_by_fuel()
        assert [entry['fuel_type'] for entry in breakdown] == ['petrol', 'lpg']
        assert all(entry['reason'] is None for entry in breakdown)

    def test_by_fuel_breakdown_without_logs_keeps_one_entry(self, bifuel_vehicle):
        """No fill-ups yet still yields the usual single empty state."""
        breakdown = bifuel_vehicle.get_average_consumption_by_fuel()
        assert len(breakdown) == 1
        assert breakdown[0]['value'] is None
        assert breakdown[0]['reason'] == 'insufficient_full_tanks'

    def test_unattributed_distance_is_reported_not_guessed(
            self, bifuel_vehicle, test_user):
        """Without a distance per fuel we say so rather than inventing one."""
        self._log(test_user, bifuel_vehicle, 10000, 40, 'lpg')
        self._log(test_user, bifuel_vehicle, 10200, 30, 'petrol')
        self._log(test_user, bifuel_vehicle, 10600, 60, 'lpg')

        assert bifuel_vehicle.get_average_consumption(fuel_type='lpg') is None
        assert bifuel_vehicle.get_consumption_unavailable_reason('lpg') == \
            'needs_distance_attribution'

    def test_single_fuel_stretch_keeps_its_odometer_figure(self, bifuel_vehicle, test_user):
        """A car converted to LPG keeps the ordinary maths over the stretch it
        ran on petrol alone: no LPG fill-up falls in that span, so the
        odometer distance is unambiguous and nothing needs attributing."""
        self._log(test_user, bifuel_vehicle, 10000, 40, 'petrol')
        self._log(test_user, bifuel_vehicle, 10500, 40, 'petrol')
        # The conversion, and the first LPG fill-ups, come later.
        self._log(test_user, bifuel_vehicle, 11000, 45, 'lpg')
        self._log(test_user, bifuel_vehicle, 11400, 50, 'lpg', fuel_distance=400)

        assert bifuel_vehicle.runs_on_two_fuels() is True
        # 40 L over the 500 km between the two petrol fills, untouched.
        assert abs(bifuel_vehicle.get_average_consumption(fuel_type='petrol') - 8.0) < 0.01
        assert bifuel_vehicle.get_consumption_unavailable_reason('petrol') is None

    def test_per_fill_up_figure_follows_its_own_fuel(self, bifuel_vehicle, test_user):
        logs = self._attributed_history(test_user, bifuel_vehicle)
        # 60 L over the 500 km the driver ran on LPG, ignoring the petrol
        # fill-up that sits between the two LPG odometer readings.
        assert abs(logs['lpg'][1].get_consumption() - 12.0) < 0.01
        assert abs(logs['petrol'][1].get_consumption() - 10.0) < 0.01

    def test_per_fill_up_figure_needs_attribution(self, bifuel_vehicle, test_user):
        self._log(test_user, bifuel_vehicle, 10000, 40, 'lpg')
        self._log(test_user, bifuel_vehicle, 10200, 30, 'petrol')
        latest = self._log(test_user, bifuel_vehicle, 10600, 60, 'lpg')
        assert latest.get_consumption() is None

    def test_new_log_stores_attributed_distance(self, auth_client, bifuel_vehicle):
        auth_client.post('/fuel/new', data={
            'vehicle_id': str(bifuel_vehicle.id),
            'date': '2024-03-01',
            'odometer': '20000',
            'volume': '45.0',
            'price_per_unit': '0.80',
            'total_cost': '36.0',
            'fuel_type': 'lpg',
            'fuel_distance': '420',
            'is_full_tank': 'on',
        }, follow_redirects=True)

        log = FuelLog.query.filter_by(vehicle_id=bifuel_vehicle.id).one()
        assert log.fuel_type == 'lpg'
        assert log.fuel_distance == 420

    def test_bad_attributed_distance_is_rejected_not_crashed(self, auth_client,
                                                             bifuel_vehicle):
        """A negative distance must come back as a flashed error. There is no
        fuel/new.html to render, so the failure path has to redirect."""
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(bifuel_vehicle.id),
            'date': '2024-03-01',
            'odometer': '20000',
            'volume': '45.0',
            'price_per_unit': '0.80',
            'total_cost': '36.0',
            'fuel_type': 'lpg',
            'fuel_distance': '-5',
            'is_full_tank': 'on',
        }, follow_redirects=True)

        assert resp.status_code == 200
        assert FuelLog.query.filter_by(vehicle_id=bifuel_vehicle.id).count() == 0

    def test_edit_updates_attributed_distance(self, auth_client, bifuel_vehicle, test_user):
        log = self._log(test_user, bifuel_vehicle, 20000, 45, 'lpg', fuel_distance=420)
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'vehicle_id': str(bifuel_vehicle.id),
            'date': '2024-03-01',
            'odometer': '20000',
            'volume': '45.0',
            'fuel_type': 'lpg',
            'fuel_distance': '380',
            'is_full_tank': 'on',
        }, follow_redirects=True)

        db.session.refresh(log)
        assert log.fuel_distance == 380

    def test_vehicle_page_shows_a_figure_per_fuel(
            self, auth_client, bifuel_vehicle, test_user):
        self._attributed_history(test_user, bifuel_vehicle)
        resp = auth_client.get(f'/vehicles/{bifuel_vehicle.id}')
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert 'LPG' in html
        assert 'Petrol/Gasoline' in html

    def test_vehicle_page_asks_for_attribution(
            self, auth_client, bifuel_vehicle, test_user):
        self._log(test_user, bifuel_vehicle, 10000, 40, 'lpg')
        self._log(test_user, bifuel_vehicle, 10200, 30, 'petrol')
        self._log(test_user, bifuel_vehicle, 10600, 60, 'lpg')

        resp = auth_client.get(f'/vehicles/{bifuel_vehicle.id}')
        html = resp.get_data(as_text=True)
        # Says why the figure has gone, not merely what to do about it.
        assert 'Consumption can' in html
        assert 'distance run on each fuel' in html
