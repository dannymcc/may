"""Restore a May backup (JSON export or full ZIP backup) into an account.

The restore always *merges*: records are added to the account that is signed
in, and any record that already matches an existing one on its natural key is
skipped rather than duplicated. Nothing is ever deleted or overwritten, so a
restore can never destroy data the user still has.

The two-step flow in the UI (preview, then apply) uses the same code path:
``restore_backup(..., dry_run=True)`` does the whole thing inside the request's
transaction and rolls it back, so the preview counts are exactly what a real
restore would do.
"""
import json
import logging
import os
import zipfile
from datetime import datetime, date, time

from app import db
from app.models import (
    Vehicle, FuelLog, Expense, Trip, ChargingSession, Reminder,
    MaintenanceSchedule, RecurringExpense, Document, VehicleSpec,
    VehiclePart, FuelStation, FuelPriceHistory, Attachment
)

logger = logging.getLogger(__name__)

# Sections we know how to restore, in the order they are shown in the summary
SECTION_LABELS = {
    'vehicles': 'Vehicles',
    'specifications': 'Specifications',
    'fuel_logs': 'Fuel logs',
    'expenses': 'Expenses',
    'trips': 'Trips',
    'charging_sessions': 'Charging sessions',
    'reminders': 'Reminders',
    'maintenance_schedules': 'Maintenance schedules',
    'recurring_expenses': 'Recurring expenses',
    'documents': 'Documents',
    'parts': 'Parts',
    'attachments': 'Attachments',
    'fuel_stations': 'Fuel stations',
    'fuel_price_history': 'Fuel price history',
    'files': 'Uploaded files',
}


class BackupError(Exception):
    """Raised when a backup file cannot be read or is not a May backup."""


# ---------------------------------------------------------------------------
# Value parsing / normalisation
# ---------------------------------------------------------------------------

def _parse_date(value):
    if value in (None, ''):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).date()
    except ValueError:
        return None


def _parse_datetime(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    # Stored columns are naive UTC
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(tz=None).replace(tzinfo=None)
    return parsed


def _parse_time(value):
    if value in (None, ''):
        return None
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _parse_float(value):
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value):
    if value in (None, ''):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_str(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


PARSERS = {
    'date': _parse_date,
    'datetime': _parse_datetime,
    'time': _parse_time,
    'bool': _parse_bool,
    'float': _parse_float,
    'int': _parse_int,
    'str': _parse_str,
}


def _normalise(value):
    """Make a value comparable between a backup record and a stored one."""
    if isinstance(value, str):
        return value.strip().lower() or None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 3)
    return value


def _key(values, key_fields):
    return tuple(_normalise(values.get(field)) for field in key_fields)


class Section:
    """How one kind of record is read from a backup and matched to existing rows."""

    def __init__(self, name, model, fields, key_fields, needs_file=False):
        self.name = name
        self.model = model
        self.fields = fields          # {column name: parser name}
        self.key_fields = key_fields  # columns forming the natural key
        self.needs_file = needs_file  # record is useless without its upload

    def parse(self, record):
        """Convert one backup record into column values, ignoring unknown keys."""
        values = {}
        for column, parser in self.fields.items():
            if column in record:
                values[column] = PARSERS[parser](record[column])
        return values

    def key_of_record(self, values):
        return _key(values, self.key_fields)

    def key_of_row(self, row):
        return _key({field: getattr(row, field, None) for field in self.key_fields},
                    self.key_fields)


VEHICLE_SECTION = Section(
    'vehicles', Vehicle,
    {
        'name': 'str', 'vehicle_type': 'str', 'make': 'str', 'model': 'str',
        'year': 'int', 'registration': 'str', 'vin': 'str',
        'tracking_unit': 'str', 'odometer_unit': 'str', 'fuel_type': 'str',
        'secondary_fuel_type': 'str', 'tank_capacity': 'float',
        'battery_capacity': 'float', 'is_active': 'bool', 'notes': 'str',
        'image_filename': 'str', 'mot_status': 'str', 'mot_expiry': 'date',
        'tax_status': 'str', 'tax_due': 'date', 'created_at': 'datetime',
    },
    key_fields=('name', 'make', 'model', 'year'),
)

