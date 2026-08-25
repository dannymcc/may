"""Tests for data export endpoints."""
import pytest
import json
import zipfile
import io
from app import db


class TestExportCsv:
    def test_export_csv_requires_auth(self, client):
        resp = client.get('/api/export/csv')
        assert resp.status_code in (302, 401)

    def test_export_csv_returns_zip(self, auth_client):
        resp = auth_client.get('/api/export/csv')
        assert resp.status_code == 200
        assert 'zip' in resp.content_type or resp.content_type == 'application/octet-stream'

    def test_export_csv_is_valid_zip(self, auth_client):
        resp = auth_client.get('/api/export/csv')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        assert zipfile.is_zipfile(buf)

    def test_export_csv_contains_vehicles_csv(self, auth_client):
        resp = auth_client.get('/api/export/csv')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert 'vehicles.csv' in names

    def test_export_csv_contains_fuel_logs(self, auth_client):
        resp = auth_client.get('/api/export/csv')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert any('fuel' in n.lower() for n in names)

    def test_export_csv_contains_expenses(self, auth_client):
        resp = auth_client.get('/api/export/csv')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert any('expense' in n.lower() for n in names)

    def test_export_csv_with_data(self, auth_client, sample_vehicle, sample_fuel_log, sample_expense):
        resp = auth_client.get('/api/export/csv')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            vehicles_csv = zf.read('vehicles.csv').decode('utf-8')
            assert 'Test Car' in vehicles_csv

    def test_export_csv_includes_sales_tax(self, auth_client, sample_vehicle, sample_fuel_log):
        """#225 — sales tax paid on fuel has to survive an export."""
        sample_fuel_log.sales_tax = 7.8
        db.session.commit()
        resp = auth_client.get('/api/export/csv')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            fuel_csv = zf.read('fuel_logs.csv').decode('utf-8')
        lines = fuel_csv.splitlines()
        assert 'sales_tax' in lines[0]
        assert '7.8' in lines[1]

    def test_export_csv_keeps_which_fuel_went_in(self, auth_client, sample_vehicle,
                                                 sample_fuel_log):
        """#221 — the fuel type and its attributed distance belong in the CSV
        too, or a dual-fuel history is lost on export."""
        sample_fuel_log.fuel_type = 'lpg'
        sample_fuel_log.fuel_distance = 320
        db.session.commit()

        resp = auth_client.get('/api/export/csv')
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            fuel_csv = zf.read('fuel_logs.csv').decode('utf-8')
        header, row = fuel_csv.splitlines()[0], fuel_csv.splitlines()[1]
        assert 'fuel_type' in header and 'fuel_distance' in header
        assert 'lpg' in row and '320' in row

    def test_export_csv_includes_odometer_unit(self, auth_client, sample_vehicle, sample_fuel_log, sample_expense):
        """#173 — odometer values must be self-describing about units."""
        resp = auth_client.get('/api/export/csv')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            vehicles_csv = zf.read('vehicles.csv').decode('utf-8')
            fuel_csv = zf.read('fuel_logs.csv').decode('utf-8')
            expenses_csv = zf.read('expenses.csv').decode('utf-8')
            assert 'odometer_unit' in vehicles_csv.splitlines()[0]
            assert 'odometer_unit' in fuel_csv.splitlines()[0]
            assert 'odometer_unit' in expenses_csv.splitlines()[0]


class TestExportJson:
    def test_export_json_requires_auth(self, client):
        resp = client.get('/api/export/json')
        assert resp.status_code in (302, 401)

    def test_export_json_returns_json(self, auth_client):
        resp = auth_client.get('/api/export/json')
        assert resp.status_code == 200
        # Should be JSON or downloadable JSON
        data = resp.get_json()
        assert data is not None

    def test_export_json_has_export_info(self, auth_client):
        resp = auth_client.get('/api/export/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'export_info' in data
        assert 'exported_at' in data['export_info']
        assert 'username' in data['export_info']

    def test_export_json_has_vehicles(self, auth_client):
        resp = auth_client.get('/api/export/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'vehicles' in data

    def test_export_json_has_user_preferences(self, auth_client):
        resp = auth_client.get('/api/export/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'user_preferences' in data

    def test_export_json_with_vehicle(self, auth_client, sample_vehicle):
        resp = auth_client.get('/api/export/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['vehicles']) == 1
        assert data['vehicles'][0]['name'] == 'Test Car'

    def test_export_json_keeps_which_fuel_went_in(self, auth_client, sample_vehicle,
                                                  sample_fuel_log):
        """#221 — without the fuel type and its attributed distance a dual-fuel
        history cannot be reconstructed from an export."""
        sample_fuel_log.fuel_type = 'lpg'
        sample_fuel_log.fuel_distance = 320
        db.session.commit()

        resp = auth_client.get('/api/export/json')
        log = resp.get_json()['vehicles'][0]['fuel_logs'][0]
        assert log['fuel_type'] == 'lpg'
        assert log['fuel_distance'] == 320

    def test_export_json_with_fuel_log(self, auth_client, sample_vehicle, sample_fuel_log):
        resp = auth_client.get('/api/export/json')
        assert resp.status_code == 200
        data = resp.get_json()
        vehicle_data = data['vehicles'][0]
        assert 'fuel_logs' in vehicle_data
        assert len(vehicle_data['fuel_logs']) == 1


class TestExportBackup:
    def test_export_backup_requires_auth(self, client):
        resp = client.get('/api/export/backup')
        assert resp.status_code in (302, 401)

    def test_export_backup_returns_zip(self, auth_client):
        resp = auth_client.get('/api/export/backup')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        assert zipfile.is_zipfile(buf)

    def test_export_backup_contains_data_json(self, auth_client):
        resp = auth_client.get('/api/export/backup')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert 'data.json' in names

    def test_export_backup_contains_manifest(self, auth_client):
        resp = auth_client.get('/api/export/backup')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert 'manifest.json' in names

    def test_export_backup_data_json_valid(self, auth_client):
        resp = auth_client.get('/api/export/backup')
        assert resp.status_code == 200
        buf = io.BytesIO(resp.data)
        with zipfile.ZipFile(buf) as zf:
            data = json.loads(zf.read('data.json').decode('utf-8'))
            assert 'export_info' in data
            assert data['export_info']['backup_type'] == 'full'
            assert 'vehicles' in data
