import os
import uuid
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from flask_babel import gettext as _
from sqlalchemy import func
from app import db
from app.utils import parse_decimal
from app.models import Vehicle, Expense, Attachment, MaintenanceSchedule, Reminder, EXPENSE_CATEGORIES
from app.routes.reminders import complete_reminder

bp = Blueprint('expenses', __name__, url_prefix='/expenses')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def parse_optional_float(value):
    """Parse an optional numeric form field, treating blank or literal
    'None' strings as an absent value rather than a parse error."""
    if value is None or value.strip() == '' or value.strip() == 'None':
        return None
    return parse_decimal(value)


def _save_attachments(expense, files):
    """Save uploaded receipts against an expense (#234).

    Accepts any number of files, ignores empty file inputs, and returns the
    names of the files skipped because of a disallowed extension so the
    caller can tell the user rather than dropping them silently.
    """
    skipped = []
    for file in files:
        if not file or not file.filename:
            continue
        if not allowed_file(file.filename):
            skipped.append(file.filename)
            continue

        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

        db.session.add(Attachment(
            filename=filename,
            original_filename=file.filename,
            file_type=file.filename.rsplit('.', 1)[1].lower(),
            expense_id=expense.id
        ))
    return skipped


def _flash_skipped_attachments(skipped):
    if skipped:
        flash(_('These files were not saved because the file type is not '
                'supported: %(names)s') % {'names': ', '.join(skipped)}, 'warning')


def _attachments_by_expense(expense_ids):
    """Attachments for the listed expenses, keyed by expense id.

    Expense.attachments is lazy='dynamic', so loading them in the template
    would run one query per row.
    """
    grouped = {}
    if not expense_ids:
        return grouped
    attachments = Attachment.query.filter(
        Attachment.expense_id.in_(expense_ids)
    ).order_by(Attachment.id).all()
    for attachment in attachments:
        grouped.setdefault(attachment.expense_id, []).append(attachment)
    return grouped


def _known_vendors(vehicle_ids):
    """Distinct vendors previously used on the user's expenses (#213)."""
    if not vehicle_ids:
        return []
    rows = db.session.query(Expense.vendor).filter(
        Expense.vehicle_id.in_(vehicle_ids),
        Expense.vendor.isnot(None),
        Expense.vendor != '',
    ).distinct().order_by(Expense.vendor).all()
    return [r[0] for r in rows]


def _active_schedules(vehicle_ids):
    """Active maintenance schedules for the linking dropdown (#86)."""
    if not vehicle_ids:
        return []
    return MaintenanceSchedule.query.filter(
        MaintenanceSchedule.vehicle_id.in_(vehicle_ids),
        MaintenanceSchedule.is_active.is_(True),
    ).order_by(MaintenanceSchedule.name).all()


def _open_reminder(reminder_id, vehicle_ids, vehicle_id=None):
    """The outstanding reminder this expense is being logged against (#296).

    Returns None unless the reminder exists, is still open and belongs to a
    vehicle the user can see — and, once the expense's vehicle is known, to
    that same vehicle. Completing a reminder is a write to the reminders
    area, so an account that may not change reminders never gets the link.
    """
    if not reminder_id or not current_user.can_write('reminders'):
        return None

    reminder = db.session.get(Reminder, reminder_id)
    if reminder is None or reminder.is_completed:
        return None
    if reminder.vehicle_id not in vehicle_ids:
        return None
    if vehicle_id is not None and reminder.vehicle_id != vehicle_id:
        return None
    return reminder