# Child records, keyed by the section name used in the backup's vehicle blocks
VEHICLE_SECTIONS = [
    Section('specifications', VehicleSpec,
            {'spec_type': 'str', 'label': 'str', 'value': 'str',
             'created_at': 'datetime'},
            key_fields=('spec_type', 'label')),
    Section('fuel_logs', FuelLog,
            {'date': 'date', 'odometer': 'float', 'volume': 'float',
             'price_per_unit': 'float', 'discount_per_unit': 'float',
             'total_cost': 'float', 'sales_tax': 'float',
             'fuel_type': 'str', 'fuel_distance': 'float', 'is_full_tank': 'bool',
             'is_missed': 'bool', 'station': 'str', 'notes': 'str',
             'created_at': 'datetime'},
            key_fields=('date', 'odometer', 'volume')),
    Section('expenses', Expense,
            {'date': 'date', 'category': 'str', 'description': 'str',
             'cost': 'float', 'odometer': 'float', 'vendor': 'str',
             'notes': 'str', 'created_at': 'datetime'},
            key_fields=('date', 'category', 'description', 'cost')),
    Section('trips', Trip,
            {'date': 'date', 'start_odometer': 'float', 'end_odometer': 'float',
             'start_fuel_level': 'float', 'end_fuel_level': 'float',
             'purpose': 'str', 'description': 'str', 'start_location': 'str',
             'end_location': 'str', 'notes': 'str', 'created_at': 'datetime'},
            key_fields=('date', 'start_odometer', 'end_odometer', 'purpose')),
    Section('charging_sessions', ChargingSession,
            {'date': 'date', 'start_time': 'time', 'end_time': 'time',
             'odometer': 'float', 'kwh_added': 'float', 'start_soc': 'int',
             'end_soc': 'int', 'cost_per_kwh': 'float', 'total_cost': 'float',
             'charger_type': 'str', 'location': 'str', 'network': 'str',
             'notes': 'str', 'created_at': 'datetime'},
            key_fields=('date', 'start_time', 'odometer', 'kwh_added')),
    Section('reminders', Reminder,
            {'title': 'str', 'description': 'str', 'reminder_type': 'str',
             'due_date': 'date', 'recurrence': 'str',
             'recurrence_interval': 'int', 'notify_days_before': 'int',
             'notification_sent': 'bool', 'is_completed': 'bool',
             'completed_at': 'datetime', 'created_at': 'datetime'},
            key_fields=('title', 'reminder_type', 'due_date')),
    Section('maintenance_schedules', MaintenanceSchedule,
            {'name': 'str', 'maintenance_type': 'str', 'description': 'str',
             'interval_miles': 'int', 'interval_km': 'int',
             'interval_hours': 'int',
             'interval_months': 'int', 'last_performed_date': 'date',
             'last_performed_odometer': 'float', 'next_due_date': 'date',
             'next_due_odometer': 'float', 'estimated_cost': 'float',
             'auto_remind': 'bool', 'remind_days_before': 'int',
             'remind_miles_before': 'int', 'is_active': 'bool',
             'created_at': 'datetime'},
            key_fields=('name', 'maintenance_type')),
    Section('recurring_expenses', RecurringExpense,
            {'name': 'str', 'category': 'str', 'description': 'str',
             'amount': 'float', 'vendor': 'str', 'frequency': 'str',
             'start_date': 'date', 'end_date': 'date', 'last_generated': 'date',
             'next_due': 'date', 'auto_create': 'bool',
             'notify_before_days': 'int', 'is_active': 'bool',
             'created_at': 'datetime'},
            key_fields=('name', 'category', 'start_date')),
    Section('documents', Document,
            {'title': 'str', 'document_type': 'str', 'description': 'str',
             'filename': 'str', 'original_filename': 'str', 'file_type': 'str',
             'file_size': 'int', 'issue_date': 'date', 'expiry_date': 'date',
             'reference_number': 'str', 'remind_before_expiry': 'bool',
             'remind_days': 'int', 'created_at': 'datetime'},
            key_fields=('title', 'document_type', 'filename'),
            needs_file=True),
    Section('parts', VehiclePart,
            {'name': 'str', 'part_type': 'str', 'specification': 'str',
             'quantity': 'float', 'unit': 'str', 'part_number': 'str',
             'supplier_url': 'str', 'notes': 'str', 'created_at': 'datetime',
             'updated_at': 'datetime'},
            key_fields=('name', 'part_type', 'part_number')),
]

