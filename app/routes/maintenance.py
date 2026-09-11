from datetime import datetime, date
from types import SimpleNamespace
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db
from app.utils import parse_decimal
from app.models import (
    Vehicle, MaintenanceSchedule, MaintenanceEvent, Expense, MAINTENANCE_TYPES, EXPENSE_CATEGORIES
)

bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')


def _record_completion(schedule):
    """Preserve a known last-performed snapshot without duplicating a repeated save."""
    if schedule.last_performed_date is None and schedule.last_performed_odometer is None:
        return
    db.session.flush()
    existing = schedule.events.filter_by(
        performed_date=schedule.last_performed_date,
        odometer=schedule.last_performed_odometer,
    ).first()
    if existing is None:
        db.session.add(MaintenanceEvent(
            vehicle_id=schedule.vehicle_id, user_id=current_user.id,
            schedule_id=schedule.id, name=schedule.name,
            maintenance_type=schedule.maintenance_type,
            performed_date=schedule.last_performed_date,
            odometer=schedule.last_performed_odometer,
            notes=schedule.description,
        ))


@bp.route('/history')
@login_required
def history():
    vehicles = current_user.get_all_vehicles()
    vehicle_id = request.args.get('vehicle_id', type=int)
    ids = [v.id for v in vehicles]
    if vehicle_id is not None:
        if vehicle_id not in ids:
            from flask import abort
            abort(403)
        ids = [vehicle_id]
    events = MaintenanceEvent.query.filter(MaintenanceEvent.vehicle_id.in_(ids)).order_by(
        MaintenanceEvent.performed_date.desc(), MaintenanceEvent.id.desc()).all()
    # Existing maintenance expenses are also historical service records.
    known = {(e.vehicle_id, e.name, e.performed_date, e.odometer) for e in events}
    for expense in Expense.query.filter(Expense.vehicle_id.in_(ids), Expense.category == 'maintenance').all():
        key = (expense.vehicle_id, expense.description, expense.date, expense.odometer)
        if key not in known:
            events.append(SimpleNamespace(
                id=None, vehicle=expense.vehicle, name=expense.description or _('Maintenance'),
                maintenance_type='custom', performed_date=expense.date,
                odometer=expense.odometer, notes=expense.notes,
            ))
    events.sort(key=lambda e: (e.performed_date or date.min, e.id or 0), reverse=True)
    return render_template('maintenance/history.html', events=events, vehicles=vehicles,
                           selected_vehicle_id=vehicle_id)


