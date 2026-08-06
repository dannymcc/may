from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db, DATE_FORMATS
from app.models import Reminder, Vehicle, REMINDER_TYPES, RECURRENCE_OPTIONS

bp = Blueprint('reminders', __name__, url_prefix='/reminders')


@bp.route('/')
@login_required
def index():
    """List all reminders for the user's vehicles"""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    # Get filter parameters
    show_completed = request.args.get('completed', 'false') == 'true'
    filter_type = request.args.get('type')
    filter_vehicle = request.args.get('vehicle', type=int)

    # Build query
    query = Reminder.query.filter(Reminder.vehicle_id.in_(vehicle_ids))

    if not show_completed:
        query = query.filter_by(is_completed=False)

    if filter_type:
        query = query.filter_by(reminder_type=filter_type)

    if filter_vehicle:
        query = query.filter_by(vehicle_id=filter_vehicle)

    # Split reminders into categories
    all_reminders = query.order_by(Reminder.due_date).all()

    overdue = [r for r in all_reminders if r.is_overdue()]
    upcoming = [r for r in all_reminders if r.is_upcoming(days=30) and not r.is_overdue()]
    later = [r for r in all_reminders if not r.is_overdue() and not r.is_upcoming(days=30)]
    completed = [r for r in all_reminders if r.is_completed] if show_completed else []

    return render_template('reminders/index.html',
                           overdue=overdue,
                           upcoming=upcoming,
                           later=later,
                           completed=completed,
                           vehicles=vehicles,
                           reminder_types=REMINDER_TYPES,
                           show_completed=show_completed,
                           filter_type=filter_type,
                           filter_vehicle=filter_vehicle)


@bp.route('/new', methods=['GET', 'POST'])
@bp.route('/new/<int:vehicle_id>', methods=['GET', 'POST'])
@login_required
def new(vehicle_id=None):
    """Create a new reminder"""
    vehicles = current_user.get_all_vehicles()

    if not vehicles:
        flash(_('Please add a vehicle first'), 'error')
        return redirect(url_for('vehicles.index'))

    if request.method == 'POST':
        vehicle_id = int(request.form.get('vehicle_id'))
        vehicle = Vehicle.query.get_or_404(vehicle_id)

        if vehicle not in vehicles:
            flash(_('Access denied'), 'error')
            return redirect(url_for('reminders.index'))

        try:
            due_date = datetime.strptime(request.form.get('due_date'), '%Y-%m-%d').date()
        except ValueError:
            flash(_('Invalid date format'), 'error')
            return redirect(url_for('reminders.new', vehicle_id=vehicle_id))

        reminder = Reminder(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            title=request.form.get('title'),
            description=request.form.get('description'),
            reminder_type=request.form.get('reminder_type'),
            due_date=due_date,
            recurrence=request.form.get('recurrence', 'none'),
            recurrence_interval=max(int(request.form.get('recurrence_interval') or 1), 1),
            notify_days_before=int(request.form.get('notify_days_before', 7))
        )

        db.session.add(reminder)
        db.session.commit()

        flash(_('Reminder "%(title)s" created successfully') % {'title': reminder.title}, 'success')

        # Redirect back to vehicle page if we came from there
        if request.form.get('return_to') == 'vehicle':
            return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

        return redirect(url_for('reminders.index'))

    # Pre-select vehicle if provided
    selected_vehicle = None
    if vehicle_id:
        selected_vehicle = Vehicle.query.get(vehicle_id)
        if selected_vehicle not in vehicles:
            selected_vehicle = None

    return render_template('reminders/form.html',
                           reminder=None,
                           vehicles=vehicles,
                           selected_vehicle=selected_vehicle,
                           reminder_types=REMINDER_TYPES,
                           recurrence_options=RECURRENCE_OPTIONS)


@bp.route('/<int:reminder_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(reminder_id):
    """Edit an existing reminder"""
    reminder = Reminder.query.get_or_404(reminder_id)
    vehicles = current_user.get_all_vehicles()

    if reminder.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('reminders.index'))

    if request.method == 'POST':
        try:
            due_date = datetime.strptime(request.form.get('due_date'), '%Y-%m-%d').date()
        except ValueError:
            flash(_('Invalid date format'), 'error')
            return redirect(url_for('reminders.edit', reminder_id=reminder_id))

        reminder.title = request.form.get('title')
        reminder.description = request.form.get('description')
        reminder.reminder_type = request.form.get('reminder_type')
        reminder.due_date = due_date
        reminder.recurrence = request.form.get('recurrence', 'none')
        reminder.recurrence_interval = max(int(request.form.get('recurrence_interval') or 1), 1)
        reminder.notify_days_before = int(request.form.get('notify_days_before', 7))

        db.session.commit()
        flash(_('Reminder updated successfully'), 'success')
        return redirect(url_for('reminders.index'))

    return render_template('reminders/form.html',
                           reminder=reminder,
                           vehicles=vehicles,
                           selected_vehicle=reminder.vehicle,
                           reminder_types=REMINDER_TYPES,
                           recurrence_options=RECURRENCE_OPTIONS)


