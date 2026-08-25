"""Tests for restoring a full May backup (issue #265)."""
import io
import json
import os
import zipfile

from app import db
from app.services.backup_restore import read_backup, restore_backup
from app.models import (
    Vehicle, FuelLog, Expense, Trip, ChargingSession, FuelStation,
    FuelPriceHistory, Document, VehiclePart, Reminder
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_backup_data():
    """A JSON backup in the shape produced by /api/export/json."""
    return {
        'export_info': {
            'exported_at': '2024-06-01T12:00:00',
            'username': 'olduser',
            'app_version': '0.9.0',
        },
        'user_preferences': {'currency': 'GBP'},
        'vehicles': [{
            'id': 7,
            'name': 'Old Car',
            'vehicle_type': 'car',
            'make': 'Honda',
            'model': 'Civic',
            'year': 2019,
            'registration': 'XY19 ZAB',
            'vin': 'VIN123456',
            'fuel_type': 'petrol',
            'tank_capacity': 47.0,
            'is_active': True,
            'notes': 'From the old instance',
            'image_filename': None,
            'mot_expiry': '2025-03-01',
            'created_at': '2023-01-01T09:00:00',
            'specifications': [
                {'id': 1, 'spec_type': 'tyre', 'label': 'Front tyres', 'value': '205/55 R16'},
            ],
            'fuel_logs': [
                {'id': 1, 'date': '2024-01-15', 'odometer': 10000.0, 'volume': 40.0,
                 'price_per_unit': 1.5, 'total_cost': 60.0, 'sales_tax': 7.8,
                 'is_full_tank': True,
                 'is_missed': False, 'station': 'Shell', 'notes': None,
                 'created_at': '2024-01-15T18:00:00'},
                {'id': 2, 'date': '2024-02-15', 'odometer': 10500.0, 'volume': 42.0,
                 'price_per_unit': 1.6, 'total_cost': 67.2,
                 'fuel_type': 'lpg', 'fuel_distance': 320.0, 'is_full_tank': True,
                 'is_missed': False, 'station': 'BP', 'notes': None,
                 'created_at': '2024-02-15T18:00:00'},
            ],
            'expenses': [
                {'id': 1, 'date': '2024-01-20', 'category': 'maintenance',
                 'description': 'Oil change', 'cost': 75.0, 'odometer': 10100.0,
                 'vendor': 'Local garage', 'notes': None,
                 'created_at': '2024-01-20T10:00:00'},
            ],
            'reminders': [
                {'id': 1, 'title': 'MOT', 'description': None, 'reminder_type': 'mot',
                 'due_date': '2025-03-01', 'recurrence': 'yearly',
                 'notify_days_before': 30, 'is_completed': False},
            ],
            'maintenance_schedules': [],
            'recurring_expenses': [],
            'documents': [],
            'trips': [
                {'id': 1, 'date': '2024-01-25', 'start_odometer': 10000.0,
                 'end_odometer': 10050.0, 'distance': 50.0, 'purpose': 'business',
                 'description': 'Client visit', 'notes': None},
            ],
            'charging_sessions': [
                {'id': 1, 'date': '2024-01-30', 'start_time': '08:00:00',
                 'end_time': '09:00:00', 'odometer': 10100.0, 'kwh_added': 40.0,
                 'cost_per_kwh': 0.3, 'total_cost': 12.0, 'charger_type': 'home'},
            ],
            'parts': [
                {'id': 1, 'name': 'Oil filter', 'part_type': 'filter',
                 'part_number': 'OF-123', 'quantity': 1.0},
            ],
        }],
        'fuel_stations': [{
            'id': 3, 'name': 'Shell Anytown', 'brand': 'Shell',
            'address': '1 High Street', 'city': 'Anytown', 'postcode': 'AN1 1AN',
            'is_favorite': True, 'times_used': 4,
        }],
        'fuel_price_history': [{
            'id': 1, 'station_id': 3, 'station_name': 'Shell Anytown',
            'date': '2024-01-15', 'fuel_type': 'petrol', 'price_per_unit': 1.5,
        }],
    }


def backup_json_bytes(data=None):
    return json.dumps(data or make_backup_data()).encode('utf-8')


def make_full_backup_zip(data=None, files=None):
    """Build a full backup ZIP in the shape produced by /api/export/backup."""
    data = data or make_backup_data()
    files = files or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('data.json', json.dumps(data))
        zf.writestr('manifest.json', json.dumps({'files': []}))
        for name, content in files.items():
            zf.writestr(f'uploads/{name}', content)
    buf.seek(0)
    return buf.read()


def upload(client, payload, filename='may_backup.json', path='/api/import/backup/preview'):
    return client.post(
        path,
        data={'file': (io.BytesIO(payload), filename)},
        content_type='multipart/form-data',
    )


def restore(client, payload, filename='may_backup.json'):
    """Upload a backup, then confirm the restore."""
    resp = upload(client, payload, filename)
    assert resp.status_code == 200, resp.status_code
    return client.post('/api/import/backup/execute')


# ---------------------------------------------------------------------------
# Access and validation
# ---------------------------------------------------------------------------

class TestBackupRestoreAccess:
    def test_upload_page_requires_auth(self, client):
        resp = client.get('/api/import/backup')
        assert resp.status_code in (302, 401)

    def test_preview_requires_auth(self, client):
        resp = client.post('/api/import/backup/preview')
        assert resp.status_code in (302, 401)

    def test_execute_requires_auth(self, client):
        resp = client.post('/api/import/backup/execute')
        assert resp.status_code in (302, 401)

    def test_upload_page_renders(self, auth_client):
        resp = auth_client.get('/api/import/backup')
        assert resp.status_code == 200
        assert b'Restore' in resp.data

    def test_settings_links_to_restore(self, auth_client):
        resp = auth_client.get('/auth/settings')
        assert resp.status_code == 200
        assert b'/api/import/backup' in resp.data

    def test_no_file_redirects(self, auth_client):
        resp = auth_client.post('/api/import/backup/preview')
        assert resp.status_code == 302

    def test_invalid_json_redirects(self, auth_client):
        resp = upload(auth_client, b'not json at all', 'bad.json')
        assert resp.status_code == 302

    def test_unrelated_json_redirects(self, auth_client, test_user):
        resp = upload(auth_client, json.dumps({'hello': 'world'}).encode(), 'other.json')
        assert resp.status_code == 302
        assert Vehicle.query.filter_by(owner_id=test_user.id).count() == 0

    def test_zip_without_data_json_redirects(self, auth_client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('something.txt', 'nope')
        resp = upload(auth_client, buf.getvalue(), 'bad.zip')
        assert resp.status_code == 302

    def test_execute_without_upload_redirects(self, auth_client):
        resp = auth_client.post('/api/import/backup/execute')
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

class TestBackupRestorePreview:
    def test_preview_shows_counts_and_writes_nothing(self, auth_client, test_user):
        resp = upload(auth_client, backup_json_bytes())
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'Old Car' in body
        assert 'Fuel logs' in body
        # Nothing committed by the preview
        assert Vehicle.query.filter_by(owner_id=test_user.id).count() == 0
        assert FuelLog.query.count() == 0

    def test_preview_reports_existing_records_as_present(self, auth_client, test_user):
        restore(auth_client, backup_json_bytes())
        resp = upload(auth_client, backup_json_bytes())
        assert resp.status_code == 200
        assert 'already in your account' in resp.data.decode()


# ---------------------------------------------------------------------------
# Restoring
# ---------------------------------------------------------------------------

class TestBackupRestoreJson:
    def test_restores_vehicle_and_records(self, auth_client, test_user):
        resp = restore(auth_client, backup_json_bytes())
        assert resp.status_code == 302

        vehicle = Vehicle.query.filter_by(owner_id=test_user.id).one()
        assert vehicle.name == 'Old Car'
        assert vehicle.vin == 'VIN123456'
        assert vehicle.tank_capacity == 47.0
        assert vehicle.specs.count() == 1

        assert vehicle.fuel_logs.count() == 2
        # #221 — a dual-fuel history has to survive the round trip, which means
        # both which fuel went in and the distance run on it.
        lpg_log = vehicle.fuel_logs.order_by(FuelLog.date).all()[1]
        assert lpg_log.fuel_type == 'lpg'
        assert lpg_log.fuel_distance == 320.0
        log = vehicle.fuel_logs.order_by(FuelLog.date).first()
        assert log.odometer == 10000.0
        assert log.station == 'Shell'
        assert log.sales_tax == 7.8  # #225
        assert log.user_id == test_user.id
        assert str(log.date) == '2024-01-15'

        assert vehicle.expenses.count() == 1
        assert vehicle.trips.count() == 1
        assert vehicle.charging_sessions.count() == 1
        assert vehicle.reminders.count() == 1
        assert vehicle.parts.count() == 1

        session = vehicle.charging_sessions.first()
        assert str(session.start_time) == '08:00:00'

    def test_restores_stations_and_price_history(self, auth_client, test_user):
        restore(auth_client, backup_json_bytes())
        station = FuelStation.query.filter_by(user_id=test_user.id).one()
        assert station.name == 'Shell Anytown'
        assert station.is_favorite is True
        prices = FuelPriceHistory.query.filter_by(station_id=station.id).all()
        assert len(prices) == 1
        assert prices[0].price_per_unit == 1.5

    def test_restore_is_idempotent(self, auth_client, test_user):
        restore(auth_client, backup_json_bytes())
        restore(auth_client, backup_json_bytes())

        assert Vehicle.query.filter_by(owner_id=test_user.id).count() == 1
        assert FuelLog.query.count() == 2
        assert Expense.query.count() == 1
        assert Trip.query.count() == 1
        assert ChargingSession.query.count() == 1
        assert Reminder.query.count() == 1
        assert VehiclePart.query.count() == 1
        assert FuelStation.query.filter_by(user_id=test_user.id).count() == 1
        assert FuelPriceHistory.query.count() == 1

    def test_merges_into_existing_vehicle_without_duplicating(self, auth_client,
                                                              test_user, sample_vehicle,
                                                              sample_fuel_log):
        """A backup vehicle matching an existing one merges rather than duplicating."""
        data = make_backup_data()
        data['vehicles'][0].update({
            'name': sample_vehicle.name,
            'make': sample_vehicle.make,
            'model': sample_vehicle.model,
            'year': sample_vehicle.year,
            'registration': None,
            'vin': None,
        })
        # One log matches the existing sample log exactly, one is new
        data['vehicles'][0]['fuel_logs'][0].update({
            'date': str(sample_fuel_log.date),
            'odometer': sample_fuel_log.odometer,
            'volume': sample_fuel_log.volume,
        })

        restore(auth_client, backup_json_bytes(data))

        assert Vehicle.query.filter_by(owner_id=test_user.id).count() == 1
        logs = FuelLog.query.filter_by(vehicle_id=sample_vehicle.id).all()
        assert len(logs) == 2

    def test_existing_data_is_never_removed(self, auth_client, test_user,
                                            sample_vehicle, sample_expense):
        """Restoring must not touch data the user already has."""
        restore(auth_client, backup_json_bytes())

        assert db.session.get(Vehicle, sample_vehicle.id) is not None
        assert db.session.get(Expense, sample_expense.id) is not None
        assert Vehicle.query.filter_by(owner_id=test_user.id).count() == 2

    def test_documents_without_files_are_skipped(self, auth_client, test_user):
        """A JSON export has no files, so documents cannot be restored from it."""
        data = make_backup_data()
        data['vehicles'][0]['documents'] = [{
            'id': 1, 'title': 'V5C', 'document_type': 'other',
            'original_filename': 'v5c.pdf', 'file_type': 'pdf',
        }]
        restore(auth_client, backup_json_bytes(data))
        assert Document.query.count() == 0

    def test_restore_only_affects_the_signed_in_account(self, auth_client, test_user,
                                                        admin_user):
        restore(auth_client, backup_json_bytes())
        assert Vehicle.query.filter_by(owner_id=admin_user.id).count() == 0
        assert Vehicle.query.filter_by(owner_id=test_user.id).count() == 1


class TestBackupRestoreZip:
    def test_restores_documents_and_files_from_zip(self, auth_client, test_user, app):
        data = make_backup_data()
        data['vehicles'][0]['documents'] = [{
            'id': 1, 'title': 'V5C', 'document_type': 'other',
            'filename': 'doc_abc123_v5c.pdf', 'original_filename': 'v5c.pdf',
            'file_type': 'pdf', 'file_size': 5,
        }]
        payload = make_full_backup_zip(data, {'doc_abc123_v5c.pdf': b'hello'})

        upload_folder = app.config['UPLOAD_FOLDER']
        target = os.path.join(upload_folder, 'doc_abc123_v5c.pdf')
        if os.path.exists(target):
            os.unlink(target)

        try:
            resp = restore(auth_client, payload, 'may_full_backup.zip')
            assert resp.status_code == 302

            document = Document.query.one()
            assert document.title == 'V5C'
            assert document.filename == 'doc_abc123_v5c.pdf'
            assert os.path.exists(target)
            with open(target, 'rb') as handle:
                assert handle.read() == b'hello'
        finally:
            if os.path.exists(target):
                os.unlink(target)

    def test_vehicle_attachments_restored_from_zip(self, auth_client, test_user, app):
        data = make_backup_data()
        data['vehicles'][0]['attachments'] = [{
            'id': 1, 'filename': 'att_1.png', 'original_filename': 'photo.png',
            'file_type': 'image', 'file_size': 3,
        }]
        data['vehicles'][0]['fuel_logs'][0]['attachments'] = [{
            'id': 2, 'filename': 'att_2.png', 'original_filename': 'receipt.png',
            'file_type': 'image', 'file_size': 3,
        }]
        payload = make_full_backup_zip(
            data, {'att_1.png': b'abc', 'att_2.png': b'def'})

        targets = [os.path.join(app.config['UPLOAD_FOLDER'], name)
                   for name in ('att_1.png', 'att_2.png')]
        for target in targets:
            if os.path.exists(target):
                os.unlink(target)

        try:
            restore(auth_client, payload, 'may_full_backup.zip')
            vehicle = Vehicle.query.filter_by(owner_id=test_user.id).one()
            assert vehicle.attachments.count() == 1
            log = vehicle.fuel_logs.order_by(FuelLog.date).first()
            assert log.attachments.count() == 1
            assert all(os.path.exists(target) for target in targets)
        finally:
            for target in targets:
                if os.path.exists(target):
                    os.unlink(target)

    def test_zip_restore_is_idempotent(self, auth_client, test_user, app):
        data = make_backup_data()
        data['vehicles'][0]['documents'] = [{
            'id': 1, 'title': 'V5C', 'document_type': 'other',
            'filename': 'doc_abc123_v5c.pdf', 'original_filename': 'v5c.pdf',
            'file_type': 'pdf', 'file_size': 5,
        }]
        payload = make_full_backup_zip(data, {'doc_abc123_v5c.pdf': b'hello'})
        target = os.path.join(app.config['UPLOAD_FOLDER'], 'doc_abc123_v5c.pdf')
        if os.path.exists(target):
            os.unlink(target)

        try:
            restore(auth_client, payload, 'may_full_backup.zip')
            restore(auth_client, payload, 'may_full_backup.zip')
            assert Document.query.count() == 1
            assert Vehicle.query.filter_by(owner_id=test_user.id).count() == 1
        finally:
            if os.path.exists(target):
                os.unlink(target)

    def test_zip_entries_outside_uploads_are_ignored(self, auth_client, app):
        """Path traversal in a backup ZIP must not write outside the uploads folder."""
        data = make_backup_data()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('data.json', json.dumps(data))
            zf.writestr('uploads/../escaped.txt', b'nope')
            zf.writestr('/etc/passwd', b'nope')
        payload = buf.getvalue()

        escaped = os.path.join(os.path.dirname(app.config['UPLOAD_FOLDER']), 'escaped.txt')
        # A traversing entry must not be written outside the uploads folder,
        # nor quietly flattened into it
        landed = os.path.join(app.config['UPLOAD_FOLDER'], 'escaped.txt')
        for path in (escaped, landed):
            if os.path.exists(path):
                os.unlink(path)

        resp = restore(auth_client, payload, 'may_full_backup.zip')
        assert resp.status_code == 302
        assert not os.path.exists(escaped)
        assert not os.path.exists(landed)


# ---------------------------------------------------------------------------
# Round trip through the real export endpoints
# ---------------------------------------------------------------------------

class TestBackupRoundTrip:
    """What the real export endpoints produce must feed back into the restore.

    This is the issue's actual scenario: a backup taken off one instance is
    loaded into another, where it lands in a different account. The restore is
    driven through its service here rather than through the HTTP routes,
    because the ``app`` fixture pushes a single long-lived app context, so
    Flask-Login's per-context ``current_user`` cache cannot be swapped to a
    second account mid-test.
    """

    def test_json_export_restores_into_another_account(
            self, auth_client, admin_user, sample_vehicle, sample_fuel_log,
            sample_expense):
        exported = auth_client.get('/api/export/json')
        assert exported.status_code == 200
        data = json.loads(exported.data)

        summary = restore_backup(data, admin_user)
        assert summary['total_added'] > 0

        vehicle = Vehicle.query.filter_by(owner_id=admin_user.id).one()
        assert vehicle.name == sample_vehicle.name
        assert vehicle.make == sample_vehicle.make
        assert vehicle.fuel_logs.count() == 1
        assert vehicle.expenses.count() == 1
        assert vehicle.fuel_logs.first().odometer == sample_fuel_log.odometer
        assert vehicle.expenses.first().cost == sample_expense.cost

    def test_full_backup_export_restores_into_another_account(
            self, app, auth_client, admin_user, sample_vehicle, sample_fuel_log,
            tmp_path):
        exported = auth_client.get('/api/export/backup')
        assert exported.status_code == 200

        archive = tmp_path / 'may_full_backup.zip'
        archive.write_bytes(exported.data)
        data, zip_path = read_backup(str(archive))
        assert zip_path is not None

        summary = restore_backup(data, admin_user, zip_path=zip_path,
                                 upload_folder=str(tmp_path / 'uploads'))
        assert summary['total_added'] > 0

        vehicle = Vehicle.query.filter_by(owner_id=admin_user.id).one()
        assert vehicle.name == sample_vehicle.name
        assert vehicle.fuel_logs.count() == 1

    def test_round_trip_restore_is_idempotent(
            self, auth_client, admin_user, sample_vehicle, sample_fuel_log):
        data = json.loads(auth_client.get('/api/export/json').data)

        restore_backup(data, admin_user)
        second = restore_backup(data, admin_user)
        assert second['total_added'] == 0

        assert Vehicle.query.filter_by(owner_id=admin_user.id).count() == 1
        vehicle = Vehicle.query.filter_by(owner_id=admin_user.id).one()
        assert vehicle.fuel_logs.count() == 1

    def test_round_trip_leaves_the_original_account_alone(
            self, auth_client, test_user, admin_user, sample_vehicle,
            sample_fuel_log):
        data = json.loads(auth_client.get('/api/export/json').data)
        restore_backup(data, admin_user)

        assert Vehicle.query.filter_by(owner_id=test_user.id).count() == 1
        assert FuelLog.query.filter_by(vehicle_id=sample_vehicle.id).count() == 1

    def test_preview_of_a_real_export_writes_nothing(
            self, auth_client, admin_user, sample_vehicle, sample_fuel_log):
        data = json.loads(auth_client.get('/api/export/json').data)

        summary = restore_backup(data, admin_user, dry_run=True)
        assert summary['total_added'] > 0
        assert Vehicle.query.filter_by(owner_id=admin_user.id).count() == 0
