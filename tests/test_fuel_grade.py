"""Petrol grade (E10 / E5) per fill-up (#268)."""
import importlib.util
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import db
from app.models import (
    FuelLog, FuelPriceHistory, FuelStation, Vehicle, clean_fuel_grade, fuel_type_label,
)


def _form(vehicle, **fields):
    data = {'vehicle_id': str(vehicle.id), 'date': '2026-11-01', 'odometer': '15000',
            'volume': '40', 'price_per_unit': '1.40', 'is_full_tank': 'on'}
    data.update(fields)
    return data


@pytest.fixture
def station(app, test_user):
    station = FuelStation(user_id=test_user.id, name='Local Shell', postcode='SW1A 1AA')
    db.session.add(station)
    db.session.commit()
    return station


class TestCleanFuelGrade:
    @pytest.mark.parametrize('grade,log_fuel,vehicle_fuel,expected', [
        ('e5', None, 'petrol', 'e5'),
        ('e10', None, 'hybrid', 'e10'),
        ('e5', 'petrol', 'lpg', 'e5'),
        ('e5', None, 'diesel', None),
        ('e5', 'lpg', 'petrol', None),
        ('super', None, 'petrol', None),
        ('', None, 'petrol', None),
        (None, None, 'petrol', None),
    ])
    def test_only_known_grades_on_petrol_are_kept(self, grade, log_fuel, vehicle_fuel, expected):
        assert clean_fuel_grade(grade, log_fuel, vehicle_fuel) == expected

    def test_premium_series_have_readable_labels(self, app):
        with app.test_request_context():
            assert str(fuel_type_label('petrol_premium')) == 'E5 (super unleaded)'
            assert str(fuel_type_label('diesel_premium')) == 'Premium diesel'


class TestFuelForm:
    def test_new_form_offers_grades_defaulting_to_e10(self, auth_client, sample_vehicle):
        body = auth_client.get('/fuel/new').get_data(as_text=True)
        assert 'id="fuel-grade-field"' in body
        assert '<option value="e10" selected>E10 (standard unleaded)</option>' in body
        assert '<option value="e5" >E5 (super unleaded)</option>' in body
        assert 'Not recorded' not in body.split('id="fuel-grade-field"')[1].split('</select>')[0]

    def test_e5_fill_up_is_stored_and_priced_as_premium(self, auth_client, sample_vehicle, station):
        resp = auth_client.post('/fuel/new', data=_form(sample_vehicle, fuel_grade='e5',
                                                        station_id=str(station.id)))
        assert resp.status_code == 302
        log = FuelLog.query.one()
        assert log.fuel_grade == 'e5'
        assert log.effective_fuel_type == 'petrol'
        assert FuelPriceHistory.query.one().fuel_type == 'petrol_premium'
        assert 'Petrol/Gasoline · E5' in auth_client.get('/fuel/').get_data(as_text=True)

    def test_e10_fill_up_stays_on_the_petrol_series(self, auth_client, sample_vehicle, station):
        auth_client.post('/fuel/new', data=_form(sample_vehicle, fuel_grade='e10',
                                                 station_id=str(station.id)))
        assert FuelLog.query.one().fuel_grade == 'e10'
        assert FuelPriceHistory.query.one().fuel_type == 'petrol'

    def test_grade_is_dropped_for_a_diesel_vehicle(self, auth_client, sample_vehicle):
        sample_vehicle.fuel_type = 'diesel'
        db.session.commit()
        auth_client.post('/fuel/new', data=_form(sample_vehicle, fuel_grade='e5'))
        assert FuelLog.query.one().fuel_grade is None

    def test_editing_moves_the_price_between_series(self, auth_client, sample_vehicle, station):
        auth_client.post('/fuel/new', data=_form(sample_vehicle, fuel_grade='e10',
                                                 station_id=str(station.id)))
        log = FuelLog.query.one()
        edit = f'/fuel/{log.id}/edit'
        page = auth_client.get(edit).get_data(as_text=True)
        assert '<option value="e10" selected>' in page
        resp = auth_client.post(edit, data=_form(sample_vehicle, fuel_grade='e5',
                                                 station_id=str(station.id)))
        assert resp.status_code == 302
        db.session.refresh(log)
        assert log.fuel_grade == 'e5'
        assert FuelPriceHistory.query.one().fuel_type == 'petrol_premium'

    def test_old_log_without_a_grade_is_not_silently_assigned_one(self, auth_client, sample_fuel_log):
        page = auth_client.get(f'/fuel/{sample_fuel_log.id}/edit').get_data(as_text=True)
        grade_select = page.split('id="fuel-grade-field"')[1].split('</select>')[0]
        assert '<option value="" selected>Not recorded</option>' in grade_select