ATTACHMENT_SECTION = Section(
    'attachments', Attachment,
    {'filename': 'str', 'original_filename': 'str', 'file_type': 'str',
     'file_size': 'int', 'description': 'str', 'created_at': 'datetime'},
    key_fields=('filename',),
    needs_file=True,
)

STATION_SECTION = Section(
    'fuel_stations', FuelStation,
    {'name': 'str', 'brand': 'str', 'address': 'str', 'city': 'str',
     'postcode': 'str', 'latitude': 'float', 'longitude': 'float',
     'notes': 'str', 'is_favorite': 'bool', 'times_used': 'int',
     'last_used': 'datetime', 'created_at': 'datetime'},
    key_fields=('name', 'address', 'postcode'),
)

PRICE_SECTION = Section(
    'fuel_price_history', FuelPriceHistory,
    {'date': 'date', 'fuel_type': 'str', 'price_per_unit': 'float',
     'created_at': 'datetime'},
    key_fields=('date', 'fuel_type', 'price_per_unit'),
)


# ---------------------------------------------------------------------------
# Reading the uploaded file
# ---------------------------------------------------------------------------

def read_backup(path):
    """Read a backup from disk.

    Accepts either a JSON export (``may_backup_*.json``) or a full backup
    ZIP (``may_full_backup_*.zip``) containing ``data.json``.

    Returns ``(data, zip_path)`` where ``zip_path`` is None for JSON backups.
    Raises :class:`BackupError` if the file is not a May backup.
    """
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                if 'data.json' not in names:
                    raise BackupError(
                        'This ZIP does not contain a data.json file, so it is '
                        'not a May full backup.'
                    )
                raw = zf.read('data.json')
        except zipfile.BadZipFile as exc:
            raise BackupError('The uploaded ZIP file could not be read.') from exc
        data = _load_json(raw)
        return _validate(data), path

    with open(path, 'rb') as handle:
        raw = handle.read()
    data = _load_json(raw)
    return _validate(data), None


def _load_json(raw):
    try:
        return json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError('The file is not valid JSON.') from exc


def _validate(data):
    if not isinstance(data, dict):
        raise BackupError('The file does not contain a May backup.')
    if 'vehicles' not in data and 'fuel_stations' not in data:
        raise BackupError(
            'This does not look like a May backup — no vehicles or fuel '
            'stations were found. Use the JSON or full backup file produced '
            'by the export page.'
        )
    return data


def describe_backup(data):
    """Human-readable details about where a backup came from."""
    info = data.get('export_info') or {}
    return {
        'exported_at': info.get('exported_at'),
        'username': info.get('username'),
        'app_version': info.get('app_version'),
        'backup_type': info.get('backup_type') or 'json',
    }


# ---------------------------------------------------------------------------
# Restoring
# ---------------------------------------------------------------------------

def _new_summary():
    return {name: {'added': 0, 'skipped': 0} for name in SECTION_LABELS}


