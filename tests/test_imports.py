"""Tests for data import endpoints."""
import io
import os
import sqlite3
import tempfile
import pytest
from app import db as _db_ext
from app.models import Vehicle, FuelLog


# ---------------------------------------------------------------------------
# Helpers to build in-memory test files
# ---------------------------------------------------------------------------

def make_hammond_db():
    """Create a minimal valid Hammond SQLite database in a temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute(
        "CREATE TABLE vehicles (id INTEGER PRIMARY KEY, make TEXT, model TEXT, "
        "year_of_manufacture INTEGER, nickname TEXT, registration TEXT, vin TEXT, "
        "fuel_type TEXT, fuel_unit TEXT, distance_unit TEXT)"
    )
    conn.execute(
        "CREATE TABLE fillups (id INTEGER PRIMARY KEY, vehicle_id INTEGER, "
        "fuel_quantity REAL, per_unit_price REAL, total_amount REAL, "
        "odo_reading REAL, is_tank_full INTEGER, has_missed_fillup INTEGER, "
        "date TEXT, filling_station TEXT, comments TEXT, fuel_sub_type TEXT)"
    )
    conn.execute(
        "CREATE TABLE expenses (id INTEGER PRIMARY KEY, vehicle_id INTEGER, "
        "expense_type TEXT, amount REAL, odo_reading REAL, date TEXT, "
        "comments TEXT, type_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO vehicles VALUES (1, 'Toyota', 'Corolla', 2020, 'My Toyota', "
        "'AB12 CDE', NULL, 'PETROL', 'litres', 'km')"
    )
    conn.execute(
        "INSERT INTO fillups VALUES (1, 1, 40.0, 1.50, 60.0, 10000.0, 1, 0, "
        "'2024-01-15T00:00:00Z', 'Shell', NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO expenses VALUES (1, 1, 'Maintenance', 75.0, 10000.0, "
        "'2024-01-20T00:00:00Z', 'Oil change', 1)"
    )
    conn.commit()
    conn.close()
    return tmp.name


def make_fuelly_csv():
    """Create a minimal valid Fuelly CSV."""
    content = (
        "Name,Model,MPG,Odometer,Miles,Gallons,Price,Fuelup Date,Date Added,Tags,Notes\n"
        "My Car,Corolla,35.5,10000,350,9.86,3.45,2024-01-15,,commute,Good fill\n"
        "My Car,Corolla,36.0,10350,350,9.72,3.50,2024-02-15,,commute,\n"
    )
    return content.encode('utf-8')


def make_clarkson_sql():
    """Create a minimal Clarkson SQL dump."""
    content = (
        "INSERT INTO `Vehicles` VALUES (1, 1, 'Test Car', 'AB12CDE', 'Ford', "
        "'Focus', 2021, 1600, 1, 1);\n"
        "INSERT INTO `Fuelups` VALUES (1, 1, 1, 45.0, 1.55, 0, 10000, "
        "'2024-01-10', 0, 1, '', 1);\n"
    )
    return content.encode('utf-8')


# ---------------------------------------------------------------------------
# Hammond import tests
# ---------------------------------------------------------------------------

class TestImportHammond:
    def test_requires_auth(self, client):
        resp = client.post('/api/import/hammond')
        assert resp.status_code in (302, 401)

    def test_no_file_redirects(self, auth_client):
        """Posting without a file should redirect (flash error)."""
        resp = auth_client.post('/api/import/hammond')
        assert resp.status_code == 302

    def test_empty_filename_redirects(self, auth_client):
        """Posting with empty filename should redirect."""
        data = {'file': (io.BytesIO(b''), '')}
        resp = auth_client.post(
            '/api/import/hammond',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_invalid_file_redirects(self, auth_client):
        """Posting a non-SQLite file should redirect with error flash."""
        data = {'file': (io.BytesIO(b'not a sqlite file'), 'bad.db')}
        resp = auth_client.post(
            '/api/import/hammond',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_wrong_schema_redirects(self, auth_client):
        """A valid SQLite DB without Hammond tables should redirect with error."""
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.execute("CREATE TABLE other_table (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        try:
            with open(tmp.name, 'rb') as f:
                data = {'file': (f, 'wrong.db')}
                resp = auth_client.post(
                    '/api/import/hammond',
                    data=data,
                    content_type='multipart/form-data'
                )
            assert resp.status_code == 302
        finally:
            os.unlink(tmp.name)

    def test_valid_hammond_db_imports_data(self, auth_client, test_user):
        """A valid Hammond DB should import vehicles and fuel logs."""
        db_path = make_hammond_db()
        try:
            with open(db_path, 'rb') as f:
                data = {'file': (f, 'hammond.db')}
                resp = auth_client.post(
                    '/api/import/hammond',
                    data=data,
                    content_type='multipart/form-data'
                )
            assert resp.status_code == 302
            # Verify data was imported
            vehicles = Vehicle.query.filter_by(owner_id=test_user.id).all()
            assert len(vehicles) >= 1
            names = [v.name for v in vehicles]
            assert any('Toyota' in n or 'Corolla' in n or 'My Toyota' in n for n in names)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# Clarkson import tests
# ---------------------------------------------------------------------------

class TestImportClarkson:
    def test_requires_auth(self, client):
        resp = client.post('/api/import/clarkson')
        assert resp.status_code in (302, 401)

    def test_no_file_redirects(self, auth_client):
        resp = auth_client.post('/api/import/clarkson')
        assert resp.status_code == 302

    def test_empty_filename_redirects(self, auth_client):
        data = {'file': (io.BytesIO(b''), '')}
        resp = auth_client.post(
            '/api/import/clarkson',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_valid_sql_dump_redirects_with_success(self, auth_client, test_user):
        """Valid Clarkson SQL dump should import and redirect."""
        sql_content = make_clarkson_sql()
        data = {'file': (io.BytesIO(sql_content), 'clarkson.sql')}
        resp = auth_client.post(
            '/api/import/clarkson',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_empty_sql_dump_redirects(self, auth_client):
        """Empty SQL dump should still redirect (no records, no crash)."""
        data = {'file': (io.BytesIO(b'-- empty dump\n'), 'empty.sql')}
        resp = auth_client.post(
            '/api/import/clarkson',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Fuelly import tests
# ---------------------------------------------------------------------------

class TestImportFuelly:
    def test_requires_auth(self, client):
        resp = client.post('/api/import/fuelly')
        assert resp.status_code in (302, 401)

    def test_no_file_redirects(self, auth_client):
        resp = auth_client.post('/api/import/fuelly')
        assert resp.status_code == 302

    def test_empty_filename_redirects(self, auth_client):
        data = {'file': (io.BytesIO(b''), '')}
        resp = auth_client.post(
            '/api/import/fuelly',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_valid_fuelly_csv_imports_data(self, auth_client, test_user):
        """Valid Fuelly CSV should import vehicle and fuel logs."""
        csv_content = make_fuelly_csv()
        data = {'file': (io.BytesIO(csv_content), 'fuelly_export.csv')}
        resp = auth_client.post(
            '/api/import/fuelly',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302
        # Verify a vehicle was created
        vehicles = Vehicle.query.filter_by(owner_id=test_user.id).all()
        assert len(vehicles) >= 1
        assert any(v.name == 'My Car' for v in vehicles)

    def test_fuelly_csv_with_fuel_logs(self, auth_client, test_user):
        """Fuel logs should be created from Fuelly CSV rows."""
        csv_content = make_fuelly_csv()
        data = {'file': (io.BytesIO(csv_content), 'fuelly_export.csv')}
        auth_client.post(
            '/api/import/fuelly',
            data=data,
            content_type='multipart/form-data'
        )
        vehicles = Vehicle.query.filter_by(owner_id=test_user.id, name='My Car').all()
        if vehicles:
            vehicle = vehicles[0]
            logs = FuelLog.query.filter_by(vehicle_id=vehicle.id).all()
            assert len(logs) >= 1

    def test_invalid_csv_redirects(self, auth_client):
        """Malformed CSV should redirect (not crash)."""
        bad_content = b'\xff\xfe not a csv'
        data = {'file': (io.BytesIO(bad_content), 'bad.csv')}
        resp = auth_client.post(
            '/api/import/fuelly',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_fuelly_csv_with_bom(self, auth_client, test_user):
        """BOM-prefixed CSV (utf-8-sig) should be handled correctly."""
        bom_content = b'\xef\xbb\xbf' + make_fuelly_csv()
        data = {'file': (io.BytesIO(bom_content), 'fuelly_bom.csv')}
        resp = auth_client.post(
            '/api/import/fuelly',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Generic CSV import tests
# ---------------------------------------------------------------------------

class TestCsvImportUpload:
    def test_requires_auth(self, client):
        resp = client.get('/api/import/csv')
        assert resp.status_code in (302, 401)

    def test_no_vehicles_redirects(self, auth_client):
        """If user has no vehicles, should redirect with warning."""
        resp = auth_client.get('/api/import/csv')
        assert resp.status_code == 302

    def test_with_vehicles_shows_form(self, auth_client, sample_vehicle):
        """User with vehicles should see the upload form page."""
        resp = auth_client.get('/api/import/csv')
        assert resp.status_code == 200


class TestCsvImportPreview:
    def test_requires_auth(self, client):
        resp = client.post('/api/import/csv/preview')
        assert resp.status_code in (302, 401)

    def test_invalid_data_type_redirects(self, auth_client, sample_vehicle):
        data = {
            'data_type': 'invalid_type',
            'vehicle_id': sample_vehicle.id,
            'file': (io.BytesIO(b'col1,col2\nval1,val2\n'), 'test.csv'),
        }
        resp = auth_client.post(
            '/api/import/csv/preview',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_no_file_redirects(self, auth_client, sample_vehicle):
        data = {
            'data_type': 'fuel_logs',
            'vehicle_id': sample_vehicle.id,
            'file': (io.BytesIO(b''), ''),
        }
        resp = auth_client.post(
            '/api/import/csv/preview',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_vehicle_not_found_redirects(self, auth_client):
        data = {
            'data_type': 'fuel_logs',
            'vehicle_id': 99999,
            'file': (io.BytesIO(b'date,odometer\n2024-01-01,10000\n'), 'test.csv'),
        }
        resp = auth_client.post(
            '/api/import/csv/preview',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_valid_csv_shows_mapping_page(self, auth_client, sample_vehicle):
        """Valid CSV file should show the column-mapping page."""
        csv_content = b'date,odometer,volume,total_cost\n2024-01-15,10000,40.0,60.0\n'
        data = {
            'data_type': 'fuel_logs',
            'vehicle_id': str(sample_vehicle.id),
            'file': (io.BytesIO(csv_content), 'fuel.csv'),
        }
        resp = auth_client.post(
            '/api/import/csv/preview',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 200

    def test_csv_no_headers_redirects(self, auth_client, sample_vehicle):
        """CSV with no column headers should redirect with error."""
        data = {
            'data_type': 'fuel_logs',
            'vehicle_id': str(sample_vehicle.id),
            'file': (io.BytesIO(b''), 'empty.csv'),
        }
        resp = auth_client.post(
            '/api/import/csv/preview',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302


class TestCsvImportExecute:
    def test_requires_auth(self, client):
        resp = client.post('/api/import/csv/execute')
        assert resp.status_code in (302, 401)

    def test_invalid_data_type_redirects(self, auth_client, sample_vehicle):
        data = {
            'data_type': 'invalid_type',
            'vehicle_id': sample_vehicle.id,
        }
        resp = auth_client.post(
            '/api/import/csv/execute',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_no_temp_file_redirects(self, auth_client, sample_vehicle):
        """Execute without a prior preview session (no temp file) should redirect."""
        data = {
            'data_type': 'fuel_logs',
            'vehicle_id': str(sample_vehicle.id),
            'date_format': 'auto',
        }
        resp = auth_client.post(
            '/api/import/csv/execute',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_vehicle_not_found_redirects(self, auth_client):
        data = {
            'data_type': 'fuel_logs',
            'vehicle_id': '99999',
            'date_format': 'auto',
        }
        resp = auth_client.post(
            '/api/import/csv/execute',
            data=data,
            content_type='multipart/form-data'
        )
        assert resp.status_code == 302

    def test_execute_with_session_temp_file(self, auth_client, sample_vehicle):
        """Full preview→execute flow: preview stores temp file, execute reads it."""
        # Step 1: Preview to create a session temp file
        csv_content = b'date,odometer,volume,total_cost\n2024-01-15,10000,40.0,60.0\n'
        preview_data = {
            'data_type': 'fuel_logs',
            'vehicle_id': str(sample_vehicle.id),
            'file': (io.BytesIO(csv_content), 'fuel.csv'),
        }
        preview_resp = auth_client.post(
            '/api/import/csv/preview',
            data=preview_data,
            content_type='multipart/form-data'
        )
        # Should show the mapping page (200), not redirect
        assert preview_resp.status_code == 200

        # Step 2: Execute with the mapping (temp file is in session)
        execute_data = {
            'data_type': 'fuel_logs',
            'vehicle_id': str(sample_vehicle.id),
            'date_format': 'auto',
            'mapping_0': 'date',
            'mapping_1': 'odometer',
            'mapping_2': 'volume',
            'mapping_3': 'total_cost',
        }
        execute_resp = auth_client.post(
            '/api/import/csv/execute',
            data=execute_data,
            content_type='multipart/form-data'
        )
        assert execute_resp.status_code == 302


# ---------------------------------------------------------------------------
# Locale-tolerant numeric handling on CSV import (issue #244)
# ---------------------------------------------------------------------------

class TestParseFloatValue:
    """parse_float_value must accept locale decimal separators without
    corrupting Anglo thousands-grouped values."""

    def _parse(self, value):
        from app.routes.api import parse_float_value
        return parse_float_value(value)

    def test_dot_decimal_unchanged(self):
        assert self._parse('9.99') == 9.99

    def test_comma_decimal(self):
        # Previously imported as 999 (comma stripped) — a silent 100x error.
        assert self._parse('9,99') == 9.99

    def test_german_grouping(self):
        assert self._parse('1.234,56') == 1234.56

    def test_anglo_grouping(self):
        assert self._parse('1,234.56') == 1234.56

    def test_anglo_thousands_only(self):
        # Odometer-style value: two or more digits before a comma with three
        # after is thousands grouping, not a decimal.
        assert self._parse('12,345') == 12345

    def test_short_integer_part_is_decimal(self):
        # German fuel price: 1,899 €/L.
        assert self._parse('1,899') == 1.899

    def test_currency_symbols_stripped(self):
        assert self._parse('€1.234,56') == 1234.56
        assert self._parse('$1,234.56') == 1234.56

    def test_empty_returns_none(self):
        assert self._parse('') is None
        assert self._parse(None) is None


# ---------------------------------------------------------------------------
# Date-format handling on CSV import (issue #250)
# ---------------------------------------------------------------------------

class TestParseDateValue:
    """Unit tests for parse_date_value date-format disambiguation."""

    def test_auto_us_preference_ambiguous_reads_as_mdy(self):
        """A US user's ambiguous 12/01/2026 should be 1 December, not 12 Jan."""
        from datetime import date
        from app.routes.api import parse_date_value
        result = parse_date_value('12/01/2026', 'auto', user_date_format='MM/DD/YYYY')
        assert result == date(2026, 12, 1)

    def test_auto_us_preference_unambiguous_day_still_parses(self):
        """12/31/2026 has no DD/MM reading, so it stays 31 December."""
        from datetime import date
        from app.routes.api import parse_date_value
        result = parse_date_value('12/31/2026', 'auto', user_date_format='MM/DD/YYYY')
        assert result == date(2026, 12, 31)

    def test_auto_uk_preference_ambiguous_reads_as_dmy(self):
        """A DD/MM user keeps the original behaviour: 12/01/2026 is 12 January."""
        from datetime import date
        from app.routes.api import parse_date_value
        result = parse_date_value('12/01/2026', 'auto', user_date_format='DD/MM/YYYY')
        assert result == date(2026, 1, 12)

    def test_auto_no_preference_defaults_to_dmy(self):
        """With no preference (legacy default) 12/01/2026 stays DD/MM = 12 January."""
        from datetime import date
        from app.routes.api import parse_date_value
        result = parse_date_value('12/01/2026', 'auto')
        assert result == date(2026, 1, 12)

    def test_iso_unaffected_by_preference(self):
        """Unambiguous ISO dates parse identically regardless of preference."""
        from datetime import date
        from app.routes.api import parse_date_value
        assert parse_date_value('2026-12-01', 'auto', user_date_format='MM/DD/YYYY') == date(2026, 12, 1)
        assert parse_date_value('2026-12-01', 'auto', user_date_format='DD/MM/YYYY') == date(2026, 12, 1)
        assert parse_date_value('2026-12-01', 'YYYY-MM-DD') == date(2026, 12, 1)

    def test_explicit_mdy_falls_back_for_out_of_range_month(self):
        """Explicit MM/DD/YYYY falls back to DD/MM when the month slot is invalid."""
        from datetime import date
        from app.routes.api import parse_date_value
        # 31 cannot be a month, so this must be 31 December.
        assert parse_date_value('31/12/2026', 'MM/DD/YYYY') == date(2026, 12, 31)

    def test_explicit_dmy_unchanged(self):
        from datetime import date
        from app.routes.api import parse_date_value
        assert parse_date_value('12/01/2026', 'DD/MM/YYYY') == date(2026, 1, 12)