class TestConsumptionIgnoresGrade:
    def test_mixing_grades_keeps_one_petrol_figure(self, app, sample_vehicle, test_user):
        for day, odometer, volume, grade in [(1, 10000, 40, 'e10'), (10, 10500, 30, 'e5'),
                                             (20, 11000, 32, 'e10')]:
            db.session.add(FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                                   date=date(2026, 10, day), odometer=odometer, volume=volume,
                                   is_full_tank=True, fuel_grade=grade))
        db.session.commit()
        assert sample_vehicle.get_propulsion_fuel_types() == ['petrol']
        assert len(sample_vehicle.get_average_consumption_by_fuel()) == 1
        # 62 L over 1000 km, the same as with no grades at all.
        assert sample_vehicle.get_average_consumption('L/100km') == pytest.approx(6.2)


class TestApi:
    def _create(self, client, headers, vehicle, **fields):
        body = {'date': '2026-11-01', 'odometer': 15000, 'volume': 40, 'price_per_unit': 1.4}
        body.update(fields)
        return client.post(f'/api/v1/vehicles/{vehicle.id}/fuel', json=body, headers=headers)

    def test_create_and_read_grade(self, client, api_headers, sample_vehicle):
        resp = self._create(client, api_headers, sample_vehicle, fuel_grade='e5')
        assert resp.status_code == 201
        assert resp.get_json()['fuel_grade'] == 'e5'

    def test_unknown_grade_is_rejected(self, client, api_headers, sample_vehicle):
        resp = self._create(client, api_headers, sample_vehicle, fuel_grade='super98')
        assert resp.status_code == 400
        assert FuelLog.query.count() == 0

    def test_update_grade_and_switch_fuel_drops_it(self, client, api_headers, sample_vehicle):
        sample_vehicle.secondary_fuel_type = 'lpg'
        db.session.commit()
        log_id = self._create(client, api_headers, sample_vehicle).get_json()['id']
        url = f'/api/v1/fuel/{log_id}'
        assert client.patch(url, json={'fuel_grade': 'e5'}, headers=api_headers).get_json()['fuel_grade'] == 'e5'
        assert client.patch(url, json={'fuel_type': 'lpg'}, headers=api_headers).get_json()['fuel_grade'] is None


def test_backup_round_trip_keeps_the_grade(auth_client, sample_vehicle, test_user, admin_user):
    from app.services.backup_restore import restore_backup
    auth_client.post('/fuel/new', data=_form(sample_vehicle, fuel_grade='e5'))
    exported = auth_client.get('/api/export/json').get_json()
    assert exported['vehicles'][0]['fuel_logs'][0]['fuel_grade'] == 'e5'
    restore_backup(exported, admin_user)
    restored = FuelLog.query.filter(FuelLog.user_id == admin_user.id).one()
    assert restored.fuel_grade == 'e5'


def test_migration_adds_and_removes_the_column(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/a7d4e2c8f913_add_fuel_grade.py'
    spec = importlib.util.spec_from_file_location('fuel_grade_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sa.create_engine('sqlite://').begin() as connection:
        connection.execute(sa.text('CREATE TABLE fuel_logs (id INTEGER PRIMARY KEY, volume FLOAT)'))
        connection.execute(sa.text('INSERT INTO fuel_logs VALUES (1, 40)'))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert connection.execute(sa.text('SELECT fuel_grade FROM fuel_logs')).scalar() is None
        migration.downgrade()
        columns = {c['name'] for c in sa.inspect(connection).get_columns('fuel_logs')}
        assert 'fuel_grade' not in columns
        assert connection.execute(sa.text('SELECT volume FROM fuel_logs')).scalar() == 40