@bp.route('/')
@login_required
def index():
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    # Get all expenses for user's vehicles
    expenses = Expense.query.filter(
        Expense.vehicle_id.in_(vehicle_ids)
    ).order_by(Expense.date.desc()).all()

    # Spend per vendor (#213)
    vendor_rows = db.session.query(
        Expense.vendor, func.sum(Expense.cost), func.count(Expense.id)
    ).filter(
        Expense.vehicle_id.in_(vehicle_ids),
        Expense.vendor.isnot(None),
        Expense.vendor != '',
    ).group_by(Expense.vendor).order_by(func.sum(Expense.cost).desc()).all()

    return render_template('expenses/index.html', expenses=expenses, vehicles=vehicles,
                           vendor_totals=vendor_rows,
                           expense_attachments=_attachments_by_expense([e.id for e in expenses]))


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    vehicles = current_user.get_all_vehicles()

    if not vehicles:
        flash(_('Please add a vehicle first'), 'info')
        return redirect(url_for('vehicles.new'))

    if request.method == 'POST':
        vehicle_id = int(request.form.get('vehicle_id'))
        vehicle = db.get_or_404(Vehicle, vehicle_id)

        # Check access
        if vehicle not in vehicles:
            flash(_('Access denied'), 'error')
            return redirect(url_for('expenses.index'))

        date_str = request.form.get('date')
        date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()

        expense = Expense(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            date=date,
            category=request.form.get('category'),
            description=request.form.get('description'),
            cost=parse_decimal(request.form.get('cost')),
            odometer=parse_optional_float(request.form.get('odometer')),
            vendor=request.form.get('vendor'),
            notes=request.form.get('notes')
        )

        db.session.add(expense)

        # Optionally mark a maintenance schedule as performed by this
        # expense (#86): stamps the expense's date/odometer onto the
        # schedule and recalculates the next due point.
        schedule_id = request.form.get('maintenance_schedule_id', type=int)
        if schedule_id:
            schedule = db.session.get(MaintenanceSchedule, schedule_id)
            if schedule and schedule.vehicle_id == vehicle_id:
                schedule.last_performed_date = date
                schedule.last_performed_odometer = (
                    expense.odometer or vehicle.get_last_odometer()
                )
                schedule.calculate_next_due()

        # Optionally complete the reminder this expense was logged for
        # (#296), rolling a recurring reminder on to its next occurrence.
        reminder = _open_reminder(request.form.get('reminder_id', type=int),
                                  [v.id for v in vehicles], vehicle_id)
        reminder_message = complete_reminder(reminder) if reminder else None

        db.session.commit()

        # Handle attachment uploads (one or more)
        skipped = _save_attachments(expense, request.files.getlist('attachment'))
        db.session.commit()
        _flash_skipped_attachments(skipped)

        flash(_('Expense added successfully'), 'success')
        if reminder_message:
            flash(reminder_message, 'success')

        # Redirect back to vehicle page if we came from there (#283)
        if request.form.get('return_to') == 'vehicle':
            return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

        return redirect(url_for('expenses.index'))

    # Pre-select vehicle if provided
    selected_vehicle_id = request.args.get('vehicle_id', type=int) or current_user.default_vehicle_id

    vehicle_ids = [v.id for v in vehicles]

    # Logging the expense for a reminder pre-fills the form from it (#296)
    reminder = _open_reminder(request.args.get('reminder_id', type=int), vehicle_ids)
    if reminder:
        selected_vehicle_id = reminder.vehicle_id

    return render_template('expenses/form.html',
                           expense=None,
                           vehicles=vehicles,
                           categories=EXPENSE_CATEGORIES,
                           known_vendors=_known_vendors(vehicle_ids),
                           maintenance_schedules=_active_schedules(vehicle_ids),
                           reminder=reminder,
                           selected_vehicle_id=selected_vehicle_id)


@bp.route('/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(expense_id):
    expense = db.get_or_404(Expense, expense_id)
    vehicles = current_user.get_all_vehicles()

    # Check access
    if expense.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('expenses.index'))

    if request.method == 'POST':
        try:
            date_str = request.form.get('date')
            expense.date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else expense.date
            expense.category = request.form.get('category')
            expense.description = request.form.get('description')
            expense.cost = parse_decimal(request.form.get('cost'))
            expense.odometer = parse_optional_float(request.form.get('odometer'))
            expense.vendor = request.form.get('vendor')
            expense.notes = request.form.get('notes')
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the date and cost fields.'), 'error')
            return render_template('expenses/form.html',
                                   expense=expense,
                                   vehicles=vehicles,
                                   categories=EXPENSE_CATEGORIES,
                                   selected_vehicle_id=expense.vehicle_id)

        # Handle attachment uploads (one or more)
        skipped = _save_attachments(expense, request.files.getlist('attachment'))

        db.session.commit()
        _flash_skipped_attachments(skipped)
        flash(_('Expense updated successfully'), 'success')

        # Redirect back to vehicle page if we came from there (#283)
        if request.form.get('return_to') == 'vehicle':
            return redirect(url_for('vehicles.view', vehicle_id=expense.vehicle_id))

        return redirect(url_for('expenses.index'))

    return render_template('expenses/form.html',
                           expense=expense,
                           vehicles=vehicles,
                           categories=EXPENSE_CATEGORIES,
                           selected_vehicle_id=expense.vehicle_id)


@bp.route('/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete(expense_id):
    expense = db.get_or_404(Expense, expense_id)
    vehicles = current_user.get_all_vehicles()

    # Check access
    if expense.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('expenses.index'))

    vehicle_id = expense.vehicle_id

    # Delete attachments
    for attachment in expense.attachments.all():
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    db.session.delete(expense)
    db.session.commit()
    flash(_('Expense deleted successfully'), 'success')

    # Redirect back to vehicle page if we came from there (#283)
    if request.args.get('return_to') == 'vehicle':
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    return redirect(url_for('expenses.index'))


@bp.route('/<int:expense_id>/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(expense_id, attachment_id):
    expense = db.get_or_404(Expense, expense_id)
    vehicles = current_user.get_all_vehicles()

    if expense.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('expenses.index'))

    attachment = db.get_or_404(Attachment, attachment_id)
    if attachment.expense_id != expense_id:
        flash(_('Access denied'), 'error')
        return redirect(url_for('expenses.edit', expense_id=expense_id))

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(attachment)
    db.session.commit()
    flash(_('Attachment deleted'), 'success')
    return redirect(url_for('expenses.edit', expense_id=expense_id))
