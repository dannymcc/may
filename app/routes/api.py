import csv
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import tempfile
import traceback
import zipfile
from functools import wraps
from datetime import datetime
from flask import Blueprint, jsonify, request, send_from_directory, current_app, url_for, render_template, Response, flash, redirect, session
from flask_login import login_required, current_user
from app import db
from app.models import (
    User, Vehicle, VehicleSpec, FuelLog, Expense, EXPENSE_CATEGORIES,
    Reminder, MaintenanceSchedule, RecurringExpense, FuelStation,
    Document, Trip, ChargingSession, VehiclePart, FuelPriceHistory, Attachment,
    TRIP_PURPOSES, CHARGER_TYPES, fuel_type_label
)
from app.services.tessie import TessieService
from app.services.backup_restore import (
    BackupError, SECTION_LABELS, describe_backup, read_backup, restore_backup
)
from app.utils import parse_decimal, parse_fuel_level, utcnow
from flask_babel import gettext as _
from config import APP_VERSION

logger = logging.getLogger(__name__)

bp = Blueprint('api', __name__, url_prefix='/api')


# =============================================================================
# API Documentation
# =============================================================================

@bp.route('/docs')
@login_required
def docs():
    """API Documentation page"""
    return render_template('api/docs.html')


# =============================================================================
# API Authentication
# =============================================================================

def api_auth_required(f):
    """Decorator for API key authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = None

        # Check Authorization header
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            api_key = auth_header[7:]

        # Check X-API-Key header
        if not api_key:
            api_key = request.headers.get('X-API-Key')

        if not api_key:
            return jsonify({'error': 'API key required', 'code': 'missing_api_key'}), 401

        user = User.get_by_api_key(api_key)
        if not user:
            return jsonify({'error': 'Invalid API key', 'code': 'invalid_api_key'}), 401

        # Attach user to request context
        request.api_user = user
        return f(*args, **kwargs)

    return decorated_function


def get_api_user():
    """Get the authenticated API user"""
    return getattr(request, 'api_user', None)


# =============================================================================
# API Key Management (Web UI routes)
# =============================================================================

@bp.route('/toggle-dark-mode', methods=['POST'])
@login_required
def toggle_dark_mode():
    """Toggle dark mode for the current user"""
    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    return jsonify({'dark_mode': current_user.dark_mode})


@bp.route('/key/generate', methods=['POST'])
@login_required
def generate_api_key():
    """Generate a new API key for the current user"""
    api_key = current_user.generate_api_key()
    db.session.commit()
    return jsonify({
        'api_key': api_key,
        'created_at': current_user.api_key_created_at.isoformat()
    })


@bp.route('/key/revoke', methods=['POST'])
@login_required
def revoke_api_key():
    """Revoke the current user's API key"""
    current_user.revoke_api_key()
    db.session.commit()
    return jsonify({'success': True})


# =============================================================================
# Notification Testing
# =============================================================================

@bp.route('/notifications/test', methods=['POST'])
@login_required
def test_notification():
    """Send a test notification using the form values (not saved settings)"""
    from app.services.notifications import NotificationService

    # Get the method and settings from the form
    method = request.form.get('notification_method', 'email')
    title = "Test Notification from May"
    message = "This is a test notification to verify your settings are working correctly."

    if method == 'email':
        success, error = NotificationService.send_email(
            current_user.email,
            title,
            message,
            f"<html><body><h2>{title}</h2><p>{message}</p></body></html>"
        )
    elif method == 'ntfy':
        topic = request.form.get('ntfy_topic')
        if not topic:
            return jsonify({'success': False, 'error': 'Please enter an ntfy topic'})
        token = request.form.get('ntfy_token') or current_user.ntfy_token or None
        success, error = NotificationService.send_ntfy(topic, title, message, token=token)
    elif method == 'pushover':
        user_key = request.form.get('pushover_user_key')
        if not user_key:
            return jsonify({'success': False, 'error': 'Please enter your Pushover user key'})
        success, error = NotificationService.send_pushover(user_key, title, message)
    elif method == 'webhook':
        webhook_url = request.form.get('webhook_url')
        if not webhook_url:
            return jsonify({'success': False, 'error': 'Please enter a webhook URL'})
        payload = {
            'title': title,
            'message': message,
            'user_email': current_user.email,
            'test': True,
        }
        success, error = NotificationService.send_webhook(webhook_url, payload)
    else:
        return jsonify({'success': False, 'error': f'Unknown method: {method}'})

    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error})


@bp.route('/smtp/test', methods=['POST'])
@login_required
def test_smtp():
    """Test SMTP settings (admin only)"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Access denied'})

    from app.services.notifications import NotificationService

    config = {
        'host': request.form.get('smtp_host'),
        'port': request.form.get('smtp_port', '587'),
        'username': request.form.get('smtp_username'),
        'password': request.form.get('smtp_password'),
        'use_tls': request.form.get('smtp_tls') == 'true',
        'use_ssl': request.form.get('smtp_ssl') == 'true',
    }

    success, message = NotificationService.test_smtp(config)

    if success:
        # If connection test passed, try sending an actual test email
        from app.models import AppSettings
        sender = request.form.get('smtp_sender') or config['username']
        sender_name = request.form.get('smtp_sender_name') or 'May'

        # Temporarily set the config for sending
        old_config = NotificationService.get_smtp_config()
        AppSettings.set('smtp_host', config['host'])
        AppSettings.set('smtp_port', config['port'])
        AppSettings.set('smtp_username', config['username'])
        AppSettings.set('smtp_password', config['password'])
        AppSettings.set('smtp_sender', sender)
        AppSettings.set('smtp_sender_name', sender_name)
        AppSettings.set('smtp_tls', 'true' if config['use_tls'] else 'false')
        AppSettings.set('smtp_ssl', 'true' if config['use_ssl'] else 'false')

        send_success, send_error = NotificationService.send_email(
            current_user.email,
            "Test Email from May",
            "This is a test email to verify your SMTP settings are configured correctly.",
            "<html><body><h2>Test Email</h2><p>This is a test email to verify your SMTP settings are configured correctly.</p></body></html>"
        )

        if send_success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': f'Connection OK, but send failed: {send_error}'})
    else:
        return jsonify({'success': False, 'error': message})


# =============================================================================
# Reminder Processing
# =============================================================================

@bp.route('/reminders/process', methods=['POST'])
def process_reminders():
    """Process due reminders and send notifications.

    This endpoint can be called by a cron job, Docker health check, or
    the built-in background scheduler. No authentication required but
    protected by a secret token if configured.

    Can also be triggered manually by an admin from the UI.
    """
    # Check for API key or admin session
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    api_user = User.get_by_api_key(token) if token else None

    if not (api_user or (current_user and current_user.is_authenticated and current_user.is_admin)):
        # Also allow internal calls with the app secret
        internal_token = request.headers.get('X-Internal-Token')
        if internal_token != current_app.config.get('SECRET_KEY'):
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    from app.services.reminder_processor import process_due_reminders
    stats = process_due_reminders()

    return jsonify({
        'success': True,
        'stats': stats
    })


# =============================================================================
# File Serving
# =============================================================================

@bp.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files (public for branding assets like logo)"""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


# =============================================================================
# Internal API (for web UI, session-authenticated)
# =============================================================================

@bp.route('/vehicles/<int:vehicle_id>/stats')
@login_required
def vehicle_stats(vehicle_id):
    """Get statistics for a specific vehicle (for charts)"""
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in current_user.get_all_vehicles():
        return jsonify({'error': 'Access denied'}), 403

    logs = vehicle.fuel_logs.filter_by(is_full_tank=True).order_by(FuelLog.date, FuelLog.odometer).all()
    consumption_data = []
    for log in logs:
        consumption = log.get_consumption(current_user.consumption_unit, current_user.volume_unit)
        if consumption:
            consumption_data.append({
                'date': log.date.isoformat(),
                'consumption': round(consumption, 2),
                'odometer': log.odometer,
                # Each fuel gets its own series in the trend chart; mixing a
                # diesel's AdBlue refills into its diesel line would be
                # nonsense (#319).
                'fuel_type': log.effective_fuel_type,
                'fuel_type_label': str(fuel_type_label(log.effective_fuel_type)),
            })

    expenses = vehicle.expenses.all()
    category_totals = {}
    for exp in expenses:
        if exp.category in category_totals:
            category_totals[exp.category] += exp.cost
        else:
            category_totals[exp.category] = exp.cost

    # Price paid per unit over time, from every log that recorded one (#249)
    price_logs = vehicle.fuel_logs.filter(
        FuelLog.price_per_unit.isnot(None)
    ).order_by(FuelLog.date, FuelLog.odometer).all()
    price_data = [
        {'date': log.date.isoformat(), 'price': round(log.price_per_unit, 3)}
        for log in price_logs
    ]

    return jsonify({
        'consumption': consumption_data,
        'price_per_unit': price_data,
        'expenses_by_category': category_totals,
        'total_fuel_cost': vehicle.get_total_fuel_cost(),
        'total_expense_cost': vehicle.get_total_expense_cost(),
        'total_distance': vehicle.get_total_distance(vehicle.get_effective_odometer_unit()),
        'avg_consumption': vehicle.get_average_consumption(current_user.consumption_unit, current_user.volume_unit)
    })


@bp.route('/vehicles/<int:vehicle_id>/last-odometer')
@login_required
def last_odometer(vehicle_id):
    """Get the last recorded odometer reading for a vehicle"""
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in current_user.get_all_vehicles():
        return jsonify({'error': 'Access denied'}), 403

    return jsonify({'odometer': vehicle.get_last_odometer()})


# =============================================================================
# Public API v1 - Vehicles
# =============================================================================

@bp.route('/v1/vehicles', methods=['GET'])
@api_auth_required
def api_list_vehicles():
    """
    List all vehicles

    Returns all vehicles the authenticated user has access to.
    """
    user = get_api_user()
    vehicles = user.get_all_vehicles()
    return jsonify({
        'vehicles': [v.to_dict() for v in vehicles],
        'count': len(vehicles)
    })


