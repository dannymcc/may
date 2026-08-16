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
from app.models import Vehicle, Expense, Attachment, MaintenanceSchedule, EXPENSE_CATEGORIES

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
                           vendor_totals=vendor_rows)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    vehicles = current_user.get_all_vehicles()

    if not vehicles:
        flash(_('Please add a vehicle first'), 'info')
        return redirect(url_for('vehicles.new'))

    if request.method == 'POST':
        vehicle_id = int(request.form.get('vehicle_id'))
        vehicle = Vehicle.query.get_or_404(vehicle_id)

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
            schedule = MaintenanceSchedule.query.get(schedule_id)
            if schedule and schedule.vehicle_id == vehicle_id:
                schedule.last_performed_date = date
                schedule.last_performed_odometer = (
                    expense.odometer or vehicle.get_last_odometer()
                )
                schedule.calculate_next_due()

        db.session.commit()

        # Handle attachment upload
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

                attachment = Attachment(
                    filename=filename,
                    original_filename=file.filename,
                    file_type=file.filename.rsplit('.', 1)[1].lower(),
                    expense_id=expense.id
                )
                db.session.add(attachment)
                db.session.commit()

        flash(_('Expense added successfully'), 'success')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    # Pre-select vehicle if provided
    selected_vehicle_id = request.args.get('vehicle_id', type=int) or current_user.default_vehicle_id

    vehicle_ids = [v.id for v in vehicles]
    return render_template('expenses/form.html',
                           expense=None,
                           vehicles=vehicles,
                           categories=EXPENSE_CATEGORIES,
                           known_vendors=_known_vendors(vehicle_ids),
                           maintenance_schedules=_active_schedules(vehicle_ids),
                           selected_vehicle_id=selected_vehicle_id)


@bp.route('/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(expense_id):
    expense = Expense.query.get_or_404(expense_id)
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

        # Handle attachment upload
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

                attachment = Attachment(
                    filename=filename,
                    original_filename=file.filename,
                    file_type=file.filename.rsplit('.', 1)[1].lower(),
                    expense_id=expense.id
                )
                db.session.add(attachment)

        db.session.commit()
        flash(_('Expense updated successfully'), 'success')
        return redirect(url_for('vehicles.view', vehicle_id=expense.vehicle_id))

    return render_template('expenses/form.html',
                           expense=expense,
                           vehicles=vehicles,
                           categories=EXPENSE_CATEGORIES,
                           selected_vehicle_id=expense.vehicle_id)


@bp.route('/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete(expense_id):
    expense = Expense.query.get_or_404(expense_id)
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
    return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))


@bp.route('/<int:expense_id>/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(expense_id, attachment_id):
    expense = Expense.query.get_or_404(expense_id)
    vehicles = current_user.get_all_vehicles()

    if expense.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('expenses.index'))

    attachment = Attachment.query.get_or_404(attachment_id)
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