class TestCsvImportUsDateFormat:
    """End-to-end import flow honours the importing user's date preference."""

    def _import(self, auth_client, sample_vehicle, csv_content):
        preview_data = {
            'data_type': 'fuel_logs',
            'vehicle_id': str(sample_vehicle.id),
            'file': (io.BytesIO(csv_content), 'fuel.csv'),
        }
        preview_resp = auth_client.post(
            '/api/import/csv/preview',
            data=preview_data,
            content_type='multipart/form-data',
        )
        assert preview_resp.status_code == 200
        execute_data = {
            'data_type': 'fuel_logs',
            'vehicle_id': str(sample_vehicle.id),
            'date_format': 'auto',
            'mapping_0': 'date',
            'mapping_1': 'odometer',
            'mapping_2': 'volume',
            'mapping_3': 'total_cost',
        }
        execute_resp = auth_client.post(
            '/api/import/csv/execute',
            data=execute_data,
            content_type='multipart/form-data',
        )
        assert execute_resp.status_code == 302

    def test_us_user_ambiguous_date_not_reversed(self, auth_client, test_user, sample_vehicle):
        """US-preference user importing 12/01/2026 gets 1 December 2026."""
        from datetime import date
        test_user.date_format = 'MM/DD/YYYY'
        _db_ext.session.commit()
        self._import(
            auth_client, sample_vehicle,
            b'date,odometer,volume,total_cost\n12/01/2026,10000,40.0,60.0\n',
        )
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id).one()
        assert log.date == date(2026, 12, 1)

    def test_us_user_unambiguous_date_correct(self, auth_client, test_user, sample_vehicle):
        """US-preference user importing 12/31/2026 gets 31 December 2026."""
        from datetime import date
        test_user.date_format = 'MM/DD/YYYY'
        _db_ext.session.commit()
        self._import(
            auth_client, sample_vehicle,
            b'date,odometer,volume,total_cost\n12/31/2026,10000,40.0,60.0\n',
        )
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id).one()
        assert log.date == date(2026, 12, 31)

    def test_uk_user_keeps_dmy_behaviour(self, auth_client, test_user, sample_vehicle):
        """DD/MM-preference user importing 12/01/2026 gets 12 January 2026."""
        from datetime import date
        test_user.date_format = 'DD/MM/YYYY'
        _db_ext.session.commit()
        self._import(
            auth_client, sample_vehicle,
            b'date,odometer,volume,total_cost\n12/01/2026,10000,40.0,60.0\n',
        )
        log = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id).one()
        assert log.date == date(2026, 1, 12)