@bp.route('/')
@login_required
def index():
    """List all maintenance schedules"""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    schedules = MaintenanceSchedule.query.filter(
        MaintenanceSchedule.vehicle_id.in_(vehicle_ids),
        MaintenanceSchedule.is_active == True
    ).order_by(MaintenanceSchedule.next_due_date).all()

    # Get current odometer for each vehicle
    vehicle_odometers = {}
    for v in vehicles:
        vehicle_odometers[v.id] = v.get_last_odometer()

    return render_template('maintenance/index.html',
                           schedules=schedules,
                           vehicles=vehicles,
                           vehicle_odometers=vehicle_odometers,
                           maintenance_types=MAINTENANCE_TYPES)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Create a new maintenance schedule"""
    vehicles = current_user.get_all_vehicles()

    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id')
        vehicle = db.session.get(Vehicle, vehicle_id)

        if not vehicle or vehicle not in vehicles:
            flash(_('Invalid vehicle'), 'error')
            return redirect(url_for('maintenance.index'))

        schedule = MaintenanceSchedule(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            name=request.form.get('name'),
            maintenance_type=request.form.get('maintenance_type'),
            description=request.form.get('description'),
            interval_km=int(request.form.get('interval_km')) if request.form.get('interval_km') else None,
            interval_miles=int(request.form.get('interval_miles')) if request.form.get('interval_miles') else None,
            interval_hours=int(request.form.get('interval_hours')) if request.form.get('interval_hours') else None,
            interval_months=int(request.form.get('interval_months')) if request.form.get('interval_months') else None,
            estimated_cost=parse_decimal(request.form.get('estimated_cost')) if request.form.get('estimated_cost') else None,
            auto_remind=request.form.get('auto_remind') == 'on',
            remind_days_before=int(request.form.get('remind_days_before') or 14),
        )

        # Set last performed if provided
        if request.form.get('last_performed_date'):
            schedule.last_performed_date = datetime.strptime(
                request.form.get('last_performed_date'), '%Y-%m-%d'
            ).date()
        if request.form.get('last_performed_odometer'):
            schedule.last_performed_odometer = parse_decimal(request.form.get('last_performed_odometer'))

        # Calculate next due
        schedule.calculate_next_due()

        # If no next_due_date calculated but we have interval_months and no last date, set from today
        if not schedule.next_due_date and schedule.interval_months:
            from dateutil.relativedelta import relativedelta
            schedule.next_due_date = date.today() + relativedelta(months=schedule.interval_months)

        db.session.add(schedule)
        _record_completion(schedule)
        db.session.commit()

        flash(_('Maintenance schedule "%(name)s" created') % {'name': schedule.name}, 'success')
        return redirect(url_for('maintenance.index'))

    # Pre-select vehicle if passed in URL
    selected_vehicle = request.args.get('vehicle_id')

    return render_template('maintenance/form.html',
                           schedule=None,
                           vehicles=vehicles,
                           selected_vehicle=selected_vehicle,
                           maintenance_types=MAINTENANCE_TYPES)


@bp.route('/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(schedule_id):
    """Edit a maintenance schedule"""
    schedule = db.get_or_404(MaintenanceSchedule, schedule_id)
    vehicles = current_user.get_all_vehicles()

    if schedule.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('maintenance.index'))

    if request.method == 'POST':
        _record_completion(schedule)
        schedule.name = request.form.get('name')
        schedule.maintenance_type = request.form.get('maintenance_type')
        schedule.description = request.form.get('description')
        schedule.interval_km = int(request.form.get('interval_km')) if request.form.get('interval_km') else None
        schedule.interval_miles = int(request.form.get('interval_miles')) if request.form.get('interval_miles') else None
        schedule.interval_hours = int(request.form.get('interval_hours')) if request.form.get('interval_hours') else None
        schedule.interval_months = int(request.form.get('interval_months')) if request.form.get('interval_months') else None
        schedule.estimated_cost = parse_decimal(request.form.get('estimated_cost')) if request.form.get('estimated_cost') else None
        schedule.auto_remind = request.form.get('auto_remind') == 'on'
        schedule.remind_days_before = int(request.form.get('remind_days_before') or 14)

        if request.form.get('last_performed_date'):
            schedule.last_performed_date = datetime.strptime(
                request.form.get('last_performed_date'), '%Y-%m-%d'
            ).date()
        if request.form.get('last_performed_odometer'):
            schedule.last_performed_odometer = parse_decimal(request.form.get('last_performed_odometer'))

        schedule.calculate_next_due()
        _record_completion(schedule)
        db.session.commit()

        flash(_('Maintenance schedule updated'), 'success')
        return redirect(url_for('maintenance.index'))

    return render_template('maintenance/form.html',
                           schedule=schedule,
                           vehicles=vehicles,
                           selected_vehicle=schedule.vehicle_id,
                           maintenance_types=MAINTENANCE_TYPES)


@bp.route('/<int:schedule_id>/complete', methods=['POST'])
@login_required
def complete(schedule_id):
    """Mark maintenance as completed and optionally create expense"""
    schedule = db.get_or_404(MaintenanceSchedule, schedule_id)
    vehicles = current_user.get_all_vehicles()

    if schedule.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('maintenance.index'))

    _record_completion(schedule)

    # Update last performed — honouring a user-chosen completion date (#220)
    performed_date = date.today()
    if request.form.get('performed_date'):
        try:
            performed_date = datetime.strptime(
                request.form.get('performed_date'), '%Y-%m-%d'
            ).date()
        except ValueError:
            pass
    schedule.last_performed_date = performed_date
    if request.form.get('odometer'):
        schedule.last_performed_odometer = parse_decimal(request.form.get('odometer'))
    else:
        schedule.last_performed_odometer = schedule.vehicle.get_last_odometer()

    # Calculate next due
    schedule.calculate_next_due()

    _record_completion(schedule)

    # Create expense if requested
    if request.form.get('create_expense') == 'on':
        # The checkbox is an explicit request: zero-cost DIY jobs still get an
        # expense entry so they appear in the vehicle's history (#271).
        cost = parse_decimal(request.form.get('actual_cost') or schedule.estimated_cost or 0)
        expense = Expense(
            vehicle_id=schedule.vehicle_id,
            user_id=current_user.id,
            date=performed_date,
            category='maintenance',
            description=schedule.name,
            cost=cost,
            odometer=schedule.last_performed_odometer,
            vendor=request.form.get('vendor'),
            notes=f'From maintenance schedule: {schedule.name}'
        )
        db.session.add(expense)

    db.session.commit()
    flash(_('Maintenance "%(name)s" marked as completed') % {'name': schedule.name}, 'success')
    return redirect(url_for('maintenance.index'))


@bp.route('/<int:schedule_id>/delete', methods=['POST'])
@login_required
def delete(schedule_id):
    """Delete a maintenance schedule"""
    schedule = db.get_or_404(MaintenanceSchedule, schedule_id)
    vehicles = current_user.get_all_vehicles()

    if schedule.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('maintenance.index'))

    _record_completion(schedule)
    name = schedule.name
    db.session.delete(schedule)
    db.session.commit()

    flash(_('Maintenance schedule "%(name)s" deleted') % {'name': name}, 'success')
    return redirect(url_for('maintenance.index'))
