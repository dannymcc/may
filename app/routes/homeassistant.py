"""Home Assistant Integration API endpoints.

These endpoints provide REST API access for Home Assistant integration.
Configure in Home Assistant using the RESTful integration or custom sensors.

Example Home Assistant configuration (configuration.yaml):

```yaml
rest:
  - resource: http://your-may-server:5000/api/ha/vehicles
    headers:
      Authorization: Bearer YOUR_API_TOKEN
    sensor:
      - name: "May Vehicles Count"
        value_template: "{{ value_json.count }}"

sensor:
  - platform: rest
    name: "Car Fuel Economy"
    resource: http://your-may-server:5000/api/ha/vehicles/1/stats
    headers:
      Authorization: Bearer YOUR_API_TOKEN
    value_template: "{{ value_json.avg_consumption }}"
    unit_of_measurement: "L/100km"
    json_attributes:
      - total_distance
      - total_fuel
      - total_cost
```
"""

from flask import Blueprint, jsonify, request, current_app
from functools import wraps
from app import db
from app.models import (
    User, Vehicle, FuelLog, Expense, MaintenanceSchedule,
    RecurringExpense, Document, Reminder
)
from datetime import date, timedelta
from sqlalchemy import func
from config import APP_VERSION

bp = Blueprint('homeassistant', __name__, url_prefix='/api/ha')


