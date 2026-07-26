"""
Backup service: create, list, and manage automated backup files on disk.
Backups use the same ZIP format as the manual Full Backup export.
"""
import hashlib
import io
import json
import logging
import os
import zipfile
from datetime import datetime

logger = logging.getLogger(__name__)


def get_backup_dir(app):
    """Return the backup directory path (creates it if missing)."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('sqlite:///') and ':memory:' not in db_uri:
        db_path = db_uri.replace('sqlite:///', '')
        data_dir = os.path.dirname(db_path)
    else:
        data_dir = app.config['UPLOAD_FOLDER']
    backup_dir = os.path.join(data_dir, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def create_backup_file(user, upload_folder, backup_dir):
    """
    Create a full backup ZIP for *user* and save it to *backup_dir*.
    Returns the filename of the created backup.
    """
    from config import APP_VERSION

    export_data = {
        'export_info': {
            'exported_at': datetime.utcnow().isoformat(),
            'username': user.username,
            'app_version': APP_VERSION,
            'backup_type': 'full'
        },
        'user_preferences': {
            'language': user.language,
            'distance_unit': user.distance_unit,
            'volume_unit': user.volume_unit,
            'consumption_unit': user.consumption_unit,
            'currency': user.currency
        },
        'vehicles': [],
        'fuel_stations': [],
        'fuel_price_history': []
    }

    files_to_backup = []  # [(filename, file_type, record_type, record_id)]

    for vehicle in user.get_all_vehicles():
        vehicle_data = _serialize_vehicle(vehicle, files_to_backup)
        export_data['vehicles'].append(vehicle_data)

    for station in user.fuel_stations.all():
        export_data['fuel_stations'].append(_serialize_station(station))
        for price in station.price_history.all():
            export_data['fuel_price_history'].append({
                'id': price.id,
                'station_id': station.id,
                'station_name': station.name,
                'date': price.date.isoformat() if price.date else None,
                'fuel_type': price.fuel_type,
                'price_per_unit': price.price_per_unit,
                'created_at': price.created_at.isoformat() if price.created_at else None
            })

    manifest = {
        'version': APP_VERSION,
        'created_at': datetime.utcnow().isoformat(),
        'username': user.username,
        'files': []
    }

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        seen_files = set()
        for filename, file_type, record_type, record_id in files_to_backup:
            if not filename or filename in seen_files:
                continue
            seen_files.add(filename)
            file_path = os.path.join(upload_folder, filename)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        file_data = f.read()
                    file_hash = hashlib.sha256(file_data).hexdigest()
                    zf.writestr(f'uploads/{filename}', file_data)
                    manifest['files'].append({
                        'filename': filename,
                        'type': record_type,
                        'record_id': record_id,
                        'file_type': file_type,
                        'size': len(file_data),
                        'sha256': file_hash
                    })
                except (IOError, OSError):
                    pass

        export_data['files_manifest'] = {
            'total_files': len(manifest['files']),
            'files': manifest['files']
        }

        zf.writestr('data.json', json.dumps(export_data, indent=2))
        zf.writestr('manifest.json', json.dumps(manifest, indent=2))

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    fname = f'willman_backup_{user.username}_{timestamp}.zip'
    fpath = os.path.join(backup_dir, fname)

    with open(fpath, 'wb') as f:
        f.write(zip_buffer.getvalue())

    logger.info('Automated backup created: %s', fpath)
    return fname


def list_backups(backup_dir):
    """Return a list of backup dicts sorted newest-first."""
    if not os.path.exists(backup_dir):
        return []
    backups = []
    for fname in os.listdir(backup_dir):
        if fname.endswith('.zip'):
            fpath = os.path.join(backup_dir, fname)
            stat = os.stat(fpath)
            backups.append({
                'filename': fname,
                'size': stat.st_size,
                'created_at': datetime.fromtimestamp(stat.st_mtime)
            })
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return backups


def cleanup_old_backups(backup_dir, retention_count):
    """Delete backups beyond *retention_count* (oldest first). Returns count deleted."""
    backups = list_backups(backup_dir)
    to_delete = backups[retention_count:]
    deleted = 0
    for backup in to_delete:
        try:
            os.remove(os.path.join(backup_dir, backup['filename']))
            deleted += 1
            logger.info('Deleted old backup: %s', backup['filename'])
        except OSError as e:
            logger.warning('Could not delete backup %s: %s', backup['filename'], e)
    return deleted


# ---------------------------------------------------------------------------
# Serialisation helpers (mirror the logic in api.py export_full_backup)
# ---------------------------------------------------------------------------

def _serialize_vehicle(vehicle, files_to_backup):
    vd = {
        'id': vehicle.id,
        'name': vehicle.name,
        'vehicle_type': vehicle.vehicle_type,
        'make': vehicle.make,
        'model': vehicle.model,
        'year': vehicle.year,
        'registration': vehicle.registration,
        'vin': vehicle.vin,
        'fuel_type': vehicle.fuel_type,
        'tank_capacity': vehicle.tank_capacity,
        'battery_capacity': vehicle.battery_capacity,
        'is_active': vehicle.is_active,
        'notes': vehicle.notes,
        'image_filename': vehicle.image_filename,
        'mot_status': vehicle.mot_status,
        'mot_expiry': vehicle.mot_expiry.isoformat() if vehicle.mot_expiry else None,
        'tax_status': vehicle.tax_status,
        'tax_due': vehicle.tax_due.isoformat() if vehicle.tax_due else None,
        'created_at': vehicle.created_at.isoformat() if vehicle.created_at else None,
        'specifications': [],
        'fuel_logs': [],
        'expenses': [],
        'reminders': [],
        'maintenance_schedules': [],
        'recurring_expenses': [],
        'documents': [],
        'trips': [],
        'charging_sessions': [],
        'parts': [],
        'attachments': [],
        'vehicle_notes': []
    }

    if vehicle.image_filename:
        files_to_backup.append((vehicle.image_filename, 'image', 'vehicle', vehicle.id))

    for att in vehicle.attachments.all():
        vd['attachments'].append({
            'id': att.id, 'filename': att.filename,
            'original_filename': att.original_filename, 'file_type': att.file_type,
            'file_size': att.file_size, 'description': att.description,
            'created_at': att.created_at.isoformat() if att.created_at else None
        })
        files_to_backup.append((att.filename, att.file_type, 'vehicle_attachment', att.id))

    for spec in vehicle.specs.all():
        vd['specifications'].append({
            'id': spec.id, 'spec_type': spec.spec_type, 'label': spec.label,
            'value': spec.value,
            'created_at': spec.created_at.isoformat() if spec.created_at else None
        })

    from app.models import FuelLog
    for log in vehicle.fuel_logs.order_by(FuelLog.date.desc()).all():
        ld = {
            'id': log.id,
            'date': log.date.isoformat() if log.date else None,
            'odometer': log.odometer, 'volume': log.volume,
            'price_per_unit': log.price_per_unit, 'total_cost': log.total_cost,
            'is_full_tank': log.is_full_tank, 'is_missed': log.is_missed,
            'station': log.station, 'notes': log.notes,
            'created_at': log.created_at.isoformat() if log.created_at else None,
            'attachments': []
        }
        for att in log.attachments.all():
            ld['attachments'].append({
                'id': att.id, 'filename': att.filename,
                'original_filename': att.original_filename, 'file_type': att.file_type,
                'file_size': att.file_size, 'description': att.description,
                'created_at': att.created_at.isoformat() if att.created_at else None
            })
            files_to_backup.append((att.filename, att.file_type, 'fuel_log_attachment', att.id))
        vd['fuel_logs'].append(ld)

    from app.models import Expense
    for exp in vehicle.expenses.order_by(Expense.date.desc()).all():
        ed = {
            'id': exp.id,
            'date': exp.date.isoformat() if exp.date else None,
            'category': exp.category, 'description': exp.description,
            'cost': exp.cost, 'odometer': exp.odometer, 'vendor': exp.vendor,
            'notes': exp.notes,
            'created_at': exp.created_at.isoformat() if exp.created_at else None,
            'attachments': []
        }
        for att in exp.attachments.all():
            ed['attachments'].append({
                'id': att.id, 'filename': att.filename,
                'original_filename': att.original_filename, 'file_type': att.file_type,
                'file_size': att.file_size, 'description': att.description,
                'created_at': att.created_at.isoformat() if att.created_at else None
            })
            files_to_backup.append((att.filename, att.file_type, 'expense_attachment', att.id))
        vd['expenses'].append(ed)

    for rem in vehicle.reminders.all():
        vd['reminders'].append({
            'id': rem.id, 'title': rem.title, 'description': rem.description,
            'reminder_type': rem.reminder_type,
            'due_date': rem.due_date.isoformat() if rem.due_date else None,
            'recurrence': rem.recurrence, 'recurrence_interval': rem.recurrence_interval,
            'notify_days_before': rem.notify_days_before,
            'notification_sent': rem.notification_sent,
            'is_completed': rem.is_completed,
            'completed_at': rem.completed_at.isoformat() if rem.completed_at else None,
            'created_at': rem.created_at.isoformat() if rem.created_at else None
        })

    for sched in vehicle.maintenance_schedules.all():
        vd['maintenance_schedules'].append({
            'id': sched.id, 'name': sched.name, 'maintenance_type': sched.maintenance_type,
            'description': sched.description,
            'interval_miles': sched.interval_miles, 'interval_km': sched.interval_km,
            'interval_months': sched.interval_months,
            'last_performed_date': sched.last_performed_date.isoformat() if sched.last_performed_date else None,
            'last_performed_odometer': sched.last_performed_odometer,
            'next_due_date': sched.next_due_date.isoformat() if sched.next_due_date else None,
            'next_due_odometer': sched.next_due_odometer,
            'estimated_cost': sched.estimated_cost, 'auto_remind': sched.auto_remind,
            'remind_days_before': sched.remind_days_before,
            'remind_miles_before': sched.remind_miles_before,
            'is_active': sched.is_active,
            'created_at': sched.created_at.isoformat() if sched.created_at else None
        })

    for rec in vehicle.recurring_expenses.all():
        vd['recurring_expenses'].append({
            'id': rec.id, 'name': rec.name, 'category': rec.category,
            'description': rec.description, 'amount': rec.amount, 'vendor': rec.vendor,
            'frequency': rec.frequency,
            'start_date': rec.start_date.isoformat() if rec.start_date else None,
            'end_date': rec.end_date.isoformat() if rec.end_date else None,
            'last_generated': rec.last_generated.isoformat() if rec.last_generated else None,
            'next_due': rec.next_due.isoformat() if rec.next_due else None,
            'auto_create': rec.auto_create, 'notify_before_days': rec.notify_before_days,
            'is_active': rec.is_active,
            'created_at': rec.created_at.isoformat() if rec.created_at else None
        })

    for doc in vehicle.documents.all():
        vd['documents'].append({
            'id': doc.id, 'title': doc.title, 'document_type': doc.document_type,
            'description': doc.description, 'filename': doc.filename,
            'original_filename': doc.original_filename, 'file_type': doc.file_type,
            'file_size': doc.file_size,
            'issue_date': doc.issue_date.isoformat() if doc.issue_date else None,
            'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None,
            'reference_number': doc.reference_number,
            'remind_before_expiry': doc.remind_before_expiry,
            'remind_days': doc.remind_days,
            'created_at': doc.created_at.isoformat() if doc.created_at else None
        })
        files_to_backup.append((doc.filename, doc.file_type, 'document', doc.id))

    from app.models import Trip
    for trip in vehicle.trips.order_by(Trip.date.desc()).all():
        vd['trips'].append({
            'id': trip.id,
            'date': trip.date.isoformat() if trip.date else None,
            'start_odometer': trip.start_odometer, 'end_odometer': trip.end_odometer,
            'distance': trip.distance, 'purpose': trip.purpose,
            'description': trip.description, 'start_location': trip.start_location,
            'end_location': trip.end_location, 'notes': trip.notes,
            'created_at': trip.created_at.isoformat() if trip.created_at else None
        })

    from app.models import ChargingSession
    for cs in vehicle.charging_sessions.order_by(ChargingSession.date.desc()).all():
        vd['charging_sessions'].append({
            'id': cs.id,
            'date': cs.date.isoformat() if cs.date else None,
            'start_time': cs.start_time.isoformat() if cs.start_time else None,
            'end_time': cs.end_time.isoformat() if cs.end_time else None,
            'odometer': cs.odometer, 'kwh_added': cs.kwh_added,
            'start_soc': cs.start_soc, 'end_soc': cs.end_soc,
            'cost_per_kwh': cs.cost_per_kwh, 'total_cost': cs.total_cost,
            'charger_type': cs.charger_type, 'location': cs.location,
            'network': cs.network, 'notes': cs.notes,
            'created_at': cs.created_at.isoformat() if cs.created_at else None
        })

    for part in vehicle.parts.all():
        vd['parts'].append({
            'id': part.id, 'name': part.name, 'part_type': part.part_type,
            'specification': part.specification, 'quantity': part.quantity,
            'unit': part.unit, 'part_number': part.part_number,
            'supplier_url': part.supplier_url, 'notes': part.notes,
            'created_at': part.created_at.isoformat() if part.created_at else None,
            'updated_at': part.updated_at.isoformat() if part.updated_at else None
        })

    from app.models import VehicleNote
    for note in vehicle.vehicle_notes.order_by(VehicleNote.created_at.asc()).all():
        vd['vehicle_notes'].append({
            'id': note.id, 'title': note.title, 'content': note.content,
            'is_pinned': note.is_pinned,
            'created_at': note.created_at.isoformat() if note.created_at else None,
            'updated_at': note.updated_at.isoformat() if note.updated_at else None,
        })

    return vd


def _serialize_station(station):
    return {
        'id': station.id, 'name': station.name, 'brand': station.brand,
        'address': station.address, 'city': station.city, 'postcode': station.postcode,
        'latitude': station.latitude, 'longitude': station.longitude,
        'notes': station.notes, 'is_favorite': station.is_favorite,
        'times_used': station.times_used,
        'last_used': station.last_used.isoformat() if station.last_used else None,
        'created_at': station.created_at.isoformat() if station.created_at else None
    }