def _zip_upload_names(zip_path):
    """Names of the files stored under uploads/ in a full backup ZIP."""
    if not zip_path:
        return {}
    available = {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.startswith('uploads/') or name.endswith('/'):
                continue
            base = name[len('uploads/'):]
            # The export writes every upload as a plain name directly under
            # uploads/, so anything with a path in it is not ours to restore.
            if not base or '/' in base or '\\' in base or base in ('.', '..'):
                continue
            available[base] = name
    return available


def restore_backup(data, user, zip_path=None, upload_folder=None, dry_run=False):
    """Merge a backup into ``user``'s account.

    Existing records are never modified or deleted; a record whose natural key
    already exists is counted as skipped. With ``dry_run`` the work is done and
    then rolled back, so the returned summary previews a real restore.
    """
    summary = _new_summary()
    summary['vehicle_details'] = []
    available_files = _zip_upload_names(zip_path)

    try:
        _restore_vehicles(data, user, summary, available_files)
        _restore_stations(data, user, summary)
        _copy_files(zip_path, available_files, upload_folder, summary,
                    dry_run=dry_run)
        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    summary['total_added'] = sum(
        counts['added'] for name, counts in summary.items()
        if name in SECTION_LABELS
    )
    summary['total_skipped'] = sum(
        counts['skipped'] for name, counts in summary.items()
        if name in SECTION_LABELS
    )
    return summary


def _vehicle_match(vehicle_values, existing):
    """Find an existing vehicle for a backup vehicle.

    VIN and registration are stable identifiers, so they win; otherwise fall
    back to name/make/model/year.
    """
    for field in ('vin', 'registration'):
        value = _normalise(vehicle_values.get(field))
        if value:
            for row in existing:
                if _normalise(getattr(row, field, None)) == value:
                    return row
    key = VEHICLE_SECTION.key_of_record(vehicle_values)
    for row in existing:
        if VEHICLE_SECTION.key_of_row(row) == key:
            return row
    return None


def _restore_vehicles(data, user, summary, available_files):
    existing_vehicles = list(
        Vehicle.query.filter_by(owner_id=user.id).all()
    )

    for raw_vehicle in data.get('vehicles') or []:
        if not isinstance(raw_vehicle, dict):
            continue
        values = VEHICLE_SECTION.parse(raw_vehicle)
        if not values.get('name'):
            values['name'] = 'Restored Vehicle'
        if not values.get('vehicle_type'):
            values['vehicle_type'] = 'car'

        vehicle = _vehicle_match(values, existing_vehicles)
        detail = {'name': values['name'], 'sections': {}}
        if vehicle is None:
            if not values.get('image_filename') or (
                    values['image_filename'] not in available_files):
                values['image_filename'] = None
            vehicle = Vehicle(owner_id=user.id, **values)
            db.session.add(vehicle)
            db.session.flush()
            existing_vehicles.append(vehicle)
            summary['vehicles']['added'] += 1
            detail['status'] = 'new'
        else:
            summary['vehicles']['skipped'] += 1
            detail['status'] = 'existing'

        for section in VEHICLE_SECTIONS:
            added, skipped, (attach_added, attach_skipped) = _restore_child_records(
                section, raw_vehicle.get(section.name) or [], vehicle, user,
                available_files
            )
            summary[section.name]['added'] += added
            summary[section.name]['skipped'] += skipped
            summary['attachments']['added'] += attach_added
            summary['attachments']['skipped'] += attach_skipped
            if added or skipped:
                detail['sections'][section.name] = {'added': added, 'skipped': skipped}

        added, skipped = _restore_attachments(
            raw_vehicle.get('attachments') or [], vehicle, user,
            available_files, owner_field='vehicle_id', owner_id=vehicle.id
        )
        summary['attachments']['added'] += added
        summary['attachments']['skipped'] += skipped
        if added or skipped:
            detail['sections']['attachments'] = {'added': added, 'skipped': skipped}

        summary['vehicle_details'].append(detail)


def _existing_keys(section, vehicle_id):
    query = section.model.query.filter_by(vehicle_id=vehicle_id)
    return {section.key_of_row(row) for row in query.all()}


ATTACHMENT_OWNERS = {'fuel_logs': 'fuel_log_id', 'expenses': 'expense_id'}


def _restore_child_records(section, records, vehicle, user, available_files):
    """Add a vehicle's child records, skipping ones that already exist.

    Returns ``(added, skipped, attachments)`` where ``attachments`` is the
    ``(added, skipped)`` pair for any attachments hanging off these records.
    """
    added = skipped = 0
    attach_added = attach_skipped = 0
    seen = _existing_keys(section, vehicle.id)
    owner_field = ATTACHMENT_OWNERS.get(section.name)

    for record in records:
        if not isinstance(record, dict):
            continue
        values = section.parse(record)
        if section.needs_file:
            filename = values.get('filename')
            if not filename or filename not in available_files:
                # Without the uploaded file the record would point at nothing
                skipped += 1
                continue
        key = section.key_of_record(values)
        if key in seen:
            skipped += 1
            if owner_field:
                # The record is already here, so its attachments may be too;
                # they are counted as skipped rather than duplicated.
                attach_skipped += len(record.get('attachments') or [])
            continue

        row = section.model(vehicle_id=vehicle.id, **values)
        if hasattr(section.model, 'user_id'):
            row.user_id = user.id
        db.session.add(row)
        seen.add(key)
        added += 1

        if owner_field and record.get('attachments'):
            db.session.flush()
            sub_added, sub_skipped = _restore_attachments(
                record['attachments'], vehicle, user, available_files,
                owner_field=owner_field, owner_id=row.id
            )
            attach_added += sub_added
            attach_skipped += sub_skipped

    return added, skipped, (attach_added, attach_skipped)


def _restore_attachments(records, vehicle, user, available_files,
                         owner_field='vehicle_id', owner_id=None):
    added = skipped = 0
    section = ATTACHMENT_SECTION
    existing = {
        section.key_of_row(row)
        for row in Attachment.query.filter_by(**{owner_field: owner_id}).all()
    }

    for record in records:
        if not isinstance(record, dict):
            continue
        values = section.parse(record)
        filename = values.get('filename')
        if not filename or filename not in available_files:
            skipped += 1
            continue
        if not values.get('original_filename'):
            values['original_filename'] = filename
        key = section.key_of_record(values)
        if key in existing:
            skipped += 1
            continue
        db.session.add(Attachment(**{owner_field: owner_id}, **values))
        existing.add(key)
        added += 1

    return added, skipped


def _restore_stations(data, user, summary):
    existing = list(FuelStation.query.filter_by(user_id=user.id).all())
    seen = {STATION_SECTION.key_of_row(row) for row in existing}
    # Old station id -> station row, so price history can be reattached
    station_by_old_id = {}
    station_by_name = {
        _normalise(row.name): row for row in existing if row.name
    }

    for record in data.get('fuel_stations') or []:
        if not isinstance(record, dict):
            continue
        values = STATION_SECTION.parse(record)
        if not values.get('name'):
            continue
        key = STATION_SECTION.key_of_record(values)
        if key in seen:
            summary['fuel_stations']['skipped'] += 1
            match = next(
                (row for row in existing
                 if STATION_SECTION.key_of_row(row) == key), None
            )
            if match is not None and record.get('id') is not None:
                station_by_old_id[record['id']] = match
            continue
        station = FuelStation(user_id=user.id, **values)
        db.session.add(station)
        db.session.flush()
        existing.append(station)
        seen.add(key)
        station_by_name.setdefault(_normalise(station.name), station)
        if record.get('id') is not None:
            station_by_old_id[record['id']] = station
        summary['fuel_stations']['added'] += 1

    _restore_price_history(data, user, summary, station_by_old_id, station_by_name)


def _restore_price_history(data, user, summary, station_by_old_id, station_by_name):
    seen_by_station = {}

    for record in data.get('fuel_price_history') or []:
        if not isinstance(record, dict):
            continue
        station = station_by_old_id.get(record.get('station_id'))
        if station is None:
            station = station_by_name.get(_normalise(record.get('station_name')))
        if station is None:
            summary['fuel_price_history']['skipped'] += 1
            continue

        if station.id not in seen_by_station:
            seen_by_station[station.id] = {
                PRICE_SECTION.key_of_row(row)
                for row in FuelPriceHistory.query.filter_by(
                    station_id=station.id).all()
            }
        seen = seen_by_station[station.id]

        values = PRICE_SECTION.parse(record)
        key = PRICE_SECTION.key_of_record(values)
        if key in seen:
            summary['fuel_price_history']['skipped'] += 1
            continue
        db.session.add(FuelPriceHistory(
            station_id=station.id, user_id=user.id, **values))
        seen.add(key)
        summary['fuel_price_history']['added'] += 1


def _copy_files(zip_path, available_files, upload_folder, summary, dry_run=False):
    """Copy uploaded files out of a full backup ZIP into the uploads folder.

    Files already present are left alone — upload names are UUID-prefixed, so
    a clash means the same file has been restored before.
    """
    if not zip_path or not available_files or not upload_folder:
        return

    if not dry_run:
        os.makedirs(upload_folder, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        for base, name in available_files.items():
            target = os.path.join(upload_folder, base)
            if os.path.exists(target):
                summary['files']['skipped'] += 1
                continue
            if dry_run:
                summary['files']['added'] += 1
                continue
            try:
                with zf.open(name) as source, open(target, 'wb') as dest:
                    dest.write(source.read())
                summary['files']['added'] += 1
            except (KeyError, OSError) as exc:
                logger.warning('Backup restore: could not write %s: %s', base, exc)
                summary['files']['skipped'] += 1