@bp.route('/v1/vehicles/<int:vehicle_id>', methods=['GET'])
@api_auth_required
def api_get_vehicle(vehicle_id):
    """
    Get a specific vehicle

    Returns detailed information about a single vehicle.
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    return jsonify(vehicle.to_dict())


@bp.route('/v1/vehicles', methods=['POST'])
@api_auth_required
def api_create_vehicle():
    """
    Create a new vehicle

    Required fields: name, vehicle_type
    Optional fields: make, model, year, registration, vin, fuel_type, tank_capacity
    """
    user = get_api_user()
    data = request.get_json()

    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if not data.get('name'):
        return jsonify({'error': 'name is required', 'code': 'validation_error'}), 400

    if not data.get('vehicle_type'):
        return jsonify({'error': 'vehicle_type is required', 'code': 'validation_error'}), 400

    if data['vehicle_type'] not in ['car', 'van', 'motorbike', 'scooter']:
        return jsonify({'error': 'vehicle_type must be one of: car, van, motorbike, scooter', 'code': 'validation_error'}), 400

    vehicle = Vehicle(
        owner_id=user.id,
        name=data['name'],
        vehicle_type=data['vehicle_type'],
        make=data.get('make'),
        model=data.get('model'),
        year=data.get('year'),
        registration=data.get('registration'),
        vin=data.get('vin'),
        fuel_type=data.get('fuel_type', 'petrol'),
        tank_capacity=data.get('tank_capacity')
    )

    db.session.add(vehicle)
    db.session.commit()

    return jsonify(vehicle.to_dict()), 201


@bp.route('/v1/vehicles/<int:vehicle_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_vehicle(vehicle_id):
    """
    Update a vehicle

    All fields are optional. Only provided fields will be updated.
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle.owner_id != user.id:
        return jsonify({'error': 'Only the owner can update this vehicle', 'code': 'forbidden'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if 'name' in data:
        vehicle.name = data['name']
    if 'vehicle_type' in data:
        if data['vehicle_type'] not in ['car', 'van', 'motorbike', 'scooter']:
            return jsonify({'error': 'vehicle_type must be one of: car, van, motorbike, scooter', 'code': 'validation_error'}), 400
        vehicle.vehicle_type = data['vehicle_type']
    if 'make' in data:
        vehicle.make = data['make']
    if 'model' in data:
        vehicle.model = data['model']
    if 'year' in data:
        vehicle.year = data['year']
    if 'registration' in data:
        vehicle.registration = data['registration']
    if 'vin' in data:
        vehicle.vin = data['vin']
    if 'fuel_type' in data:
        vehicle.fuel_type = data['fuel_type']
    if 'tank_capacity' in data:
        vehicle.tank_capacity = data['tank_capacity']
    if 'is_active' in data:
        vehicle.is_active = data['is_active']

    db.session.commit()
    return jsonify(vehicle.to_dict())


@bp.route('/v1/vehicles/<int:vehicle_id>', methods=['DELETE'])
@api_auth_required
def api_delete_vehicle(vehicle_id):
    """
    Delete a vehicle

    This will also delete all associated fuel logs and expenses.
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle.owner_id != user.id:
        return jsonify({'error': 'Only the owner can delete this vehicle', 'code': 'forbidden'}), 403

    db.session.delete(vehicle)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Vehicle deleted'})


# =============================================================================
# Public API v1 - Fuel Logs
# =============================================================================

@bp.route('/v1/vehicles/<int:vehicle_id>/fuel', methods=['GET'])
@api_auth_required
def api_list_fuel_logs(vehicle_id):
    """
    List fuel logs for a vehicle

    Query parameters:
    - limit: Maximum number of results (default: 100)
    - offset: Number of results to skip (default: 0)
    - sort: Sort order, 'asc' or 'desc' by date (default: desc)
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    limit = min(request.args.get('limit', 100, type=int), 500)
    offset = request.args.get('offset', 0, type=int)
    sort = request.args.get('sort', 'desc')

    query = vehicle.fuel_logs
    if sort == 'asc':
        query = query.order_by(FuelLog.date.asc(), FuelLog.odometer.asc())
    else:
        query = query.order_by(FuelLog.date.desc(), FuelLog.odometer.desc())

    total = query.count()
    logs = query.offset(offset).limit(limit).all()

    return jsonify({
        'fuel_logs': [log.to_dict() for log in logs],
        'count': len(logs),
        'total': total,
        'limit': limit,
        'offset': offset
    })


@bp.route('/v1/vehicles/<int:vehicle_id>/fuel', methods=['POST'])
@api_auth_required
def api_create_fuel_log(vehicle_id):
    """
    Create a fuel log

    Required fields: date, odometer
    Optional fields: volume, price_per_unit, total_cost, sales_tax, fuel_type,
    fuel_distance, is_full_tank, is_missed, station, notes
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if not data.get('date'):
        return jsonify({'error': 'date is required (YYYY-MM-DD)', 'code': 'validation_error'}), 400

    if not data.get('odometer'):
        return jsonify({'error': 'odometer is required', 'code': 'validation_error'}), 400

    try:
        date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    log = FuelLog(
        vehicle_id=vehicle_id,
        user_id=user.id,
        date=date,
        odometer=parse_decimal(data['odometer']),
        volume=parse_decimal(data['volume']) if data.get('volume') else None,
        price_per_unit=parse_decimal(data['price_per_unit']) if data.get('price_per_unit') else None,
        total_cost=parse_decimal(data['total_cost']) if data.get('total_cost') else None,
        sales_tax=parse_decimal(data['sales_tax']) if data.get('sales_tax') else None,
        fuel_type=data.get('fuel_type') or None,
        fuel_distance=parse_decimal(data['fuel_distance']) if data.get('fuel_distance') else None,
        is_full_tank=data.get('is_full_tank', True),
        is_missed=data.get('is_missed', False),
        station=data.get('station'),
        notes=data.get('notes')
    )

    # Auto-calculate total cost if not provided
    if log.volume and log.price_per_unit and not log.total_cost:
        log.total_cost = round(log.volume * log.price_per_unit, 2)

    db.session.add(log)
    db.session.commit()

    return jsonify(log.to_dict()), 201


@bp.route('/v1/fuel/<int:log_id>', methods=['GET'])
@api_auth_required
def api_get_fuel_log(log_id):
    """Get a specific fuel log"""
    user = get_api_user()
    log = db.get_or_404(FuelLog, log_id)

    if log.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Fuel log not found or access denied', 'code': 'not_found'}), 404

    return jsonify(log.to_dict())


@bp.route('/v1/fuel/<int:log_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_fuel_log(log_id):
    """Update a fuel log"""
    user = get_api_user()
    log = db.get_or_404(FuelLog, log_id)

    if log.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Fuel log not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if 'date' in data:
        try:
            log.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    if 'odometer' in data:
        log.odometer = parse_decimal(data['odometer'])
    if 'volume' in data:
        log.volume = parse_decimal(data['volume']) if data['volume'] else None
    if 'price_per_unit' in data:
        log.price_per_unit = parse_decimal(data['price_per_unit']) if data['price_per_unit'] else None
    if 'total_cost' in data:
        log.total_cost = parse_decimal(data['total_cost']) if data['total_cost'] else None
    if 'sales_tax' in data:
        log.sales_tax = parse_decimal(data['sales_tax']) if data['sales_tax'] else None
    if 'fuel_type' in data:
        log.fuel_type = data['fuel_type'] or None
    if 'fuel_distance' in data:
        log.fuel_distance = parse_decimal(data['fuel_distance']) if data['fuel_distance'] else None
    if 'is_full_tank' in data:
        log.is_full_tank = data['is_full_tank']
    if 'is_missed' in data:
        log.is_missed = data['is_missed']
    if 'station' in data:
        log.station = data['station']
    if 'notes' in data:
        log.notes = data['notes']

    db.session.commit()
    return jsonify(log.to_dict())


@bp.route('/v1/fuel/<int:log_id>', methods=['DELETE'])
@api_auth_required
def api_delete_fuel_log(log_id):
    """Delete a fuel log"""
    user = get_api_user()
    log = db.get_or_404(FuelLog, log_id)

    if log.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Fuel log not found or access denied', 'code': 'not_found'}), 404

    db.session.delete(log)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Fuel log deleted'})


# =============================================================================
# Public API v1 - Expenses
# =============================================================================

@bp.route('/v1/vehicles/<int:vehicle_id>/expenses', methods=['GET'])
@api_auth_required
def api_list_expenses(vehicle_id):
    """
    List expenses for a vehicle

    Query parameters:
    - limit: Maximum number of results (default: 100)
    - offset: Number of results to skip (default: 0)
    - category: Filter by category
    - sort: Sort order, 'asc' or 'desc' by date (default: desc)
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    limit = min(request.args.get('limit', 100, type=int), 500)
    offset = request.args.get('offset', 0, type=int)
    category = request.args.get('category')
    sort = request.args.get('sort', 'desc')

    query = vehicle.expenses
    if category:
        query = query.filter_by(category=category)

    if sort == 'asc':
        query = query.order_by(Expense.date.asc())
    else:
        query = query.order_by(Expense.date.desc())

    total = query.count()
    expenses = query.offset(offset).limit(limit).all()

    return jsonify({
        'expenses': [exp.to_dict() for exp in expenses],
        'count': len(expenses),
        'total': total,
        'limit': limit,
        'offset': offset
    })


@bp.route('/v1/vehicles/<int:vehicle_id>/expenses', methods=['POST'])
@api_auth_required
def api_create_expense(vehicle_id):
    """
    Create an expense

    Required fields: date, category, description, cost
    Optional fields: odometer, vendor, notes
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    required = ['date', 'category', 'description', 'cost']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'{field} is required', 'code': 'validation_error'}), 400

    valid_categories = [c[0] for c in EXPENSE_CATEGORIES]
    if data['category'] not in valid_categories:
        return jsonify({
            'error': f'category must be one of: {", ".join(valid_categories)}',
            'code': 'validation_error'
        }), 400

    try:
        date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    expense = Expense(
        vehicle_id=vehicle_id,
        user_id=user.id,
        date=date,
        category=data['category'],
        description=data['description'],
        cost=parse_decimal(data['cost']),
        odometer=parse_decimal(data['odometer']) if data.get('odometer') else None,
        vendor=data.get('vendor'),
        notes=data.get('notes')
    )

    db.session.add(expense)
    db.session.commit()

    return jsonify(expense.to_dict()), 201


@bp.route('/v1/expenses/<int:expense_id>', methods=['GET'])
@api_auth_required
def api_get_expense(expense_id):
    """Get a specific expense"""
    user = get_api_user()
    expense = db.get_or_404(Expense, expense_id)

    if expense.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Expense not found or access denied', 'code': 'not_found'}), 404

    return jsonify(expense.to_dict())


@bp.route('/v1/expenses/<int:expense_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_expense(expense_id):
    """Update an expense"""
    user = get_api_user()
    expense = db.get_or_404(Expense, expense_id)

    if expense.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Expense not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if 'date' in data:
        try:
            expense.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    if 'category' in data:
        valid_categories = [c[0] for c in EXPENSE_CATEGORIES]
        if data['category'] not in valid_categories:
            return jsonify({
                'error': f'category must be one of: {", ".join(valid_categories)}',
                'code': 'validation_error'
            }), 400
        expense.category = data['category']

    if 'description' in data:
        expense.description = data['description']
    if 'cost' in data:
        expense.cost = parse_decimal(data['cost'])
    if 'odometer' in data:
        expense.odometer = parse_decimal(data['odometer']) if data['odometer'] else None
    if 'vendor' in data:
        expense.vendor = data['vendor']
    if 'notes' in data:
        expense.notes = data['notes']

    db.session.commit()
    return jsonify(expense.to_dict())


@bp.route('/v1/expenses/<int:expense_id>', methods=['DELETE'])
@api_auth_required
def api_delete_expense(expense_id):
    """Delete an expense"""
    user = get_api_user()
    expense = db.get_or_404(Expense, expense_id)

    if expense.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Expense not found or access denied', 'code': 'not_found'}), 404

    db.session.delete(expense)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Expense deleted'})


# =============================================================================
# Public API v1 - Trips
# =============================================================================

def _parse_api_time(value):
    """Parse a time string from an API request.

    Accepts HH:MM (as the web forms submit) and HH:MM:SS (as ``to_dict``
    returns), so values can be round-tripped. Raises ValueError otherwise.
    """
    if not isinstance(value, str):
        raise ValueError(f'Invalid time format: {value}')
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError(f'Invalid time format: {value}')


@bp.route('/v1/vehicles/<int:vehicle_id>/trips', methods=['GET'])
@api_auth_required
def api_list_trips(vehicle_id):
    """
    List trips for a vehicle

    Query parameters:
    - limit: Maximum number of results (default: 100)
    - offset: Number of results to skip (default: 0)
    - purpose: Filter by purpose
    - sort: Sort order, 'asc' or 'desc' by date (default: desc)
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    limit = min(request.args.get('limit', 100, type=int), 500)
    offset = request.args.get('offset', 0, type=int)
    purpose = request.args.get('purpose')
    sort = request.args.get('sort', 'desc')

    query = vehicle.trips
    if purpose:
        query = query.filter_by(purpose=purpose)

    if sort == 'asc':
        query = query.order_by(Trip.date.asc(), Trip.id.asc())
    else:
        query = query.order_by(Trip.date.desc(), Trip.id.desc())

    total = query.count()
    trips = query.offset(offset).limit(limit).all()

    return jsonify({
        'trips': [trip.to_dict() for trip in trips],
        'count': len(trips),
        'total': total,
        'limit': limit,
        'offset': offset
    })


@bp.route('/v1/vehicles/<int:vehicle_id>/trips', methods=['POST'])
@api_auth_required
def api_create_trip(vehicle_id):
    """
    Create a trip

    Required fields: date, start_odometer, purpose
    Optional fields: end_odometer, start_fuel_level, end_fuel_level, description,
    start_location, end_location, notes
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    required = ['date', 'start_odometer', 'purpose']
    for field in required:
        if data.get(field) is None or data.get(field) == '':
            return jsonify({'error': f'{field} is required', 'code': 'validation_error'}), 400

    valid_purposes = [p[0] for p in TRIP_PURPOSES]
    if data['purpose'] not in valid_purposes:
        return jsonify({
            'error': f'purpose must be one of: {", ".join(valid_purposes)}',
            'code': 'validation_error'
        }), 400

    try:
        date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    try:
        start_odometer = parse_decimal(data['start_odometer'])
        end_odometer = parse_decimal(data.get('end_odometer'))
    except ValueError:
        return jsonify({'error': 'Odometer values must be numeric', 'code': 'validation_error'}), 400

    try:
        start_fuel_level = parse_fuel_level(data.get('start_fuel_level'))
        end_fuel_level = parse_fuel_level(data.get('end_fuel_level'))
    except (ValueError, TypeError):
        return jsonify({
            'error': 'Fuel levels must be a percentage between 0 and 100',
            'code': 'validation_error'
        }), 400

    trip = Trip(
        vehicle_id=vehicle_id,
        user_id=user.id,
        date=date,
        start_odometer=start_odometer,
        end_odometer=end_odometer,
        start_fuel_level=start_fuel_level,
        end_fuel_level=end_fuel_level,
        purpose=data['purpose'],
        description=data.get('description'),
        start_location=data.get('start_location'),
        end_location=data.get('end_location'),
        notes=data.get('notes')
    )

    db.session.add(trip)
    db.session.commit()

    return jsonify(trip.to_dict()), 201


@bp.route('/v1/trips/<int:trip_id>', methods=['GET'])
@api_auth_required
def api_get_trip(trip_id):
    """Get a specific trip"""
    user = get_api_user()
    trip = db.get_or_404(Trip, trip_id)

    if trip.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Trip not found or access denied', 'code': 'not_found'}), 404

    return jsonify(trip.to_dict())


@bp.route('/v1/trips/<int:trip_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_trip(trip_id):
    """Update a trip"""
    user = get_api_user()
    trip = db.get_or_404(Trip, trip_id)

    if trip.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Trip not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if 'date' in data:
        try:
            trip.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    if 'purpose' in data:
        valid_purposes = [p[0] for p in TRIP_PURPOSES]
        if data['purpose'] not in valid_purposes:
            return jsonify({
                'error': f'purpose must be one of: {", ".join(valid_purposes)}',
                'code': 'validation_error'
            }), 400
        trip.purpose = data['purpose']

    try:
        if 'start_odometer' in data:
            start_odometer = parse_decimal(data['start_odometer'])
            if start_odometer is None:
                return jsonify({'error': 'start_odometer is required', 'code': 'validation_error'}), 400
            trip.start_odometer = start_odometer
        if 'end_odometer' in data:
            trip.end_odometer = parse_decimal(data['end_odometer'])
    except ValueError:
        return jsonify({'error': 'Odometer values must be numeric', 'code': 'validation_error'}), 400

    try:
        if 'start_fuel_level' in data:
            trip.start_fuel_level = parse_fuel_level(data['start_fuel_level'])
        if 'end_fuel_level' in data:
            trip.end_fuel_level = parse_fuel_level(data['end_fuel_level'])
    except (ValueError, TypeError):
        db.session.rollback()
        return jsonify({
            'error': 'Fuel levels must be a percentage between 0 and 100',
            'code': 'validation_error'
        }), 400

    if 'description' in data:
        trip.description = data['description']
    if 'start_location' in data:
        trip.start_location = data['start_location']
    if 'end_location' in data:
        trip.end_location = data['end_location']
    if 'notes' in data:
        trip.notes = data['notes']

    db.session.commit()
    return jsonify(trip.to_dict())


@bp.route('/v1/trips/<int:trip_id>', methods=['DELETE'])
@api_auth_required
def api_delete_trip(trip_id):
    """Delete a trip"""
    user = get_api_user()
    trip = db.get_or_404(Trip, trip_id)

    if trip.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Trip not found or access denied', 'code': 'not_found'}), 404

    db.session.delete(trip)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Trip deleted'})


# =============================================================================
# Public API v1 - Charging Sessions
# =============================================================================

@bp.route('/v1/vehicles/<int:vehicle_id>/charging', methods=['GET'])
@api_auth_required
def api_list_charging_sessions(vehicle_id):
    """
    List charging sessions for a vehicle

    Query parameters:
    - limit: Maximum number of results (default: 100)
    - offset: Number of results to skip (default: 0)
    - charger_type: Filter by charger type
    - sort: Sort order, 'asc' or 'desc' by date (default: desc)
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    limit = min(request.args.get('limit', 100, type=int), 500)
    offset = request.args.get('offset', 0, type=int)
    charger_type = request.args.get('charger_type')
    sort = request.args.get('sort', 'desc')

    query = vehicle.charging_sessions
    if charger_type:
        query = query.filter_by(charger_type=charger_type)

    if sort == 'asc':
        query = query.order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
    else:
        query = query.order_by(ChargingSession.date.desc(), ChargingSession.id.desc())

    total = query.count()
    sessions = query.offset(offset).limit(limit).all()

    return jsonify({
        'charging_sessions': [s.to_dict() for s in sessions],
        'count': len(sessions),
        'total': total,
        'limit': limit,
        'offset': offset
    })


@bp.route('/v1/vehicles/<int:vehicle_id>/charging', methods=['POST'])
@api_auth_required
def api_create_charging_session(vehicle_id):
    """
    Create a charging session

    Required fields: date
    Optional fields: start_time, end_time, odometer, kwh_added, start_soc, end_soc,
    cost_per_kwh, total_cost, charger_type, location, network, notes
    """
    user = get_api_user()
    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if not data.get('date'):
        return jsonify({'error': 'date is required (YYYY-MM-DD)', 'code': 'validation_error'}), 400

    try:
        date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    if data.get('charger_type'):
        valid_charger_types = [c[0] for c in CHARGER_TYPES]
        if data['charger_type'] not in valid_charger_types:
            return jsonify({
                'error': f'charger_type must be one of: {", ".join(valid_charger_types)}',
                'code': 'validation_error'
            }), 400

    try:
        start_time = _parse_api_time(data['start_time']) if data.get('start_time') else None
        end_time = _parse_api_time(data['end_time']) if data.get('end_time') else None
    except ValueError:
        return jsonify({'error': 'Invalid time format. Use HH:MM', 'code': 'validation_error'}), 400

    try:
        session = ChargingSession(
            vehicle_id=vehicle_id,
            user_id=user.id,
            date=date,
            start_time=start_time,
            end_time=end_time,
            odometer=parse_decimal(data.get('odometer')),
            kwh_added=parse_decimal(data.get('kwh_added')),
            start_soc=int(data['start_soc']) if data.get('start_soc') is not None else None,
            end_soc=int(data['end_soc']) if data.get('end_soc') is not None else None,
            cost_per_kwh=parse_decimal(data.get('cost_per_kwh')),
            total_cost=parse_decimal(data.get('total_cost')),
            charger_type=data.get('charger_type'),
            location=data.get('location'),
            network=data.get('network'),
            notes=data.get('notes')
        )
    except (TypeError, ValueError):
        return jsonify({'error': 'Numeric fields must be valid numbers', 'code': 'validation_error'}), 400

    # Auto-calculate total cost if not provided
    if session.kwh_added and session.cost_per_kwh and not session.total_cost:
        session.total_cost = round(session.kwh_added * session.cost_per_kwh, 2)

    db.session.add(session)
    db.session.commit()

    return jsonify(session.to_dict()), 201


@bp.route('/v1/charging/<int:session_id>', methods=['GET'])
@api_auth_required
def api_get_charging_session(session_id):
    """Get a specific charging session"""
    user = get_api_user()
    charge = db.get_or_404(ChargingSession, session_id)

    if charge.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Charging session not found or access denied', 'code': 'not_found'}), 404

    return jsonify(charge.to_dict())


@bp.route('/v1/charging/<int:session_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_charging_session(session_id):
    """Update a charging session"""
    user = get_api_user()
    charge = db.get_or_404(ChargingSession, session_id)

    if charge.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Charging session not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if 'date' in data:
        try:
            charge.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    if 'charger_type' in data:
        if data['charger_type']:
            valid_charger_types = [c[0] for c in CHARGER_TYPES]
            if data['charger_type'] not in valid_charger_types:
                return jsonify({
                    'error': f'charger_type must be one of: {", ".join(valid_charger_types)}',
                    'code': 'validation_error'
                }), 400
        charge.charger_type = data['charger_type']

    try:
        for field in ('start_time', 'end_time'):
            if field in data:
                setattr(charge, field, _parse_api_time(data[field]) if data[field] else None)
    except ValueError:
        return jsonify({'error': 'Invalid time format. Use HH:MM', 'code': 'validation_error'}), 400

    try:
        for field in ('odometer', 'kwh_added', 'cost_per_kwh', 'total_cost'):
            if field in data:
                setattr(charge, field, parse_decimal(data[field]))
        for field in ('start_soc', 'end_soc'):
            if field in data:
                setattr(charge, field, int(data[field]) if data[field] is not None else None)
    except (TypeError, ValueError):
        return jsonify({'error': 'Numeric fields must be valid numbers', 'code': 'validation_error'}), 400

    if 'location' in data:
        charge.location = data['location']
    if 'network' in data:
        charge.network = data['network']
    if 'notes' in data:
        charge.notes = data['notes']

    db.session.commit()
    return jsonify(charge.to_dict())


@bp.route('/v1/charging/<int:session_id>', methods=['DELETE'])
@api_auth_required
def api_delete_charging_session(session_id):
    """Delete a charging session"""
    user = get_api_user()
    charge = db.get_or_404(ChargingSession, session_id)

    if charge.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Charging session not found or access denied', 'code': 'not_found'}), 404

    db.session.delete(charge)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Charging session deleted'})


# =============================================================================
# Public API v1 - Metadata
# =============================================================================

@bp.route('/v1/categories', methods=['GET'])
@api_auth_required
def api_list_categories():
    """List all expense categories"""
    return jsonify({
        'categories': [{'id': c[0], 'name': c[1]} for c in EXPENSE_CATEGORIES]
    })


@bp.route('/v1/trip-purposes', methods=['GET'])
@api_auth_required
def api_list_trip_purposes():
    """List all trip purposes"""
    return jsonify({
        'purposes': [{'id': p[0], 'name': p[1]} for p in TRIP_PURPOSES]
    })


@bp.route('/v1/charger-types', methods=['GET'])
@api_auth_required
def api_list_charger_types():
    """List all charger types"""
    return jsonify({
        'charger_types': [{'id': c[0], 'name': c[1]} for c in CHARGER_TYPES]
    })


# =============================================================================
# DVLA Integration (UK Vehicles)
# =============================================================================

@bp.route('/dvla/lookup', methods=['POST'])
@login_required
def dvla_lookup():
    """
    Look up vehicle information from DVLA (UK vehicles only)

    Expects JSON body with 'registration' field
    """
    from app.services.dvla import DVLAService

    if not DVLAService.is_configured():
        return jsonify({'success': False, 'error': 'DVLA integration not configured'}), 400

    data = request.get_json()
    if not data or not data.get('registration'):
        return jsonify({'success': False, 'error': 'Registration number required'}), 400

    success, result = DVLAService.lookup_vehicle(data['registration'])

    if success:
        # Convert dates to strings for JSON
        if result.get('mot_expiry_date'):
            result['mot_expiry_date'] = result['mot_expiry_date'].isoformat()
        if result.get('tax_due_date'):
            result['tax_due_date'] = result['tax_due_date'].isoformat()
        if result.get('date_of_last_v5c_issued'):
            result['date_of_last_v5c_issued'] = result['date_of_last_v5c_issued'].isoformat()
        return jsonify({'success': True, 'vehicle': result})
    else:
        return jsonify({'success': False, 'error': result}), 400


@bp.route('/dvla/test', methods=['POST'])
@login_required
def dvla_test_key():
    """Test DVLA API key (admin only)"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    from app.services.dvla import DVLAService

    api_key = request.form.get('dvla_api_key')
    if not api_key:
        return jsonify({'success': False, 'error': 'API key required'}), 400

    success, message = DVLAService.test_api_key(api_key)
    return jsonify({'success': success, 'message': message})


@bp.route('/dvla/status')
@login_required
def dvla_status():
    """Check if DVLA integration is available"""
    from app.services.dvla import DVLAService
    return jsonify({'configured': DVLAService.is_configured()})


@bp.route('/vehicles/<int:vehicle_id>/dvla-refresh', methods=['POST'])
@login_required
def refresh_vehicle_dvla(vehicle_id):
    """
    Refresh vehicle MOT and tax status from DVLA

    Updates the vehicle's MOT and tax status fields if the vehicle has a UK registration
    """
    from app.services.dvla import DVLAService

    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in current_user.get_all_vehicles():
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    if not vehicle.registration:
        return jsonify({'success': False, 'error': 'Vehicle has no registration number'}), 400

    if not DVLAService.is_configured():
        return jsonify({'success': False, 'error': 'DVLA integration not configured'}), 400

    success, result = DVLAService.lookup_vehicle(vehicle.registration)

    if success:
        # Update vehicle with DVLA data
        vehicle.mot_status = result.get('mot_status')
        vehicle.mot_expiry = result.get('mot_expiry_date')
        vehicle.tax_status = result.get('tax_status')
        vehicle.tax_due = result.get('tax_due_date')
        vehicle.dvla_colour = result.get('colour')
        vehicle.dvla_last_updated = utcnow()

        # Optionally update make if empty
        if not vehicle.make and result.get('make'):
            vehicle.make = result['make']

        # Optionally update year if empty
        if not vehicle.year and result.get('year_of_manufacture'):
            vehicle.year = result['year_of_manufacture']

        db.session.commit()

        return jsonify({
            'success': True,
            'mot_status': vehicle.mot_status,
            'mot_expiry': vehicle.mot_expiry.isoformat() if vehicle.mot_expiry else None,
            'tax_status': vehicle.tax_status,
            'tax_due': vehicle.tax_due.isoformat() if vehicle.tax_due else None,
        })
    else:
        return jsonify({'success': False, 'error': result}), 400


# =============================================================================
# Tessie Integration (Tesla vehicles via Tessie API)
# =============================================================================

@bp.route('/tessie/test', methods=['POST'])
@login_required
def tessie_test_token():
    """Test Tessie API token (admin only)"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    from app.services.tessie import TessieService

    api_token = request.form.get('tessie_api_token')
    if not api_token:
        return jsonify({'success': False, 'error': 'API token required'}), 400

    success, message = TessieService.test_api_token(api_token)
    return jsonify({'success': success, 'message': message})


@bp.route('/tessie/status')
@login_required
def tessie_status():
    """Check if Tessie integration is available"""
    from app.services.tessie import TessieService
    return jsonify({'configured': TessieService.is_configured()})


@bp.route('/tessie/vehicles')
@login_required
def tessie_vehicles():
    """Get list of vehicles from Tessie account (for linking)"""
    from app.services.tessie import TessieService

    if not TessieService.is_configured():
        return jsonify({'success': False, 'error': 'Tessie not configured'}), 400

    success, result = TessieService.get_vehicles()
    if success:
        return jsonify({'success': True, 'vehicles': result})
    else:
        return jsonify({'success': False, 'error': result}), 400


@bp.route('/vehicles/<int:vehicle_id>/tessie-refresh', methods=['POST'])
@login_required
def refresh_vehicle_tessie(vehicle_id):
    """
    Refresh vehicle data from Tessie

    Updates the vehicle's odometer, battery level, and range from Tessie
    """
    from app.services.tessie import TessieService

    vehicle = db.get_or_404(Vehicle, vehicle_id)

    if vehicle not in current_user.get_all_vehicles():
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    if not vehicle.tessie_vin:
        return jsonify({'success': False, 'error': 'Vehicle not linked to Tessie'}), 400

    if not vehicle.tessie_enabled:
        return jsonify({'success': False, 'error': 'Tessie not enabled for this vehicle'}), 400

    if not TessieService.is_configured():
        return jsonify({'success': False, 'error': 'Tessie integration not configured'}), 400

    success, result = TessieService.get_vehicle_state(vehicle.tessie_vin)

    if success:
        vehicle.tessie_last_odometer = result['odometer_km']
        vehicle.tessie_battery_level = result.get('battery_level')
        vehicle.tessie_battery_range = result.get('battery_range_km')
        vehicle.tessie_last_updated = utcnow()

        db.session.commit()

        return jsonify({
            'success': True,
            'odometer': vehicle.tessie_last_odometer,
            'battery_level': vehicle.tessie_battery_level,
            'battery_range': vehicle.tessie_battery_range,
            'updated': vehicle.tessie_last_updated.isoformat()
        })
    else:
        return jsonify({'success': False, 'error': result}), 400


@bp.route('/vehicles/<int:vehicle_id>/tessie-import-charges', methods=['POST'])
@login_required
def import_tessie_charges(vehicle_id):
    """
    Import charging history from Tessie for a vehicle

    Creates ChargingSession records for charges not already imported.
    """
    from app.models import ChargingSession

    vehicle = db.get_or_404(Vehicle, vehicle_id)

    # Check access
    if vehicle not in current_user.get_all_vehicles():
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    # Check Tessie is configured for this vehicle
    if not vehicle.tessie_vin:
        return jsonify({'success': False, 'error': 'Vehicle not linked to Tessie'}), 400

    if not TessieService.is_configured():
        return jsonify({'success': False, 'error': 'Tessie integration not configured'}), 400

    # Fetch charges from Tessie
    success, result = TessieService.get_charges(vehicle.tessie_vin)

    if not success:
        return jsonify({'success': False, 'error': result}), 400

    # Import charges that haven't been imported yet
    imported_count = 0
    skipped_count = 0

    for charge in result:
        tessie_id = str(charge.get('tessie_id'))

        # Check if already imported
        existing = ChargingSession.query.filter_by(tessie_charge_id=tessie_id).first()
        if existing:
            skipped_count += 1
            continue

        # Determine charger type
        charger_type = 'tesla' if charge.get('is_supercharger') else 'level2'

        # Create charging session
        session = ChargingSession(
            vehicle_id=vehicle.id,
            user_id=current_user.id,
            date=charge.get('date'),
            start_time=charge.get('start_time'),
            end_time=charge.get('end_time'),
            odometer=charge.get('odometer_km'),  # Stored in km
            kwh_added=charge.get('kwh_added'),
            start_soc=charge.get('start_soc'),
            end_soc=charge.get('end_soc'),
            total_cost=charge.get('cost'),
            charger_type=charger_type,
            location=charge.get('location'),
            tessie_charge_id=tessie_id
        )
        db.session.add(session)
        imported_count += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'imported': imported_count,
        'skipped': skipped_count,
        'message': f'Imported {imported_count} charging sessions ({skipped_count} already existed)'
    })


# =============================================================================
# Data Export (Web UI routes, session-authenticated)
# =============================================================================

@bp.route('/export/csv')
@login_required
def export_csv():
    """
    Export all user data as CSV files in a ZIP archive.
    Includes: vehicles.csv, fuel_logs.csv, expenses.csv
    """
    import zipfile

    # Create a BytesIO buffer for the ZIP file
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Export Vehicles
        vehicles_csv = io.StringIO()
        writer = csv.writer(vehicles_csv)
        writer.writerow([
            'id', 'name', 'vehicle_type', 'make', 'model', 'year',
            'registration', 'vin', 'fuel_type', 'tank_capacity',
            'odometer_unit', 'is_active', 'notes', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            writer.writerow([
                vehicle.id, vehicle.name, vehicle.vehicle_type,
                vehicle.make, vehicle.model, vehicle.year,
                vehicle.registration, vehicle.vin, vehicle.fuel_type,
                vehicle.tank_capacity,
                vehicle.get_reading_unit(),
                vehicle.is_active, vehicle.notes,
                vehicle.created_at.isoformat() if vehicle.created_at else ''
            ])
        zip_file.writestr('vehicles.csv', vehicles_csv.getvalue())

        # Export Vehicle Specs
        specs_csv = io.StringIO()
        writer = csv.writer(specs_csv)
        writer.writerow(['vehicle_id', 'vehicle_name', 'spec_type', 'label', 'value'])
        for vehicle in current_user.get_all_vehicles():
            for spec in vehicle.specs.all():
                writer.writerow([
                    vehicle.id, vehicle.name, spec.spec_type, spec.label, spec.value
                ])
        zip_file.writestr('vehicle_specs.csv', specs_csv.getvalue())

        # Export Fuel Logs
        fuel_csv = io.StringIO()
        writer = csv.writer(fuel_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'date', 'odometer', 'odometer_unit',
            'volume', 'price_per_unit', 'total_cost', 'sales_tax', 'fuel_type',
            'fuel_distance', 'is_full_tank', 'is_missed', 'station', 'notes',
            'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            # Each row states the unit its own vehicle meters in, so a
            # tractor's engine hours are never filed under a distance
            # heading alongside the cars (#324).
            odometer_unit = vehicle.get_reading_unit()
            for log in vehicle.fuel_logs.order_by(FuelLog.date.desc(), FuelLog.odometer.desc()).all():
                writer.writerow([
                    log.id, vehicle.id, vehicle.name, log.date.isoformat(),
                    log.odometer, odometer_unit,
                    log.volume, log.price_per_unit, log.total_cost, log.sales_tax,
                    log.fuel_type, log.fuel_distance,
                    log.is_full_tank, log.is_missed, log.station, log.notes,
                    log.created_at.isoformat() if log.created_at else ''
                ])
        zip_file.writestr('fuel_logs.csv', fuel_csv.getvalue())

        # Export Expenses
        expenses_csv = io.StringIO()
        writer = csv.writer(expenses_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'date', 'category',
            'description', 'cost', 'odometer', 'odometer_unit', 'vendor', 'notes', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            odometer_unit = vehicle.get_reading_unit()
            for expense in vehicle.expenses.order_by(Expense.date.desc()).all():
                writer.writerow([
                    expense.id, vehicle.id, vehicle.name, expense.date.isoformat(),
                    expense.category, expense.description, expense.cost,
                    expense.odometer, odometer_unit if expense.odometer is not None else '',
                    expense.vendor, expense.notes,
                    expense.created_at.isoformat() if expense.created_at else ''
                ])
        zip_file.writestr('expenses.csv', expenses_csv.getvalue())

        # Export Reminders
        reminders_csv = io.StringIO()
        writer = csv.writer(reminders_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'title', 'description', 'reminder_type',
            'due_date', 'recurrence', 'recurrence_interval', 'notify_days_before',
            'is_completed', 'completed_at', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            for reminder in vehicle.reminders.all():
                writer.writerow([
                    reminder.id, vehicle.id, vehicle.name, reminder.title,
                    reminder.description, reminder.reminder_type,
                    reminder.due_date.isoformat() if reminder.due_date else '',
                    reminder.recurrence, reminder.recurrence_interval, reminder.notify_days_before,
                    reminder.is_completed,
                    reminder.completed_at.isoformat() if reminder.completed_at else '',
                    reminder.created_at.isoformat() if reminder.created_at else ''
                ])
        zip_file.writestr('reminders.csv', reminders_csv.getvalue())

        # Export Maintenance Schedules
        maintenance_csv = io.StringIO()
        writer = csv.writer(maintenance_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'name', 'maintenance_type', 'description',
            'interval_miles', 'interval_km', 'interval_months',
            'last_performed_date', 'last_performed_odometer',
            'next_due_date', 'next_due_odometer', 'estimated_cost',
            'auto_remind', 'is_active', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            for schedule in vehicle.maintenance_schedules.all():
                writer.writerow([
                    schedule.id, vehicle.id, vehicle.name, schedule.name,
                    schedule.maintenance_type, schedule.description,
                    schedule.interval_miles, schedule.interval_km, schedule.interval_months,
                    schedule.last_performed_date.isoformat() if schedule.last_performed_date else '',
                    schedule.last_performed_odometer,
                    schedule.next_due_date.isoformat() if schedule.next_due_date else '',
                    schedule.next_due_odometer, schedule.estimated_cost,
                    schedule.auto_remind, schedule.is_active,
                    schedule.created_at.isoformat() if schedule.created_at else ''
                ])
        zip_file.writestr('maintenance_schedules.csv', maintenance_csv.getvalue())

        # Export Recurring Expenses
        recurring_csv = io.StringIO()
        writer = csv.writer(recurring_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'name', 'category', 'description',
            'amount', 'vendor', 'frequency', 'start_date', 'end_date',
            'last_generated', 'next_due', 'auto_create', 'is_active', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            for recurring in vehicle.recurring_expenses.all():
                writer.writerow([
                    recurring.id, vehicle.id, vehicle.name, recurring.name,
                    recurring.category, recurring.description, recurring.amount,
                    recurring.vendor, recurring.frequency,
                    recurring.start_date.isoformat() if recurring.start_date else '',
                    recurring.end_date.isoformat() if recurring.end_date else '',
                    recurring.last_generated.isoformat() if recurring.last_generated else '',
                    recurring.next_due.isoformat() if recurring.next_due else '',
                    recurring.auto_create, recurring.is_active,
                    recurring.created_at.isoformat() if recurring.created_at else ''
                ])
        zip_file.writestr('recurring_expenses.csv', recurring_csv.getvalue())

        # Export Documents (metadata only, not files)
        documents_csv = io.StringIO()
        writer = csv.writer(documents_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'title', 'document_type', 'description',
            'original_filename', 'file_type', 'file_size',
            'issue_date', 'expiry_date', 'reference_number', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            for doc in vehicle.documents.all():
                writer.writerow([
                    doc.id, vehicle.id, vehicle.name, doc.title,
                    doc.document_type, doc.description,
                    doc.original_filename, doc.file_type, doc.file_size,
                    doc.issue_date.isoformat() if doc.issue_date else '',
                    doc.expiry_date.isoformat() if doc.expiry_date else '',
                    doc.reference_number,
                    doc.created_at.isoformat() if doc.created_at else ''
                ])
        zip_file.writestr('documents.csv', documents_csv.getvalue())

        # Export Trips
        trips_csv = io.StringIO()
        writer = csv.writer(trips_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'date', 'start_odometer', 'end_odometer',
            'distance', 'distance_unit', 'start_fuel_level', 'end_fuel_level',
            'purpose', 'description', 'start_location', 'end_location',
            'notes', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            odometer_unit = vehicle.get_reading_unit()
            for trip in vehicle.trips.order_by(Trip.date.desc()).all():
                writer.writerow([
                    trip.id, vehicle.id, vehicle.name,
                    trip.date.isoformat() if trip.date else '',
                    trip.start_odometer, trip.end_odometer, trip.distance, odometer_unit,
                    trip.start_fuel_level, trip.end_fuel_level,
                    trip.purpose, trip.description,
                    trip.start_location, trip.end_location,
                    trip.notes,
                    trip.created_at.isoformat() if trip.created_at else ''
                ])
        zip_file.writestr('trips.csv', trips_csv.getvalue())

        # Export Charging Sessions
        charging_csv = io.StringIO()
        writer = csv.writer(charging_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'date', 'start_time', 'end_time',
            'odometer', 'kwh_added', 'start_soc', 'end_soc',
            'cost_per_kwh', 'total_cost', 'charger_type', 'location', 'network',
            'notes', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            for session in vehicle.charging_sessions.order_by(ChargingSession.date.desc()).all():
                writer.writerow([
                    session.id, vehicle.id, vehicle.name,
                    session.date.isoformat() if session.date else '',
                    session.start_time.isoformat() if session.start_time else '',
                    session.end_time.isoformat() if session.end_time else '',
                    session.odometer, session.kwh_added, session.start_soc, session.end_soc,
                    session.cost_per_kwh, session.total_cost,
                    session.charger_type, session.location, session.network,
                    session.notes,
                    session.created_at.isoformat() if session.created_at else ''
                ])
        zip_file.writestr('charging_sessions.csv', charging_csv.getvalue())

        # Export Vehicle Parts
        parts_csv = io.StringIO()
        writer = csv.writer(parts_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'name', 'part_type', 'specification',
            'quantity', 'unit', 'part_number', 'supplier_url', 'notes', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            for part in vehicle.parts.all():
                writer.writerow([
                    part.id, vehicle.id, vehicle.name, part.name,
                    part.part_type, part.specification,
                    part.quantity, part.unit, part.part_number,
                    part.supplier_url, part.notes,
                    part.created_at.isoformat() if part.created_at else ''
                ])
        zip_file.writestr('vehicle_parts.csv', parts_csv.getvalue())

        # Export Fuel Stations
        stations_csv = io.StringIO()
        writer = csv.writer(stations_csv)
        writer.writerow([
            'id', 'name', 'brand', 'address', 'city', 'postcode',
            'latitude', 'longitude', 'notes', 'is_favorite',
            'times_used', 'last_used', 'created_at'
        ])
        for station in current_user.fuel_stations.all():
            writer.writerow([
                station.id, station.name, station.brand,
                station.address, station.city, station.postcode,
                station.latitude, station.longitude,
                station.notes, station.is_favorite,
                station.times_used,
                station.last_used.isoformat() if station.last_used else '',
                station.created_at.isoformat() if station.created_at else ''
            ])
        zip_file.writestr('fuel_stations.csv', stations_csv.getvalue())

        # Export Fuel Price History
        prices_csv = io.StringIO()
        writer = csv.writer(prices_csv)
        writer.writerow([
            'id', 'station_id', 'station_name', 'date', 'fuel_type',
            'price_per_unit', 'created_at'
        ])
        for station in current_user.fuel_stations.all():
            for price in station.price_history.all():
                writer.writerow([
                    price.id, station.id, station.name,
                    price.date.isoformat() if price.date else '',
                    price.fuel_type, price.price_per_unit,
                    price.created_at.isoformat() if price.created_at else ''
                ])
        zip_file.writestr('fuel_price_history.csv', prices_csv.getvalue())

    zip_buffer.seek(0)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'may_export_{timestamp}.zip'

    return Response(
        zip_buffer.getvalue(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@bp.route('/export/json')
@login_required
def export_json():
    """
    Export all user data as a single JSON file.
    Complete backup including all vehicles and related data.
    """
    export_data = {
        'export_info': {
            'exported_at': utcnow().isoformat(),
            'username': current_user.username,
            'app_version': APP_VERSION
        },
        'user_preferences': {
            'language': current_user.language,
            'distance_unit': current_user.distance_unit,
            'volume_unit': current_user.volume_unit,
            'consumption_unit': current_user.consumption_unit,
            'currency': current_user.currency
        },
        'vehicles': [],
        'fuel_stations': [],
        'fuel_price_history': []
    }

    for vehicle in current_user.get_all_vehicles():
        vehicle_data = {
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
            'parts': []
        }

        # Add specifications
        for spec in vehicle.specs.all():
            vehicle_data['specifications'].append({
                'id': spec.id,
                'spec_type': spec.spec_type,
                'label': spec.label,
                'value': spec.value,
                'created_at': spec.created_at.isoformat() if spec.created_at else None
            })

        # Add fuel logs
        for log in vehicle.fuel_logs.order_by(FuelLog.date.desc(), FuelLog.odometer.desc()).all():
            vehicle_data['fuel_logs'].append({
                'id': log.id,
                'date': log.date.isoformat() if log.date else None,
                'odometer': log.odometer,
                'volume': log.volume,
                'price_per_unit': log.price_per_unit,
                'total_cost': log.total_cost,
                'sales_tax': log.sales_tax,
                'fuel_type': log.fuel_type,
                'fuel_distance': log.fuel_distance,
                'is_full_tank': log.is_full_tank,
                'is_missed': log.is_missed,
                'station': log.station,
                'notes': log.notes,
                'created_at': log.created_at.isoformat() if log.created_at else None
            })

        # Add expenses
        for expense in vehicle.expenses.order_by(Expense.date.desc()).all():
            vehicle_data['expenses'].append({
                'id': expense.id,
                'date': expense.date.isoformat() if expense.date else None,
                'category': expense.category,
                'description': expense.description,
                'cost': expense.cost,
                'odometer': expense.odometer,
                'vendor': expense.vendor,
                'notes': expense.notes,
                'created_at': expense.created_at.isoformat() if expense.created_at else None
            })

        # Add reminders
        for reminder in vehicle.reminders.all():
            vehicle_data['reminders'].append({
                'id': reminder.id,
                'title': reminder.title,
                'description': reminder.description,
                'reminder_type': reminder.reminder_type,
                'due_date': reminder.due_date.isoformat() if reminder.due_date else None,
                'recurrence': reminder.recurrence,
                'recurrence_interval': reminder.recurrence_interval,
                'notify_days_before': reminder.notify_days_before,
                'notification_sent': reminder.notification_sent,
                'is_completed': reminder.is_completed,
                'completed_at': reminder.completed_at.isoformat() if reminder.completed_at else None,
                'created_at': reminder.created_at.isoformat() if reminder.created_at else None
            })

        # Add maintenance schedules
        for schedule in vehicle.maintenance_schedules.all():
            vehicle_data['maintenance_schedules'].append({
                'id': schedule.id,
                'name': schedule.name,
                'maintenance_type': schedule.maintenance_type,
                'description': schedule.description,
                'interval_miles': schedule.interval_miles,
                'interval_km': schedule.interval_km,
                'interval_months': schedule.interval_months,
                'last_performed_date': schedule.last_performed_date.isoformat() if schedule.last_performed_date else None,
                'last_performed_odometer': schedule.last_performed_odometer,
                'next_due_date': schedule.next_due_date.isoformat() if schedule.next_due_date else None,
                'next_due_odometer': schedule.next_due_odometer,
                'estimated_cost': schedule.estimated_cost,
                'auto_remind': schedule.auto_remind,
                'remind_days_before': schedule.remind_days_before,
                'remind_miles_before': schedule.remind_miles_before,
                'is_active': schedule.is_active,
                'created_at': schedule.created_at.isoformat() if schedule.created_at else None
            })

        # Add recurring expenses
        for recurring in vehicle.recurring_expenses.all():
            vehicle_data['recurring_expenses'].append({
                'id': recurring.id,
                'name': recurring.name,
                'category': recurring.category,
                'description': recurring.description,
                'amount': recurring.amount,
                'vendor': recurring.vendor,
                'frequency': recurring.frequency,
                'start_date': recurring.start_date.isoformat() if recurring.start_date else None,
                'end_date': recurring.end_date.isoformat() if recurring.end_date else None,
                'last_generated': recurring.last_generated.isoformat() if recurring.last_generated else None,
                'next_due': recurring.next_due.isoformat() if recurring.next_due else None,
                'auto_create': recurring.auto_create,
                'notify_before_days': recurring.notify_before_days,
                'is_active': recurring.is_active,
                'created_at': recurring.created_at.isoformat() if recurring.created_at else None
            })

        # Add documents (metadata only, not files)
        for doc in vehicle.documents.all():
            vehicle_data['documents'].append({
                'id': doc.id,
                'title': doc.title,
                'document_type': doc.document_type,
                'description': doc.description,
                'original_filename': doc.original_filename,
                'file_type': doc.file_type,
                'file_size': doc.file_size,
                'issue_date': doc.issue_date.isoformat() if doc.issue_date else None,
                'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None,
                'reference_number': doc.reference_number,
                'remind_before_expiry': doc.remind_before_expiry,
                'remind_days': doc.remind_days,
                'created_at': doc.created_at.isoformat() if doc.created_at else None
            })

        # Add trips
        for trip in vehicle.trips.order_by(Trip.date.desc()).all():
            vehicle_data['trips'].append({
                'id': trip.id,
                'date': trip.date.isoformat() if trip.date else None,
                'start_odometer': trip.start_odometer,
                'end_odometer': trip.end_odometer,
                'distance': trip.distance,
                'start_fuel_level': trip.start_fuel_level,
                'end_fuel_level': trip.end_fuel_level,
                'purpose': trip.purpose,
                'description': trip.description,
                'start_location': trip.start_location,
                'end_location': trip.end_location,
                'notes': trip.notes,
                'created_at': trip.created_at.isoformat() if trip.created_at else None
            })

        # Add charging sessions
        for session in vehicle.charging_sessions.order_by(ChargingSession.date.desc()).all():
            vehicle_data['charging_sessions'].append({
                'id': session.id,
                'date': session.date.isoformat() if session.date else None,
                'start_time': session.start_time.isoformat() if session.start_time else None,
                'end_time': session.end_time.isoformat() if session.end_time else None,
                'odometer': session.odometer,
                'kwh_added': session.kwh_added,
                'start_soc': session.start_soc,
                'end_soc': session.end_soc,
                'cost_per_kwh': session.cost_per_kwh,
                'total_cost': session.total_cost,
                'charger_type': session.charger_type,
                'location': session.location,
                'network': session.network,
                'notes': session.notes,
                'created_at': session.created_at.isoformat() if session.created_at else None
            })

        # Add vehicle parts
        for part in vehicle.parts.all():
            vehicle_data['parts'].append({
                'id': part.id,
                'name': part.name,
                'part_type': part.part_type,
                'specification': part.specification,
                'quantity': part.quantity,
                'unit': part.unit,
                'part_number': part.part_number,
                'supplier_url': part.supplier_url,
                'notes': part.notes,
                'created_at': part.created_at.isoformat() if part.created_at else None,
                'updated_at': part.updated_at.isoformat() if part.updated_at else None
            })

        export_data['vehicles'].append(vehicle_data)

    # Add fuel stations (not vehicle-specific)
    for station in current_user.fuel_stations.all():
        export_data['fuel_stations'].append({
            'id': station.id,
            'name': station.name,
            'brand': station.brand,
            'address': station.address,
            'city': station.city,
            'postcode': station.postcode,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'notes': station.notes,
            'is_favorite': station.is_favorite,
            'price_source': station.price_source,
            'external_id': station.external_id,
            'times_used': station.times_used,
            'last_used': station.last_used.isoformat() if station.last_used else None,
            'created_at': station.created_at.isoformat() if station.created_at else None
        })

    # Add fuel price history
    for station in current_user.fuel_stations.all():
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

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'may_backup_{timestamp}.json'

    return Response(
        json.dumps(export_data, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@bp.route('/export/backup')
@login_required
def export_full_backup():
    """
    Export complete backup including all data and uploaded files.
    Creates a ZIP archive containing:
    - data.json: Full JSON backup with attachment references
    - manifest.json: File integrity manifest with SHA256 hashes
    - uploads/: All user's uploaded files
    """
    # Build export data (similar to export_json but with attachment info)
    export_data = {
        'export_info': {
            'exported_at': utcnow().isoformat(),
            'username': current_user.username,
            'app_version': APP_VERSION,
            'backup_type': 'full'
        },
        'user_preferences': {
            'language': current_user.language,
            'distance_unit': current_user.distance_unit,
            'volume_unit': current_user.volume_unit,
            'consumption_unit': current_user.consumption_unit,
            'currency': current_user.currency
        },
        'vehicles': [],
        'fuel_stations': [],
        'fuel_price_history': []
    }

    # Track files to include
    files_to_backup = []  # List of (filename, file_type, record_type, record_id)

    for vehicle in current_user.get_all_vehicles():
        vehicle_data = {
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
            'attachments': []
        }

        # Track vehicle image
        if vehicle.image_filename:
            files_to_backup.append((vehicle.image_filename, 'image', 'vehicle', vehicle.id))

        # Add vehicle attachments
        for attachment in vehicle.attachments.all():
            vehicle_data['attachments'].append({
                'id': attachment.id,
                'filename': attachment.filename,
                'original_filename': attachment.original_filename,
                'file_type': attachment.file_type,
                'file_size': attachment.file_size,
                'description': attachment.description,
                'created_at': attachment.created_at.isoformat() if attachment.created_at else None
            })
            files_to_backup.append((attachment.filename, attachment.file_type, 'vehicle_attachment', attachment.id))

        # Add specifications
        for spec in vehicle.specs.all():
            vehicle_data['specifications'].append({
                'id': spec.id,
                'spec_type': spec.spec_type,
                'label': spec.label,
                'value': spec.value,
                'created_at': spec.created_at.isoformat() if spec.created_at else None
            })

        # Add fuel logs with attachments
        for log in vehicle.fuel_logs.order_by(FuelLog.date.desc(), FuelLog.odometer.desc()).all():
            log_data = {
                'id': log.id,
                'date': log.date.isoformat() if log.date else None,
                'odometer': log.odometer,
                'volume': log.volume,
                'price_per_unit': log.price_per_unit,
                'total_cost': log.total_cost,
                'sales_tax': log.sales_tax,
                'fuel_type': log.fuel_type,
                'fuel_distance': log.fuel_distance,
                'is_full_tank': log.is_full_tank,
                'is_missed': log.is_missed,
                'station': log.station,
                'notes': log.notes,
                'created_at': log.created_at.isoformat() if log.created_at else None,
                'attachments': []
            }
            for attachment in log.attachments.all():
                log_data['attachments'].append({
                    'id': attachment.id,
                    'filename': attachment.filename,
                    'original_filename': attachment.original_filename,
                    'file_type': attachment.file_type,
                    'file_size': attachment.file_size,
                    'description': attachment.description,
                    'created_at': attachment.created_at.isoformat() if attachment.created_at else None
                })
                files_to_backup.append((attachment.filename, attachment.file_type, 'fuel_log_attachment', attachment.id))
            vehicle_data['fuel_logs'].append(log_data)

        # Add expenses with attachments
        for expense in vehicle.expenses.order_by(Expense.date.desc()).all():
            expense_data = {
                'id': expense.id,
                'date': expense.date.isoformat() if expense.date else None,
                'category': expense.category,
                'description': expense.description,
                'cost': expense.cost,
                'odometer': expense.odometer,
                'vendor': expense.vendor,
                'notes': expense.notes,
                'created_at': expense.created_at.isoformat() if expense.created_at else None,
                'attachments': []
            }
            for attachment in expense.attachments.all():
                expense_data['attachments'].append({
                    'id': attachment.id,
                    'filename': attachment.filename,
                    'original_filename': attachment.original_filename,
                    'file_type': attachment.file_type,
                    'file_size': attachment.file_size,
                    'description': attachment.description,
                    'created_at': attachment.created_at.isoformat() if attachment.created_at else None
                })
                files_to_backup.append((attachment.filename, attachment.file_type, 'expense_attachment', attachment.id))
            vehicle_data['expenses'].append(expense_data)

        # Add reminders
        for reminder in vehicle.reminders.all():
            vehicle_data['reminders'].append({
                'id': reminder.id,
                'title': reminder.title,
                'description': reminder.description,
                'reminder_type': reminder.reminder_type,
                'due_date': reminder.due_date.isoformat() if reminder.due_date else None,
                'recurrence': reminder.recurrence,
                'recurrence_interval': reminder.recurrence_interval,
                'notify_days_before': reminder.notify_days_before,
                'notification_sent': reminder.notification_sent,
                'is_completed': reminder.is_completed,
                'completed_at': reminder.completed_at.isoformat() if reminder.completed_at else None,
                'created_at': reminder.created_at.isoformat() if reminder.created_at else None
            })

        # Add maintenance schedules
        for schedule in vehicle.maintenance_schedules.all():
            vehicle_data['maintenance_schedules'].append({
                'id': schedule.id,
                'name': schedule.name,
                'maintenance_type': schedule.maintenance_type,
                'description': schedule.description,
                'interval_miles': schedule.interval_miles,
                'interval_km': schedule.interval_km,
                'interval_months': schedule.interval_months,
                'last_performed_date': schedule.last_performed_date.isoformat() if schedule.last_performed_date else None,
                'last_performed_odometer': schedule.last_performed_odometer,
                'next_due_date': schedule.next_due_date.isoformat() if schedule.next_due_date else None,
                'next_due_odometer': schedule.next_due_odometer,
                'estimated_cost': schedule.estimated_cost,
                'auto_remind': schedule.auto_remind,
                'remind_days_before': schedule.remind_days_before,
                'remind_miles_before': schedule.remind_miles_before,
                'is_active': schedule.is_active,
                'created_at': schedule.created_at.isoformat() if schedule.created_at else None
            })

        # Add recurring expenses
        for recurring in vehicle.recurring_expenses.all():
            vehicle_data['recurring_expenses'].append({
                'id': recurring.id,
                'name': recurring.name,
                'category': recurring.category,
                'description': recurring.description,
                'amount': recurring.amount,
                'vendor': recurring.vendor,
                'frequency': recurring.frequency,
                'start_date': recurring.start_date.isoformat() if recurring.start_date else None,
                'end_date': recurring.end_date.isoformat() if recurring.end_date else None,
                'last_generated': recurring.last_generated.isoformat() if recurring.last_generated else None,
                'next_due': recurring.next_due.isoformat() if recurring.next_due else None,
                'auto_create': recurring.auto_create,
                'notify_before_days': recurring.notify_before_days,
                'is_active': recurring.is_active,
                'created_at': recurring.created_at.isoformat() if recurring.created_at else None
            })

        # Add documents with filename for restore
        for doc in vehicle.documents.all():
            vehicle_data['documents'].append({
                'id': doc.id,
                'title': doc.title,
                'document_type': doc.document_type,
                'description': doc.description,
                'filename': doc.filename,
                'original_filename': doc.original_filename,
                'file_type': doc.file_type,
                'file_size': doc.file_size,
                'issue_date': doc.issue_date.isoformat() if doc.issue_date else None,
                'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None,
                'reference_number': doc.reference_number,
                'remind_before_expiry': doc.remind_before_expiry,
                'remind_days': doc.remind_days,
                'created_at': doc.created_at.isoformat() if doc.created_at else None
            })
            files_to_backup.append((doc.filename, doc.file_type, 'document', doc.id))

        # Add trips
        for trip in vehicle.trips.order_by(Trip.date.desc()).all():
            vehicle_data['trips'].append({
                'id': trip.id,
                'date': trip.date.isoformat() if trip.date else None,
                'start_odometer': trip.start_odometer,
                'end_odometer': trip.end_odometer,
                'distance': trip.distance,
                'start_fuel_level': trip.start_fuel_level,
                'end_fuel_level': trip.end_fuel_level,
                'purpose': trip.purpose,
                'description': trip.description,
                'start_location': trip.start_location,
                'end_location': trip.end_location,
                'notes': trip.notes,
                'created_at': trip.created_at.isoformat() if trip.created_at else None
            })

        # Add charging sessions
        for session in vehicle.charging_sessions.order_by(ChargingSession.date.desc()).all():
            vehicle_data['charging_sessions'].append({
                'id': session.id,
                'date': session.date.isoformat() if session.date else None,
                'start_time': session.start_time.isoformat() if session.start_time else None,
                'end_time': session.end_time.isoformat() if session.end_time else None,
                'odometer': session.odometer,
                'kwh_added': session.kwh_added,
                'start_soc': session.start_soc,
                'end_soc': session.end_soc,
                'cost_per_kwh': session.cost_per_kwh,
                'total_cost': session.total_cost,
                'charger_type': session.charger_type,
                'location': session.location,
                'network': session.network,
                'notes': session.notes,
                'created_at': session.created_at.isoformat() if session.created_at else None
            })

        # Add vehicle parts
        for part in vehicle.parts.all():
            vehicle_data['parts'].append({
                'id': part.id,
                'name': part.name,
                'part_type': part.part_type,
                'specification': part.specification,
                'quantity': part.quantity,
                'unit': part.unit,
                'part_number': part.part_number,
                'supplier_url': part.supplier_url,
                'notes': part.notes,
                'created_at': part.created_at.isoformat() if part.created_at else None,
                'updated_at': part.updated_at.isoformat() if part.updated_at else None
            })

        export_data['vehicles'].append(vehicle_data)

    # Add fuel stations (not vehicle-specific)
    for station in current_user.fuel_stations.all():
        export_data['fuel_stations'].append({
            'id': station.id,
            'name': station.name,
            'brand': station.brand,
            'address': station.address,
            'city': station.city,
            'postcode': station.postcode,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'notes': station.notes,
            'is_favorite': station.is_favorite,
            'price_source': station.price_source,
            'external_id': station.external_id,
            'times_used': station.times_used,
            'last_used': station.last_used.isoformat() if station.last_used else None,
            'created_at': station.created_at.isoformat() if station.created_at else None
        })

    # Add fuel price history
    for station in current_user.fuel_stations.all():
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

    # Build manifest and create ZIP
    upload_folder = current_app.config['UPLOAD_FOLDER']
    manifest = {
        'version': APP_VERSION,
        'created_at': utcnow().isoformat(),
        'username': current_user.username,
        'files': []
    }

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add files to ZIP
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
                    # Skip files that can't be read
                    pass

        # Add manifest reference to export data
        export_data['files_manifest'] = {
            'total_files': len(manifest['files']),
            'files': manifest['files']
        }

        # Write data.json and manifest.json to ZIP
        zf.writestr('data.json', json.dumps(export_data, indent=2))
        zf.writestr('manifest.json', json.dumps(manifest, indent=2))

    zip_buffer.seek(0)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'may_full_backup_{timestamp}.zip'

    return Response(
        zip_buffer.getvalue(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# =============================================================================
# Data Import (Web UI routes, session-authenticated)
# =============================================================================

# Hammond fuel unit mapping
HAMMOND_FUEL_UNITS = {
    'LITRE': 'L',
    'GALLON': 'gal',
    'US_GALLON': 'us_gal',
}

# Hammond fuel type mapping
# =============================================================================
# Hammond / Clarkson Import Helpers
# =============================================================================

def _safe_get(row, key, default=None):
    """Safely get a value from a sqlite3.Row, returning default if column missing."""
    try:
        val = row[key]
        return val if val is not None else default
    except (IndexError, KeyError):
        return default


def _safe_float(row, key, default=None):
    """Safely get a float from a sqlite3.Row."""
    val = _safe_get(row, key)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        logger.warning("Hammond: could not convert %s=%r to float", key, val)
        return default


def _safe_int(row, key, default=None):
    """Safely get an int from a sqlite3.Row."""
    val = _safe_get(row, key)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        logger.warning("Hammond: could not convert %s=%r to int", key, val)
        return default


def _parse_hammond_date(row, key):
    """Parse a date from a Hammond row. Hammond stores dates as ISO 8601 strings.
    Falls back to today's date if parsing fails."""
    val = _safe_get(row, key)
    if not val:
        return utcnow().date()
    try:
        # Hammond may store dates as "2022-01-15T00:00:00Z" or "2022-01-15"
        return datetime.fromisoformat(str(val).replace('Z', '+00:00')).date()
    except (ValueError, TypeError) as e:
        logger.warning("Hammond: could not parse date %s=%r: %s", key, val, e)
        return utcnow().date()


HAMMOND_FUEL_TYPES = {
    'PETROL': 'petrol',
    'DIESEL': 'diesel',
    'ETHANOL': 'e85',
    'LPG': 'lpg',
    'ELECTRIC': 'electric',
    'HYBRID': 'hybrid',
}

# Hammond distance unit mapping
HAMMOND_DISTANCE_UNITS = {
    'MILES': 'mi',
    'KILOMETERS': 'km',
}

# Clarkson fuel type mapping (int to string)
CLARKSON_FUEL_TYPES = {
    1: 'petrol',
    2: 'diesel',
    3: 'e85',
    4: 'lpg',
}

# Clarkson distance unit mapping
CLARKSON_DISTANCE_UNITS = {
    1: 'mi',
    2: 'km',
}

# Clarkson fuel unit mapping
CLARKSON_FUEL_UNITS = {
    1: 'L',
    2: 'gal',
    3: 'us_gal',
}


@bp.route('/import/hammond', methods=['POST'])
@login_required
def import_hammond():
    """
    Import data from a Hammond (github.com/akhilrex/hammond) SQLite database.

    Hammond database schema (v2022.07.06):
      vehicles: id, make, model, year_of_manufacture, nickname, registration,
                vin, fuel_type (string: PETROL/DIESEL/etc), fuel_unit, distance_unit
      fillups:  id, vehicle_id, fuel_quantity, per_unit_price, total_amount,
                odo_reading, is_tank_full, has_missed_fillup, date (ISO string),
                filling_station, comments, fuel_sub_type
      expenses: id, vehicle_id, expense_type, amount, odo_reading, date (ISO string),
                comments, type_id

    Note: Hammond date fields may be ISO 8601 strings with or without timezone.
    Some fields may be NULL depending on user input.
    """
    if 'file' not in request.files:
        flash(_('No file uploaded'), 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    file = request.files['file']
    if not file.filename:
        flash(_('No file selected'), 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    logger.info("Hammond import started by user %s, file: %s", current_user.id, file.filename)

    try:
        # Validate the file is a valid SQLite database
        try:
            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Quick sanity check - this will fail if the file isn't a valid SQLite DB
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row['name'] for row in cursor.fetchall()}
            logger.info("Hammond DB tables found: %s", tables)
        except sqlite3.DatabaseError as e:
            logger.error("Hammond import: uploaded file is not a valid SQLite database: %s", e)
            flash(_('The uploaded file is not a valid SQLite database.'), 'error')
            return redirect(url_for('auth.settings') + '#integrations')

        if not tables.intersection({'vehicles', 'fillups', 'expenses'}):
            logger.warning("Hammond import: no recognised tables found. Tables in DB: %s", tables)
            flash(_('This does not appear to be a Hammond database — no vehicles, fillups, or expenses tables found.'), 'error')
            conn.close()
            return redirect(url_for('auth.settings') + '#integrations')

        # Track import statistics
        stats = {'vehicles': 0, 'fuel_logs': 0, 'expenses': 0}
        skipped = {'vehicles': 0, 'fuel_logs': 0, 'expenses': 0}
        vehicle_id_map = {}  # Hammond vehicle ID -> May vehicle ID

        # --- Import vehicles ---
        if 'vehicles' in tables:
            try:
                cursor.execute('SELECT * FROM vehicles')
                hammond_vehicles = cursor.fetchall()
                logger.info("Hammond: found %d vehicles to import", len(hammond_vehicles))

                for hv in hammond_vehicles:
                    try:
                        # Safely read columns with defaults for missing/NULL values
                        hv_id = hv['id']
                        fuel_type_raw = _safe_get(hv, 'fuel_type')
                        fuel_type = HAMMOND_FUEL_TYPES.get(fuel_type_raw, 'petrol') if fuel_type_raw else 'petrol'
                        make = _safe_get(hv, 'make', '')
                        model = _safe_get(hv, 'model', '')
                        nickname = _safe_get(hv, 'nickname')

                        vehicle = Vehicle(
                            owner_id=current_user.id,
                            name=nickname or f"{make} {model}".strip() or 'Imported Vehicle',
                            vehicle_type='car',  # Hammond doesn't distinguish vehicle types
                            make=make or None,
                            model=model or None,
                            year=_safe_int(hv, 'year_of_manufacture'),
                            registration=_safe_get(hv, 'registration'),
                            vin=_safe_get(hv, 'vin'),
                            fuel_type=fuel_type,
                            tank_capacity=None,
                            notes=f"Imported from Hammond (ID: {hv_id})"
                        )
                        db.session.add(vehicle)
                        db.session.flush()
                        vehicle_id_map[hv_id] = vehicle.id
                        stats['vehicles'] += 1
                    except (KeyError, IndexError) as e:
                        logger.warning("Hammond: skipping vehicle row due to missing column: %s", e)
                        skipped['vehicles'] += 1
                    except Exception as e:
                        logger.error("Hammond: error importing vehicle: %s\n%s", e, traceback.format_exc())
                        skipped['vehicles'] += 1

            except sqlite3.OperationalError as e:
                logger.warning("Hammond: could not read vehicles table: %s", e)
        else:
            logger.info("Hammond: no 'vehicles' table found, skipping")

        # --- Import fillups (fuel logs) ---
        if 'fillups' in tables:
            try:
                cursor.execute('SELECT * FROM fillups')
                hammond_fillups = cursor.fetchall()
                logger.info("Hammond: found %d fillups to import", len(hammond_fillups))

                for hf in hammond_fillups:
                    try:
                        vehicle_id = vehicle_id_map.get(hf['vehicle_id'])
                        if not vehicle_id:
                            skipped['fuel_logs'] += 1
                            continue

                        date = _parse_hammond_date(hf, 'date')

                        log = FuelLog(
                            vehicle_id=vehicle_id,
                            user_id=current_user.id,
                            date=date,
                            odometer=_safe_float(hf, 'odo_reading', 0),
                            volume=_safe_float(hf, 'fuel_quantity'),
                            price_per_unit=_safe_float(hf, 'per_unit_price'),
                            total_cost=_safe_float(hf, 'total_amount'),
                            is_full_tank=bool(hf['is_tank_full']) if _safe_get(hf, 'is_tank_full') is not None else True,
                            is_missed=bool(hf['has_missed_fillup']) if _safe_get(hf, 'has_missed_fillup') is not None else False,
                            station=_safe_get(hf, 'filling_station'),
                            notes=_safe_get(hf, 'comments')
                        )
                        db.session.add(log)
                        stats['fuel_logs'] += 1
                    except (KeyError, IndexError) as e:
                        logger.warning("Hammond: skipping fillup row due to missing column: %s", e)
                        skipped['fuel_logs'] += 1
                    except Exception as e:
                        logger.error("Hammond: error importing fillup: %s\n%s", e, traceback.format_exc())
                        skipped['fuel_logs'] += 1

            except sqlite3.OperationalError as e:
                logger.warning("Hammond: could not read fillups table: %s", e)
        else:
            logger.info("Hammond: no 'fillups' table found, skipping")

        # --- Import expenses ---
        if 'expenses' in tables:
            try:
                cursor.execute('SELECT * FROM expenses')
                hammond_expenses = cursor.fetchall()
                logger.info("Hammond: found %d expenses to import", len(hammond_expenses))

                for he in hammond_expenses:
                    try:
                        vehicle_id = vehicle_id_map.get(he['vehicle_id'])
                        if not vehicle_id:
                            skipped['expenses'] += 1
                            continue

                        date = _parse_hammond_date(he, 'date')

                        # Map expense type
                        expense_type_raw = _safe_get(he, 'expense_type', 'other')
                        expense_type = (expense_type_raw or 'other').lower()
                        valid_categories = [c[0] for c in EXPENSE_CATEGORIES]
                        if expense_type not in valid_categories:
                            expense_type = 'other'

                        expense = Expense(
                            vehicle_id=vehicle_id,
                            user_id=current_user.id,
                            date=date,
                            category=expense_type,
                            description=expense_type_raw or 'Imported expense',
                            cost=_safe_float(he, 'amount', 0),
                            odometer=_safe_float(he, 'odo_reading'),
                            notes=_safe_get(he, 'comments')
                        )
                        db.session.add(expense)
                        stats['expenses'] += 1
                    except (KeyError, IndexError) as e:
                        logger.warning("Hammond: skipping expense row due to missing column: %s", e)
                        skipped['expenses'] += 1
                    except Exception as e:
                        logger.error("Hammond: error importing expense: %s\n%s", e, traceback.format_exc())
                        skipped['expenses'] += 1

            except sqlite3.OperationalError as e:
                logger.warning("Hammond: could not read expenses table: %s", e)
        else:
            logger.info("Hammond: no 'expenses' table found, skipping")

        db.session.commit()
        conn.close()

        total_skipped = sum(skipped.values())
        msg = _('Hammond import complete: %(vehicles)s vehicles, %(fuel_logs)s fuel logs, %(expenses)s expenses imported.') % {'vehicles': stats['vehicles'], 'fuel_logs': stats['fuel_logs'], 'expenses': stats['expenses']}
        if total_skipped:
            msg += ' ' + _('(%(total_skipped)s records skipped due to errors — check server logs for details.)') % {'total_skipped': total_skipped}
        logger.info("Hammond import finished: imported=%s, skipped=%s", stats, skipped)
        flash(msg, 'success')

    except sqlite3.Error as e:
        db.session.rollback()
        logger.error("Hammond import failed (SQLite error): %s\n%s", e, traceback.format_exc())
        flash(_('Import failed due to a database error. Check that the file is a valid Hammond database. Error: %(error)s') % {'error': e}, 'error')

    except Exception as e:
        db.session.rollback()
        logger.error("Hammond import failed (unexpected error): %s\n%s", e, traceback.format_exc())
        flash(_('Import failed: %(error)s') % {'error': e}, 'error')

    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return redirect(url_for('auth.settings') + '#integrations')


@bp.route('/import/clarkson', methods=['POST'])
@login_required
def import_clarkson():
    """
    Import data from Clarkson MySQL database.
    Expects a .sql dump file upload.
    """
    if 'file' not in request.files:
        flash(_('No file uploaded'), 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    file = request.files['file']
    if not file.filename:
        flash(_('No file selected'), 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    try:
        # Read SQL dump content
        content = file.read().decode('utf-8', errors='ignore')

        # Track import statistics
        stats = {'vehicles': 0, 'fuel_logs': 0}
        vehicle_id_map = {}  # Clarkson vehicle ID -> May vehicle ID

        # Parse INSERT statements for Vehicles table
        # Clarkson format: INSERT INTO `Vehicles` VALUES (id, userId, name, registration, make, model, yearOfManufacture, engineSizeCC, fuelType, active)
        import re

        # Find Vehicles INSERT statements
        vehicle_pattern = r"INSERT INTO [`']?Vehicles[`']?\s+(?:VALUES\s*)?\(([^)]+)\)"
        vehicle_matches = re.findall(vehicle_pattern, content, re.IGNORECASE)

        # Also try multi-value inserts
        vehicle_multi_pattern = r"INSERT INTO [`']?Vehicles[`']?[^;]*VALUES\s*((?:\([^)]+\)\s*,?\s*)+)"
        vehicle_multi_matches = re.findall(vehicle_multi_pattern, content, re.IGNORECASE)

        for match in vehicle_multi_matches:
            # Extract individual value tuples
            tuples = re.findall(r'\(([^)]+)\)', match)
            vehicle_matches.extend(tuples)

        for values_str in vehicle_matches:
            try:
                # Parse CSV-like values (handling quoted strings)
                values = parse_sql_values(values_str)
                if len(values) >= 9:
                    # Clarkson may use integer IDs or UUIDs — store as string key
                    raw_id = clean_sql_string(values[0]) if values[0] else None
                    clarkson_id = raw_id
                    name = clean_sql_string(values[2])
                    registration = clean_sql_string(values[3])
                    make = clean_sql_string(values[4])
                    model = clean_sql_string(values[5])
                    year = int(values[6]) if values[6] and values[6] != 'NULL' else None
                    fuel_type_id = int(values[8]) if values[8] and values[8] != 'NULL' else 1

                    fuel_type = CLARKSON_FUEL_TYPES.get(fuel_type_id, 'petrol')

                    vehicle = Vehicle(
                        owner_id=current_user.id,
                        name=name or f"{make} {model}".strip() or 'Imported Vehicle',
                        vehicle_type='car',
                        make=make,
                        model=model,
                        year=year,
                        registration=registration,
                        fuel_type=fuel_type,
                        notes=f"Imported from Clarkson (ID: {clarkson_id})"
                    )
                    db.session.add(vehicle)
                    db.session.flush()
                    if clarkson_id:
                        vehicle_id_map[clarkson_id] = vehicle.id
                    stats['vehicles'] += 1

            except (ValueError, IndexError) as e:
                continue

        # Find Fuel INSERT statements — table may be named `Fuel` or `Fuelups`
        # Clarkson format: INSERT INTO `Fuel` VALUES (id, vehicleId, fuelAmount, fuelUnitCost, totalCost, odometerReading, dateTime, fullTank, missedFillUp, userId, fuelUnit, location, lat, lng)
        fuel_pattern = r"INSERT INTO [`']?(?:Fuel|Fuelups)[`']?\s+(?:VALUES\s*)?\(([^)]+)\)"
        fuel_matches = re.findall(fuel_pattern, content, re.IGNORECASE)

        fuel_multi_pattern = r"INSERT INTO [`']?(?:Fuel|Fuelups)[`']?[^;]*VALUES\s*((?:\([^)]+\)\s*,?\s*)+)"
        fuel_multi_matches = re.findall(fuel_multi_pattern, content, re.IGNORECASE)

        for match in fuel_multi_matches:
            tuples = re.findall(r'\(([^)]+)\)', match)
            fuel_matches.extend(tuples)

        for values_str in fuel_matches:
            try:
                values = parse_sql_values(values_str)
                if len(values) >= 10:
                    clarkson_vehicle_id = clean_sql_string(values[1]) if values[1] else None
                    vehicle_id = vehicle_id_map.get(clarkson_vehicle_id)
                    if not vehicle_id:
                        continue

                    # Parse date
                    date_str = clean_sql_string(values[6])
                    try:
                        date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').date() if date_str else utcnow().date()
                    except ValueError:
                        try:
                            date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        except ValueError:
                            date = utcnow().date()

                    station = clean_sql_string(values[11]) if len(values) > 11 else None

                    log = FuelLog(
                        vehicle_id=vehicle_id,
                        user_id=current_user.id,
                        date=date,
                        odometer=float(values[5]) if values[5] and values[5] != 'NULL' else 0,
                        volume=float(values[2]) if values[2] and values[2] != 'NULL' else None,
                        price_per_unit=float(values[3]) if values[3] and values[3] != 'NULL' else None,
                        total_cost=float(values[4]) if values[4] and values[4] != 'NULL' else None,
                        is_full_tank=values[7] == '1' if values[7] else True,
                        is_missed=values[8] == '1' if values[8] else False,
                        station=station,
                    )
                    db.session.add(log)
                    stats['fuel_logs'] += 1

            except (ValueError, IndexError) as e:
                continue

        db.session.commit()
        flash(_('Clarkson import complete: %(vehicles)s vehicles, %(fuel_logs)s fuel logs') % {'vehicles': stats['vehicles'], 'fuel_logs': stats['fuel_logs']}, 'success')

    except Exception as e:
        db.session.rollback()
        flash(_('Import failed: %(error)s') % {'error': str(e)}, 'error')

    return redirect(url_for('auth.settings') + '#integrations')


def parse_sql_values(values_str):
    """Parse SQL INSERT values handling quoted strings and NULLs"""
    values = []
    current = ''
    in_quotes = False
    quote_char = None

    for char in values_str:
        if char in ("'", '"') and not in_quotes:
            in_quotes = True
            quote_char = char
        elif char == quote_char and in_quotes:
            in_quotes = False
            quote_char = None
        elif char == ',' and not in_quotes:
            values.append(current.strip())
            current = ''
            continue
        current += char

    if current:
        values.append(current.strip())

    return values


def clean_sql_string(value):
    """Clean a SQL string value, removing quotes and handling NULL"""
    if not value or value.upper() == 'NULL':
        return None
    value = value.strip()
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        value = value[1:-1]
    return value.replace("\\'", "'").replace('\\"', '"')


@bp.route('/import/fuelly', methods=['POST'])
@login_required
def import_fuelly():
    """
    Import data from Fuelly CSV export.
    Expects a CSV file with columns: Name, Model, MPG, Odometer, Miles, Gallons, Price, Fuelup Date, Date Added, Tags, Notes
    """
    if 'file' not in request.files:
        flash(_('No file uploaded'), 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    file = request.files['file']
    if not file.filename:
        flash(_('No file selected'), 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    try:
        # Read CSV content
        content = file.read().decode('utf-8-sig', errors='ignore')  # utf-8-sig handles BOM
        reader = csv.DictReader(io.StringIO(content))

        # Track import statistics
        stats = {'vehicles': 0, 'fuel_logs': 0}
        vehicle_cache = {}  # Vehicle name -> Vehicle object

        for row in reader:
            try:
                # Get or create vehicle
                # Fuelly uses "Name" for vehicle name and "Model" for model
                vehicle_name = row.get('Name', '').strip()
                vehicle_model = row.get('Model', '').strip()

                if not vehicle_name:
                    vehicle_name = vehicle_model or 'Imported Vehicle'

                # Create a unique key for the vehicle
                vehicle_key = f"{vehicle_name}|{vehicle_model}"

                if vehicle_key not in vehicle_cache:
                    # Check if vehicle already exists for this user
                    existing = Vehicle.query.filter_by(
                        owner_id=current_user.id,
                        name=vehicle_name
                    ).first()

                    if existing:
                        vehicle_cache[vehicle_key] = existing
                    else:
                        vehicle = Vehicle(
                            owner_id=current_user.id,
                            name=vehicle_name,
                            vehicle_type='car',
                            model=vehicle_model if vehicle_model != vehicle_name else None,
                            fuel_type='petrol',
                            notes='Imported from Fuelly'
                        )
                        db.session.add(vehicle)
                        db.session.flush()
                        vehicle_cache[vehicle_key] = vehicle
                        stats['vehicles'] += 1

                vehicle = vehicle_cache[vehicle_key]

                # Parse fuel log data
                # Fuelly date formats: YYYY-MM-DD or M/D/YY or M/D/YYYY
                date_str = row.get('Fuelup Date', '').strip() or row.get('Date', '').strip()
                date = None
                if date_str:
                    for fmt in ['%Y-%m-%d', '%m/%d/%y', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S']:
                        try:
                            date = datetime.strptime(date_str, fmt).date()
                            break
                        except ValueError:
                            continue

                if not date:
                    date = utcnow().date()

                # Parse numeric values - Fuelly uses US units (gallons, miles)
                odometer_str = row.get('Odometer', '').strip().replace(',', '')
                gallons_str = row.get('Gallons', '').strip().replace(',', '')
                price_str = row.get('Price', '').strip().replace(',', '').replace('$', '')
                miles_str = row.get('Miles', '').strip().replace(',', '')

                odometer = float(odometer_str) if odometer_str else None
                gallons = float(gallons_str) if gallons_str else None
                price = float(price_str) if price_str else None

                # Calculate total cost if we have gallons and price
                total_cost = None
                if gallons and price:
                    total_cost = round(gallons * price, 2)

                # Get notes and tags
                notes = row.get('Notes', '').strip()
                tags = row.get('Tags', '').strip()
                if tags and notes:
                    notes = f"{notes} [Tags: {tags}]"
                elif tags:
                    notes = f"[Tags: {tags}]"

                # Check for partial fill indicator
                # Fuelly uses "Partial" column or notes may indicate partial fill
                is_partial = row.get('Partial', '').strip().lower() in ('1', 'yes', 'true', 'partial')
                is_full_tank = not is_partial

                # Create fuel log (only if we have meaningful data)
                if odometer or gallons:
                    log = FuelLog(
                        vehicle_id=vehicle.id,
                        user_id=current_user.id,
                        date=date,
                        odometer=odometer or 0,
                        volume=gallons,  # Store in original units (gallons)
                        price_per_unit=price,
                        total_cost=total_cost,
                        is_full_tank=is_full_tank,
                        is_missed=False,
                        notes=notes if notes else None
                    )
                    db.session.add(log)
                    stats['fuel_logs'] += 1

            except (ValueError, KeyError) as e:
                continue

        db.session.commit()
        flash(_('Fuelly import complete: %(vehicles)s new vehicles, %(fuel_logs)s fuel logs') % {'vehicles': stats['vehicles'], 'fuel_logs': stats['fuel_logs']}, 'success')

    except Exception as e:
        db.session.rollback()
        flash(_('Import failed: %(error)s') % {'error': str(e)}, 'error')

    return redirect(url_for('auth.settings') + '#integrations')


# =============================================================================
# Generic CSV Import
# =============================================================================

def get_import_fields(data_type):
    """Return field definitions for a given data type."""
    fields = {
        'fuel_logs': [
            {'name': 'date', 'label': 'Date', 'required': True, 'type': 'date'},
            {'name': 'odometer', 'label': 'Odometer', 'required': True, 'type': 'float'},
            {'name': 'volume', 'label': 'Volume', 'required': False, 'type': 'float'},
            {'name': 'price_per_unit', 'label': 'Price per Unit', 'required': False, 'type': 'float'},
            {'name': 'total_cost', 'label': 'Total Cost', 'required': False, 'type': 'float'},
            {'name': 'sales_tax', 'label': 'Sales Tax', 'required': False, 'type': 'float'},
            {'name': 'is_full_tank', 'label': 'Full Tank', 'required': False, 'type': 'bool'},
            {'name': 'is_missed', 'label': 'Missed Fill-up', 'required': False, 'type': 'bool'},
            {'name': 'station', 'label': 'Station', 'required': False, 'type': 'str'},
            {'name': 'notes', 'label': 'Notes', 'required': False, 'type': 'str'},
        ],
        'expenses': [
            {'name': 'date', 'label': 'Date', 'required': True, 'type': 'date'},
            {'name': 'category', 'label': 'Category', 'required': True, 'type': 'str'},
            {'name': 'description', 'label': 'Description', 'required': True, 'type': 'str'},
            {'name': 'cost', 'label': 'Cost', 'required': True, 'type': 'float'},
            {'name': 'odometer', 'label': 'Odometer', 'required': False, 'type': 'float'},
            {'name': 'vendor', 'label': 'Vendor', 'required': False, 'type': 'str'},
            {'name': 'notes', 'label': 'Notes', 'required': False, 'type': 'str'},
        ],
        'trips': [
            {'name': 'date', 'label': 'Date', 'required': True, 'type': 'date'},
            {'name': 'start_odometer', 'label': 'Start Odometer', 'required': True, 'type': 'float'},
            {'name': 'end_odometer', 'label': 'End Odometer', 'required': True, 'type': 'float'},
            {'name': 'start_fuel_level', 'label': 'Start Fuel Level %', 'required': False, 'type': 'float'},
            {'name': 'end_fuel_level', 'label': 'End Fuel Level %', 'required': False, 'type': 'float'},
            {'name': 'purpose', 'label': 'Purpose', 'required': True, 'type': 'str'},
            {'name': 'description', 'label': 'Description', 'required': False, 'type': 'str'},
            {'name': 'start_location', 'label': 'Start Location', 'required': False, 'type': 'str'},
            {'name': 'end_location', 'label': 'End Location', 'required': False, 'type': 'str'},
            {'name': 'notes', 'label': 'Notes', 'required': False, 'type': 'str'},
        ],
        'charging_sessions': [
            {'name': 'date', 'label': 'Date', 'required': True, 'type': 'date'},
            {'name': 'start_time', 'label': 'Start Time', 'required': False, 'type': 'time'},
            {'name': 'end_time', 'label': 'End Time', 'required': False, 'type': 'time'},
            {'name': 'odometer', 'label': 'Odometer', 'required': False, 'type': 'float'},
            {'name': 'kwh_added', 'label': 'kWh Added', 'required': False, 'type': 'float'},
            {'name': 'start_soc', 'label': 'Start SOC %', 'required': False, 'type': 'int'},
            {'name': 'end_soc', 'label': 'End SOC %', 'required': False, 'type': 'int'},
            {'name': 'cost_per_kwh', 'label': 'Cost per kWh', 'required': False, 'type': 'float'},
            {'name': 'total_cost', 'label': 'Total Cost', 'required': False, 'type': 'float'},
            {'name': 'charger_type', 'label': 'Charger Type', 'required': False, 'type': 'str'},
            {'name': 'location', 'label': 'Location', 'required': False, 'type': 'str'},
            {'name': 'network', 'label': 'Network', 'required': False, 'type': 'str'},
            {'name': 'notes', 'label': 'Notes', 'required': False, 'type': 'str'},
        ],
    }
    return fields.get(data_type, [])


# Common aliases for auto-suggesting column mappings
_COLUMN_ALIASES = {
    'date': ['date', 'fuelup date', 'fill date', 'trip date', 'charge date', 'session date', 'expense date'],
    'odometer': ['odometer', 'odo', 'mileage', 'miles', 'km', 'kilometers', 'distance'],
    'volume': ['volume', 'litres', 'liters', 'gallons', 'gal', 'fuel', 'qty', 'quantity'],
    'price_per_unit': ['price per unit', 'unit price', 'price/l', 'price/gal', 'price', 'rate'],
    'total_cost': ['total cost', 'total', 'cost', 'price paid', 'total price'],
    'sales_tax': ['sales tax', 'sales taxes', 'tax', 'taxes', 'vat', 'gst', 'hst', 'pst', 'qst'],
    'is_full_tank': ['full tank', 'full', 'complete', 'full fill'],
    'is_missed': ['missed', 'missed fill', 'skipped'],
    'station': ['station', 'gas station', 'fuel station'],
    'notes': ['notes', 'note', 'comments', 'comment', 'remarks', 'memo'],
    'category': ['category', 'type', 'expense type', 'expense category'],
    'description': ['description', 'desc', 'title', 'name', 'item', 'service'],
    'cost': ['cost', 'amount', 'total', 'price', 'expense'],
    'vendor': ['vendor', 'shop', 'store', 'supplier', 'merchant', 'provider'],
    'start_odometer': ['start odometer', 'start odo', 'start miles', 'start km', 'odometer start'],
    'end_odometer': ['end odometer', 'end odo', 'end miles', 'end km', 'odometer end'],
    'purpose': ['purpose', 'trip purpose', 'reason', 'trip type'],
    'start_fuel_level': ['start fuel level', 'start fuel', 'fuel start', 'start tank', 'start fuel %'],
    'end_fuel_level': ['end fuel level', 'end fuel', 'fuel end', 'end tank', 'end fuel %'],
    'start_location': ['start location', 'from', 'origin', 'departure'],
    'end_location': ['end location', 'to', 'destination', 'arrival'],
    'start_time': ['start time', 'time start', 'begin time'],
    'end_time': ['end time', 'time end', 'finish time'],
    'kwh_added': ['kwh added', 'kwh', 'energy', 'energy added', 'kilowatt hours'],
    'start_soc': ['start soc', 'soc start', 'start battery', 'battery start', 'start %'],
    'end_soc': ['end soc', 'soc end', 'end battery', 'battery end', 'end %'],
    'cost_per_kwh': ['cost per kwh', 'price per kwh', 'kwh price', 'kwh cost'],
    'charger_type': ['charger type', 'charger', 'connector', 'plug type'],
    'location': ['location', 'place', 'charging station', 'site'],
    'network': ['network', 'provider', 'operator', 'charging network'],
}


def auto_suggest_mappings(csv_columns, target_fields):
    """Match CSV column names to target fields using normalized name comparison."""
    field_names = {f['name'] for f in target_fields}
    suggestions = {}
    used_fields = set()

    for col in csv_columns:
        normalized = col.strip().lower().replace('_', ' ').replace('-', ' ')
        best_match = None

        for field_name, aliases in _COLUMN_ALIASES.items():
            if field_name not in field_names or field_name in used_fields:
                continue
            if normalized in aliases or normalized == field_name.replace('_', ' '):
                best_match = field_name
                break

        if best_match:
            suggestions[col] = best_match
            used_fields.add(best_match)

    return suggestions


def _ordered_slash_formats(prefer_mdy):
    """Return ambiguous day/month date formats, preferred interpretation first.

    ``strptime`` rejects out-of-range values, so listing the preferred order
    first means a value that is unambiguous (e.g. a 31 in the day slot) still
    falls through to the only interpretation that parses, without silently
    reversing values that are valid under the preferred format.
    """
    dmy = ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y',
           '%d-%m-%Y', '%d.%m.%Y', '%d/%m/%y']
    mdy = ['%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M', '%m/%d/%Y',
           '%m-%d-%Y', '%m/%d/%y']
    return (mdy + dmy) if prefer_mdy else (dmy + mdy)


def parse_date_value(value, date_format='auto', user_date_format=None):
    """Parse a date string, optionally with a format hint.

    ``date_format`` is the format chosen on the import screen. When it is
    ``'auto'`` the importing user's own ``date_format`` preference
    (``user_date_format``) disambiguates slash-separated dates such as
    ``12/01/2026`` (issue #250), so a US user's ``MM/DD/YYYY`` data is not
    silently read as ``DD/MM/YYYY``. Unambiguous ISO dates (``YYYY-MM-DD``)
    are always parsed first and are unaffected by the preference.
    """
    if not value or not value.strip():
        return None
    value = value.strip()

    iso_formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y/%m/%d']

    if date_format == 'DD/MM/YYYY':
        formats = _ordered_slash_formats(prefer_mdy=False)
    elif date_format == 'MM/DD/YYYY':
        formats = _ordered_slash_formats(prefer_mdy=True)
    elif date_format == 'YYYY-MM-DD':
        formats = iso_formats
    else:
        # Auto-detect: unambiguous ISO first, then slash formats ordered by
        # the importing user's preference so US dates are not reversed.
        prefer_mdy = (user_date_format == 'MM/DD/YYYY')
        formats = iso_formats + _ordered_slash_formats(prefer_mdy)

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_time_value(value):
    """Parse a time string."""
    if not value or not value.strip():
        return None
    value = value.strip()
    for fmt in ['%H:%M:%S', '%H:%M', '%I:%M %p', '%I:%M:%S %p']:
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def parse_bool_value(value):
    """Parse a boolean-like value."""
    if not value:
        return False
    return str(value).strip().lower() in ('1', 'yes', 'true', 'y', 'on', 'full')


def parse_float_value(value):
    """Parse a CSV numeric value, stripping currency symbols and tolerating
    locale separators (#244).

    Uses :func:`app.utils.parse_decimal` (so ``9,99``, ``1.234,56`` and
    ``1,234.56`` all parse correctly) with one CSV-specific refinement: a
    single comma followed by exactly three digits with two or more digits
    before it (e.g. ``12,345``) is read as Anglo thousands grouping, which is
    how such values appear in exported odometer columns. A short integer part
    (e.g. the German fuel price ``1,899``) still reads the comma as a decimal
    separator.
    """
    if value is None or not str(value).strip():
        return None
    cleaned = str(value).strip()
    for ch in ['$', '\u20ac', '\u00a3', '\u00a5', '\u20b9']:
        cleaned = cleaned.replace(ch, '')
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    m = re.fullmatch(r'(-?\d{2,}),(\d{3})', cleaned)
    if m:
        cleaned = m.group(1) + m.group(2)
    return parse_decimal(cleaned)


def parse_int_value(value):
    """Parse an integer value."""
    f = parse_float_value(value)
    if f is None:
        return None
    return int(round(f))


def _cleanup_temp_file(path):
    """Remove a temp file safely."""
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


def create_record(data_type, mapped_row, vehicle_id, user_id, date_format, user_date_format=None):
    """Create a model instance from a mapped CSV row."""
    date_val = parse_date_value(mapped_row.get('date', ''), date_format, user_date_format)

    if data_type == 'fuel_logs':
        if not date_val:
            raise ValueError('Missing or invalid date')
        odometer = parse_float_value(mapped_row.get('odometer'))
        if odometer is None:
            raise ValueError('Missing or invalid odometer')
        return FuelLog(
            vehicle_id=vehicle_id,
            user_id=user_id,
            date=date_val,
            odometer=odometer,
            volume=parse_float_value(mapped_row.get('volume')),
            price_per_unit=parse_float_value(mapped_row.get('price_per_unit')),
            total_cost=parse_float_value(mapped_row.get('total_cost')),
            sales_tax=parse_float_value(mapped_row.get('sales_tax')),
            is_full_tank=parse_bool_value(mapped_row.get('is_full_tank')) if mapped_row.get('is_full_tank') else True,
            is_missed=parse_bool_value(mapped_row.get('is_missed')),
            station=mapped_row.get('station', '').strip() or None,
            notes=mapped_row.get('notes', '').strip() or None,
        )

    elif data_type == 'expenses':
        if not date_val:
            raise ValueError('Missing or invalid date')
        cost = parse_float_value(mapped_row.get('cost'))
        if cost is None:
            raise ValueError('Missing or invalid cost')
        description = mapped_row.get('description', '').strip()
        if not description:
            raise ValueError('Missing description')
        category = mapped_row.get('category', '').strip().lower()
        valid_categories = [c[0] for c in EXPENSE_CATEGORIES]
        if category not in valid_categories:
            category = 'other'
        return Expense(
            vehicle_id=vehicle_id,
            user_id=user_id,
            date=date_val,
            category=category,
            description=description,
            cost=cost,
            odometer=parse_float_value(mapped_row.get('odometer')),
            vendor=mapped_row.get('vendor', '').strip() or None,
            notes=mapped_row.get('notes', '').strip() or None,
        )

    elif data_type == 'trips':
        if not date_val:
            raise ValueError('Missing or invalid date')
        start_odo = parse_float_value(mapped_row.get('start_odometer'))
        end_odo = parse_float_value(mapped_row.get('end_odometer'))
        if start_odo is None:
            raise ValueError('Missing or invalid start odometer')
        if end_odo is None:
            raise ValueError('Missing or invalid end odometer')
        start_fuel = parse_fuel_level(parse_float_value(mapped_row.get('start_fuel_level')))
        end_fuel = parse_fuel_level(parse_float_value(mapped_row.get('end_fuel_level')))
        purpose = mapped_row.get('purpose', '').strip().lower()
        valid_purposes = [p[0] for p in TRIP_PURPOSES]
        if purpose not in valid_purposes:
            purpose = 'other'
        return Trip(
            vehicle_id=vehicle_id,
            user_id=user_id,
            date=date_val,
            start_odometer=start_odo,
            end_odometer=end_odo,
            start_fuel_level=start_fuel,
            end_fuel_level=end_fuel,
            purpose=purpose,
            description=mapped_row.get('description', '').strip() or None,
            start_location=mapped_row.get('start_location', '').strip() or None,
            end_location=mapped_row.get('end_location', '').strip() or None,
            notes=mapped_row.get('notes', '').strip() or None,
        )

    elif data_type == 'charging_sessions':
        if not date_val:
            raise ValueError('Missing or invalid date')
        charger_type = mapped_row.get('charger_type', '').strip().lower()
        valid_charger_types = [c[0] for c in CHARGER_TYPES]
        if charger_type and charger_type not in valid_charger_types:
            charger_type = 'other'
        return ChargingSession(
            vehicle_id=vehicle_id,
            user_id=user_id,
            date=date_val,
            start_time=parse_time_value(mapped_row.get('start_time')),
            end_time=parse_time_value(mapped_row.get('end_time')),
            odometer=parse_float_value(mapped_row.get('odometer')),
            kwh_added=parse_float_value(mapped_row.get('kwh_added')),
            start_soc=parse_int_value(mapped_row.get('start_soc')),
            end_soc=parse_int_value(mapped_row.get('end_soc')),
            cost_per_kwh=parse_float_value(mapped_row.get('cost_per_kwh')),
            total_cost=parse_float_value(mapped_row.get('total_cost')),
            charger_type=charger_type or None,
            location=mapped_row.get('location', '').strip() or None,
            network=mapped_row.get('network', '').strip() or None,
            notes=mapped_row.get('notes', '').strip() or None,
        )

    raise ValueError(f'Unknown data type: {data_type}')


DATA_TYPE_LABELS = {
    'fuel_logs': 'Fuel Logs',
    'expenses': 'Expenses',
    'trips': 'Trips',
    'charging_sessions': 'Charging Sessions',
}


@bp.route('/import/csv')
@login_required
def csv_import_upload():
    """CSV import - step 1: upload form."""
    vehicles = current_user.get_all_vehicles()
    if not vehicles:
        flash(_('Please add a vehicle before importing data.'), 'warning')
        return redirect(url_for('auth.settings') + '#integrations')
    return render_template('import/csv_upload.html', vehicles=vehicles)


@bp.route('/import/csv/preview', methods=['POST'])
@login_required
def csv_import_preview():
    """CSV import - step 2: parse CSV and show mapping page."""
    data_type = request.form.get('data_type')
    vehicle_id = request.form.get('vehicle_id', type=int)

    if data_type not in DATA_TYPE_LABELS:
        flash(_('Invalid data type selected.'), 'error')
        return redirect(url_for('api.csv_import_upload'))

    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        flash(_('Vehicle not found.'), 'error')
        return redirect(url_for('api.csv_import_upload'))

    if 'file' not in request.files or not request.files['file'].filename:
        flash(_('No CSV file uploaded.'), 'error')
        return redirect(url_for('api.csv_import_upload'))

    file = request.files['file']

    try:
        content = file.read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(content))
        csv_columns = reader.fieldnames

        if not csv_columns:
            flash(_('CSV file has no column headers.'), 'error')
            return redirect(url_for('api.csv_import_upload'))

        # Read all rows for counting, keep first 5 for preview
        all_rows = list(reader)
        preview_rows = all_rows[:5]

        # Build sample data (first non-empty value per column)
        sample_data = {}
        for col in csv_columns:
            for row in preview_rows:
                val = row.get(col, '').strip()
                if val:
                    sample_data[col] = val
                    break

        # Save CSV to temp file
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False,
                                          dir=current_app.instance_path if os.path.isdir(current_app.instance_path) else None)
        tmp.write(content)
        tmp.close()
        session['csv_import_temp_file'] = tmp.name

        target_fields = get_import_fields(data_type)
        suggestions = auto_suggest_mappings(csv_columns, target_fields)
        required_fields = [f for f in target_fields if f['required']]

        return render_template('import/csv_mapping.html',
                               data_type=data_type,
                               data_type_label=DATA_TYPE_LABELS[data_type],
                               vehicle_id=vehicle_id,
                               vehicle_name=vehicle.name,
                               csv_columns=csv_columns,
                               sample_data=sample_data,
                               preview_rows=preview_rows,
                               total_rows=len(all_rows),
                               target_fields=target_fields,
                               suggestions=suggestions,
                               required_fields=required_fields)

    except Exception as e:
        flash(_('Failed to parse CSV file: %(error)s') % {'error': str(e)}, 'error')
        return redirect(url_for('api.csv_import_upload'))


@bp.route('/import/csv/execute', methods=['POST'])
@login_required
def csv_import_execute():
    """CSV import - step 3: apply mapping and create records."""
    data_type = request.form.get('data_type')
    vehicle_id = request.form.get('vehicle_id', type=int)
    date_format = request.form.get('date_format', 'auto')
    temp_file = session.pop('csv_import_temp_file', None)

    if data_type not in DATA_TYPE_LABELS:
        flash(_('Invalid data type.'), 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        flash(_('Vehicle not found.'), 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    if not temp_file or not os.path.exists(temp_file):
        flash(_('CSV file expired. Please upload again.'), 'error')
        return redirect(url_for('api.csv_import_upload'))

    try:
        # Read temp CSV
        with open(temp_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
            reader = csv.DictReader(f)
            csv_columns = reader.fieldnames or []

            # Build column mapping from form: mapping_0, mapping_1, etc.
            col_mapping = {}
            for i, col in enumerate(csv_columns):
                field_name = request.form.get(f'mapping_{i}', '')
                if field_name:
                    col_mapping[col] = field_name

            rows = list(reader)

        imported = 0
        errors = []
        max_errors = 50

        for row_num, row in enumerate(rows, start=2):  # start=2 because row 1 is header
            try:
                mapped_row = {}
                for csv_col, field_name in col_mapping.items():
                    mapped_row[field_name] = row.get(csv_col, '')

                record = create_record(data_type, mapped_row, vehicle_id, current_user.id, date_format, current_user.date_format)
                db.session.add(record)
                imported += 1
            except (ValueError, KeyError) as e:
                if len(errors) < max_errors:
                    errors.append(f'Row {row_num}: {str(e)}')

        db.session.commit()

        label = DATA_TYPE_LABELS.get(data_type, data_type)
        flash(_('CSV import complete: %(count)s %(label)s imported.') % {'count': imported, 'label': label.lower()}, 'success')

        if errors:
            error_summary = f'{len(errors)} row(s) skipped due to errors.'
            if len(errors) <= 10:
                error_summary += ' ' + '; '.join(errors)
            else:
                error_summary += ' First 10: ' + '; '.join(errors[:10])
            flash(error_summary, 'warning')

    except Exception as e:
        db.session.rollback()
        flash(_('Import failed: %(error)s') % {'error': str(e)}, 'error')
    finally:
        _cleanup_temp_file(temp_file)

    return redirect(url_for('auth.settings') + '#integrations')


# =============================================================================
# May Backup Restore (JSON export or full ZIP backup)
# =============================================================================

BACKUP_RESTORE_SESSION_KEY = 'backup_restore_temp_file'


def _save_backup_upload(file):
    """Save an uploaded backup to a temp file and return its path."""
    suffix = '.zip' if (file.filename or '').lower().endswith('.zip') else '.json'
    tmp_dir = current_app.instance_path if os.path.isdir(current_app.instance_path) else None
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=tmp_dir) as tmp:
        file.save(tmp.name)
        return tmp.name


@bp.route('/import/backup')
@login_required
def backup_restore_upload():
    """Backup restore - step 1: upload form."""
    return render_template('import/backup_upload.html')


@bp.route('/import/backup/preview', methods=['POST'])
@login_required
def backup_restore_preview():
    """Backup restore - step 2: show what would be added before anything is written."""
    if 'file' not in request.files or not request.files['file'].filename:
        flash(_('No backup file uploaded.'), 'error')
        return redirect(url_for('api.backup_restore_upload'))

    # Drop any backup left over from an abandoned restore
    _cleanup_temp_file(session.pop(BACKUP_RESTORE_SESSION_KEY, None))

    tmp_path = _save_backup_upload(request.files['file'])

    try:
        data, zip_path = read_backup(tmp_path)
        summary = restore_backup(
            data, current_user,
            zip_path=zip_path,
            upload_folder=current_app.config['UPLOAD_FOLDER'],
            dry_run=True
        )
    except BackupError as e:
        _cleanup_temp_file(tmp_path)
        flash(str(e), 'error')
        return redirect(url_for('api.backup_restore_upload'))
    except Exception as e:
        _cleanup_temp_file(tmp_path)
        logger.error("Backup restore preview failed: %s\n%s", e, traceback.format_exc())
        flash(_('Could not read that backup: %(error)s') % {'error': e}, 'error')
        return redirect(url_for('api.backup_restore_upload'))

    session[BACKUP_RESTORE_SESSION_KEY] = tmp_path

    return render_template('import/backup_preview.html',
                           summary=summary,
                           section_labels=SECTION_LABELS,
                           backup_info=describe_backup(data),
                           is_full_backup=zip_path is not None)


@bp.route('/import/backup/execute', methods=['POST'])
@login_required
def backup_restore_execute():
    """Backup restore - step 3: merge the backup into the current account."""
    tmp_path = session.pop(BACKUP_RESTORE_SESSION_KEY, None)

    if not tmp_path or not os.path.exists(tmp_path):
        flash(_('The uploaded backup has expired. Please upload it again.'), 'error')
        return redirect(url_for('api.backup_restore_upload'))

    try:
        data, zip_path = read_backup(tmp_path)
        summary = restore_backup(
            data, current_user,
            zip_path=zip_path,
            upload_folder=current_app.config['UPLOAD_FOLDER'],
            dry_run=False
        )
        logger.info("Backup restore finished for user %s: %s added, %s already present",
                    current_user.id, summary['total_added'], summary['total_skipped'])
        flash(_('Backup restored: %(added)s records added, %(skipped)s already present and left alone.') % {
            'added': summary['total_added'], 'skipped': summary['total_skipped']}, 'success')
    except BackupError as e:
        flash(str(e), 'error')
        return redirect(url_for('api.backup_restore_upload'))
    except Exception as e:
        db.session.rollback()
        logger.error("Backup restore failed: %s\n%s", e, traceback.format_exc())
        flash(_('Restore failed: %(error)s') % {'error': e}, 'error')
    finally:
        _cleanup_temp_file(tmp_path)

    return redirect(url_for('auth.settings') + '#integrations')