def token_required(f):
    """Decorator to require API token authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'Authorization header required'}), 401

        try:
            scheme, token = auth_header.split(' ', 1)
            if scheme.lower() != 'bearer':
                return jsonify({'error': 'Bearer token required'}), 401
        except ValueError:
            return jsonify({'error': 'Invalid authorization header'}), 401

        # Find user by API token
        user = User.query.filter_by(api_key=token).first()
        if not user:
            return jsonify({'error': 'Invalid API token'}), 401

        # Add user to kwargs for route access
        kwargs['user'] = user
        return f(*args, **kwargs)
    return decorated


@bp.route('/status')
@token_required
def status(user):
    """Health check endpoint for Home Assistant availability sensor."""
    return jsonify({
        'status': 'online',
        'user': user.username,
        'version': APP_VERSION
    })


@bp.route('/vehicles')
@token_required
def vehicles(user):
    """List all vehicles with basic stats."""
    vehicles = Vehicle.query.filter_by(owner_id=user.id).all()

    result = {
        'count': len(vehicles),
        'vehicles': []
    }

    for v in vehicles:
        # Get latest odometer reading
        latest_log = FuelLog.query.filter_by(vehicle_id=v.id).order_by(
            FuelLog.odometer.desc()
        ).first()

        vehicle_data = {
            'id': v.id,
            'name': v.name,
            'make': v.make,
            'model': v.model,
            'year': v.year,
            'registration': v.registration,
            'fuel_type': v.fuel_type,
            'current_odometer': latest_log.odometer if latest_log else 0,
            'unit_distance': user.distance_unit,
            'unit_volume': user.volume_unit,
            'currency': user.currency
        }
        result['vehicles'].append(vehicle_data)

    return jsonify(result)


@bp.route('/vehicles/<int:vehicle_id>')
@token_required
def vehicle_detail(vehicle_id, user):
    """Get detailed vehicle information."""
    vehicle = Vehicle.query.filter_by(id=vehicle_id, owner_id=user.id).first()
    if not vehicle:
        return jsonify({'error': 'Vehicle not found'}), 404

    # Get latest odometer reading
    latest_log = FuelLog.query.filter_by(vehicle_id=vehicle.id).order_by(
        FuelLog.odometer.desc()
    ).first()

    return jsonify({
        'id': vehicle.id,
        'name': vehicle.name,
        'make': vehicle.make,
        'model': vehicle.model,
        'year': vehicle.year,
        'registration': vehicle.registration,
        'fuel_type': vehicle.fuel_type,
        'current_odometer': latest_log.odometer if latest_log else 0,
        'unit_distance': user.distance_unit,
        'unit_volume': user.volume_unit,
        'currency': user.currency
    })


@bp.route('/vehicles/<int:vehicle_id>/stats')
@token_required
def vehicle_stats(vehicle_id, user):
    """Get vehicle statistics for Home Assistant sensors."""
    vehicle = Vehicle.query.filter_by(id=vehicle_id, owner_id=user.id).first()
    if not vehicle:
        return jsonify({'error': 'Vehicle not found'}), 404

    # Time period for stats (default: all time, or specify ?days=30)
    days = request.args.get('days', type=int)
    if days:
        since_date = date.today() - timedelta(days=days)
        fuel_query = FuelLog.query.filter(
            FuelLog.vehicle_id == vehicle.id,
            FuelLog.date >= since_date
        )
        expense_query = Expense.query.filter(
            Expense.vehicle_id == vehicle.id,
            Expense.date >= since_date
        )
    else:
        fuel_query = FuelLog.query.filter_by(vehicle_id=vehicle.id)
        expense_query = Expense.query.filter_by(vehicle_id=vehicle.id)

    # Calculate fuel stats
    fuel_logs = fuel_query.order_by(FuelLog.odometer.asc()).all()

    total_fuel = sum(log.volume for log in fuel_logs)
    total_fuel_cost = sum(log.total_cost for log in fuel_logs)

    # Calculate distance driven
    if len(fuel_logs) >= 2:
        total_distance = fuel_logs[-1].odometer - fuel_logs[0].odometer
    else:
        total_distance = 0

    # Calculate average consumption
    # Skip first fill for consumption calculation (don't know previous fill level)
    if len(fuel_logs) >= 2 and total_distance > 0:
        consumption_fuel = sum(log.volume for log in fuel_logs[1:])
        if user.distance_unit == 'mi':
            # MPG (higher is better)
            avg_consumption = total_distance / consumption_fuel if consumption_fuel > 0 else 0
        else:
            # L/100km (lower is better)
            avg_consumption = (consumption_fuel / total_distance) * 100 if total_distance > 0 else 0
    else:
        avg_consumption = 0

    # Calculate expense totals
    total_expenses = expense_query.with_entities(func.sum(Expense.cost)).scalar() or 0

    # Get last fill date
    last_fill = FuelLog.query.filter_by(vehicle_id=vehicle.id).order_by(
        FuelLog.date.desc()
    ).first()

    # Get current odometer
    latest_log = FuelLog.query.filter_by(vehicle_id=vehicle.id).order_by(
        FuelLog.odometer.desc()
    ).first()

    return jsonify({
        'vehicle_id': vehicle.id,
        'vehicle_name': vehicle.name,
        'period_days': days if days else 'all',
        'total_distance': round(total_distance, 1),
        'total_fuel': round(total_fuel, 2),
        'total_fuel_cost': round(total_fuel_cost, 2),
        'total_expenses': round(float(total_expenses), 2),
        'total_cost': round(total_fuel_cost + float(total_expenses), 2),
        'avg_consumption': round(avg_consumption, 2),
        'consumption_unit': 'mpg' if user.distance_unit == 'mi' else 'L/100km',
        'fill_count': len(fuel_logs),
        'last_fill_date': last_fill.date.isoformat() if last_fill else None,
        'last_fill_volume': last_fill.volume if last_fill else None,
        'last_fill_cost': last_fill.total_cost if last_fill else None,
        'current_odometer': latest_log.odometer if latest_log else 0,
        'distance_unit': user.distance_unit,
        'volume_unit': user.volume_unit,
        'currency': user.currency,
        'currency_symbol': vehicle.currency_symbol
    })


@bp.route('/alerts')
@token_required
def alerts(user):
    """Get all active alerts for Home Assistant binary sensors."""
    alerts = []

    # Check maintenance schedules
    schedules = MaintenanceSchedule.query.join(Vehicle).filter(
        Vehicle.owner_id == user.id,
        MaintenanceSchedule.is_active == True
    ).all()

    for schedule in schedules:
        current_odometer = schedule.vehicle.get_last_odometer()
        is_due = schedule.is_due(current_odometer)
        date_overdue = bool(schedule.next_due_date and schedule.next_due_date < date.today())
        odometer_overdue = bool(
            schedule.next_due_odometer is not None and
            current_odometer is not None and
            current_odometer > schedule.next_due_odometer
        )

        if is_due:
            alerts.append({
                'type': 'maintenance',
                'vehicle': schedule.vehicle.name,
                'title': schedule.name,
                'status': 'overdue' if (date_overdue or odometer_overdue) else 'due',
                'due_odometer': schedule.next_due_odometer,
                'due_date': schedule.next_due_date.isoformat() if schedule.next_due_date else None
            })

    # Check recurring expenses
    recurring = RecurringExpense.query.join(Vehicle).filter(
        Vehicle.owner_id == user.id,
        RecurringExpense.is_active == True
    ).all()

    for item in recurring:
        if item.is_due():
            alerts.append({
                'type': 'recurring_expense',
                'vehicle': item.vehicle.name,
                'title': item.name,
                'status': 'due',
                'due_date': item.next_due.isoformat() if item.next_due else None,
                'amount': item.amount
            })

    # Check expiring documents
    documents = Document.query.join(Vehicle).filter(
        Vehicle.owner_id == user.id
    ).all()

    for doc in documents:
        if doc.is_expired():
            alerts.append({
                'type': 'document',
                'vehicle': doc.vehicle.name,
                'title': doc.title,
                'status': 'expired',
                'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None
            })
        elif doc.is_expiring_soon():
            alerts.append({
                'type': 'document',
                'vehicle': doc.vehicle.name,
                'title': doc.title,
                'status': 'expiring_soon',
                'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None
            })

    # Check reminders
    reminders = Reminder.query.join(Vehicle).filter(
        Vehicle.owner_id == user.id,
        Reminder.is_completed == False
    ).all()

    for reminder in reminders:
        if reminder.is_overdue():
            alerts.append({
                'type': 'reminder',
                'vehicle': reminder.vehicle.name,
                'title': reminder.title,
                'status': 'overdue',
                'due_date': reminder.due_date.isoformat() if reminder.due_date else None
            })
        elif reminder.is_upcoming(reminder.notify_days_before or 7):
            alerts.append({
                'type': 'reminder',
                'vehicle': reminder.vehicle.name,
                'title': reminder.title,
                'status': 'upcoming',
                'due_date': reminder.due_date.isoformat() if reminder.due_date else None
            })

    return jsonify({
        'count': len(alerts),
        'has_alerts': len(alerts) > 0,
        'alerts': alerts
    })


@bp.route('/summary')
@token_required
def summary(user):
    """Get overall summary for Home Assistant dashboard."""
    vehicles = Vehicle.query.filter_by(owner_id=user.id).all()

    # Calculate totals
    total_vehicles = len(vehicles)
    total_distance = 0
    total_fuel_cost = 0
    total_expenses = 0
    alerts_count = 0

    for vehicle in vehicles:
        # Get fuel stats
        fuel_logs = FuelLog.query.filter_by(vehicle_id=vehicle.id).order_by(
            FuelLog.odometer.asc()
        ).all()

        if len(fuel_logs) >= 2:
            total_distance += fuel_logs[-1].odometer - fuel_logs[0].odometer

        total_fuel_cost += sum(log.total_cost for log in fuel_logs)

        # Get expense totals
        expenses = Expense.query.filter_by(vehicle_id=vehicle.id).with_entities(
            func.sum(Expense.cost)
        ).scalar() or 0
        total_expenses += float(expenses)

    # Count alerts
    alerts_response = alerts(user=user)
    alerts_data = alerts_response.get_json()
    alerts_count = alerts_data.get('count', 0)

    return jsonify({
        'total_vehicles': total_vehicles,
        'total_distance': round(total_distance, 1),
        'total_fuel_cost': round(total_fuel_cost, 2),
        'total_expenses': round(total_expenses, 2),
        'total_cost': round(total_fuel_cost + total_expenses, 2),
        'alerts_count': alerts_count,
        'has_alerts': alerts_count > 0
    })


@bp.route('/fuel/add', methods=['POST'])
@token_required
def add_fuel(user):
    """Add a fuel log entry via API (for Home Assistant automations)."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    required_fields = ['vehicle_id', 'date', 'odometer', 'volume', 'price_per_unit', 'total_cost']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    # Verify vehicle belongs to user
    vehicle = Vehicle.query.filter_by(id=data['vehicle_id'], owner_id=user.id).first()
    if not vehicle:
        return jsonify({'error': 'Vehicle not found'}), 404

    try:
        fuel_log = FuelLog(
            vehicle_id=data['vehicle_id'],
            user_id=user.id,
            date=date.fromisoformat(data['date']),
            odometer=float(data['odometer']),
            volume=float(data['volume']),
            price_per_unit=float(data['price_per_unit']),
            total_cost=float(data['total_cost']),
            is_full_tank=data.get('is_full_tank', True),
            notes=data.get('notes', '')
        )

        db.session.add(fuel_log)
        db.session.commit()

        return jsonify({
            'success': True,
            'id': fuel_log.id,
            'message': 'Fuel log added successfully'
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