@bp.route('/<int:reminder_id>/complete', methods=['POST'])
@login_required
def complete(reminder_id):
    """Mark a reminder as completed"""
    reminder = Reminder.query.get_or_404(reminder_id)
    vehicles = current_user.get_all_vehicles()

    if reminder.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('reminders.index'))

    reminder.is_completed = True
    reminder.completed_at = datetime.utcnow()

    # If recurring, create the next occurrence
    if reminder.recurrence != 'none':
        new_due_date = calculate_next_due_date(reminder.due_date, reminder.recurrence, reminder.recurrence_interval)

        # Guard against duplicates (#232): if the reminder was completed,
        # un-completed and completed again, a matching open next occurrence
        # may already exist. Only create one if none is present.
        existing = Reminder.query.filter_by(
            vehicle_id=reminder.vehicle_id,
            user_id=reminder.user_id,
            title=reminder.title,
            reminder_type=reminder.reminder_type,
            recurrence=reminder.recurrence,
            recurrence_interval=reminder.recurrence_interval,
            due_date=new_due_date,
            is_completed=False,
        ).first()

        user_format = getattr(current_user, 'date_format', None) or 'DD/MM/YYYY'
        fmt = DATE_FORMATS.get(user_format, DATE_FORMATS['DD/MM/YYYY'])['default']

        if existing:
            flash(_('Reminder marked as completed'), 'success')
        else:
            new_reminder = Reminder(
                vehicle_id=reminder.vehicle_id,
                user_id=reminder.user_id,
                title=reminder.title,
                description=reminder.description,
                reminder_type=reminder.reminder_type,
                due_date=new_due_date,
                recurrence=reminder.recurrence,
                recurrence_interval=reminder.recurrence_interval,
                notify_days_before=reminder.notify_days_before
            )
            db.session.add(new_reminder)
            flash(_('Reminder completed. Next occurrence created for %(date)s') % {'date': new_due_date.strftime(fmt)}, 'success')
    else:
        flash(_('Reminder marked as completed'), 'success')

    db.session.commit()

    # Redirect back to referrer if available
    return_to = request.args.get('return_to')
    if return_to == 'vehicle':
        return redirect(url_for('vehicles.view', vehicle_id=reminder.vehicle_id))

    return redirect(url_for('reminders.index'))


@bp.route('/<int:reminder_id>/uncomplete', methods=['POST'])
@login_required
def uncomplete(reminder_id):
    """Mark a completed reminder as not completed"""
    reminder = Reminder.query.get_or_404(reminder_id)
    vehicles = current_user.get_all_vehicles()

    if reminder.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('reminders.index'))

    reminder.is_completed = False
    reminder.completed_at = None
    db.session.commit()

    flash(_('Reminder marked as not completed'), 'success')
    return redirect(url_for('reminders.index'))


@bp.route('/<int:reminder_id>/delete', methods=['POST'])
@login_required
def delete(reminder_id):
    """Delete a reminder"""
    reminder = Reminder.query.get_or_404(reminder_id)
    vehicles = current_user.get_all_vehicles()

    if reminder.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('reminders.index'))

    vehicle_id = reminder.vehicle_id
    db.session.delete(reminder)
    db.session.commit()

    flash(_('Reminder deleted'), 'success')

    # Redirect back to referrer if available
    return_to = request.args.get('return_to')
    if return_to == 'vehicle':
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    return redirect(url_for('reminders.index'))


def calculate_next_due_date(current_date, recurrence, interval=1):
    """Calculate the next due date for the given recurrence unit and interval.

    Accepts the current unit-based vocabulary (daily, weekly, monthly, yearly)
    and the legacy values (quarterly = 3 months, biannual = 6 months) so old
    reminders keep working until they're edited.
    """
    from dateutil.relativedelta import relativedelta

    step = max(int(interval or 1), 1)

    if recurrence == 'daily':
        return current_date + relativedelta(days=step)
    if recurrence == 'weekly':
        return current_date + relativedelta(weeks=step)
    if recurrence == 'monthly':
        return current_date + relativedelta(months=step)
    if recurrence == 'yearly':
        return current_date + relativedelta(years=step)
    # Legacy fixed-interval values from pre-0.22.4 reminders.
    if recurrence == 'quarterly':
        return current_date + relativedelta(months=3 * step)
    if recurrence == 'biannual':
        return current_date + relativedelta(months=6 * step)

    return current_date
