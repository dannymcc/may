import os
import uuid
from base64 import b64encode
from io import BytesIO
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, Response
from flask_login import login_required, current_user
from flask_babel import gettext as _
from werkzeug.utils import secure_filename
from app import db
from app.utils import parse_decimal
from app.models import Vehicle, VehicleSpec, VehiclePart, FuelLog, Expense, User, Reminder, MaintenanceSchedule, Attachment, VEHICLE_TYPES, FUEL_TYPES, VEHICLE_SPEC_TYPES, REMINDER_TYPES, PART_TYPES, TRACKING_UNITS, ODOMETER_UNITS, TRIP_PURPOSES, AppSettings
from app.services.tessie import TessieService

bp = Blueprint('vehicles', __name__, url_prefix='/vehicles')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Attachment types that can be inlined into the PDF report as pictures.
RECEIPT_IMAGE_TYPES = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Receipts are base64-encoded into the document, so cap the total to keep
# both the PDF and the memory used to build it within reason.
MAX_RECEIPT_BYTES = 20 * 1024 * 1024


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/')
@login_required
def index():
    show_archived = request.args.get('archived', 'false') == 'true'
    all_vehicles = current_user.get_all_vehicles()

    if show_archived:
        vehicles = [v for v in all_vehicles if not v.is_active]
    else:
        vehicles = [v for v in all_vehicles if v.is_active]

    archived_count = len([v for v in all_vehicles if not v.is_active])

    return render_template('vehicles/index.html',
                           vehicles=vehicles,
                           show_archived=show_archived,
                           archived_count=archived_count)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        vehicle = Vehicle(
            owner_id=current_user.id,
            name=request.form.get('name'),
            vehicle_type=request.form.get('vehicle_type'),
            tracking_unit=request.form.get('tracking_unit', 'mileage'),
            odometer_unit=request.form.get('odometer_unit') or None,
            make=request.form.get('make'),
            model=request.form.get('model'),
            year=int(request.form.get('year')) if request.form.get('year') else None,
            registration=request.form.get('registration'),
            vin=request.form.get('vin'),
            fuel_type=request.form.get('fuel_type'),
            secondary_fuel_type=request.form.get('secondary_fuel_type') or None,
            tank_capacity=parse_decimal(request.form.get('tank_capacity')) if request.form.get('tank_capacity') else None,
            notes=request.form.get('notes'),
            annual_mileage_limit=parse_decimal(request.form.get('annual_mileage_limit')) if request.form.get('annual_mileage_limit') else None,
            annual_mileage_start_date=datetime.strptime(request.form.get('annual_mileage_start_date'), '%Y-%m-%d').date() if request.form.get('annual_mileage_start_date') else None,
            default_trip_purpose=(request.form.get('default_trip_purpose')
                                  if request.form.get('default_trip_purpose') in dict(TRIP_PURPOSES)
                                  else 'business'),
        )

        # Handle image upload
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                vehicle.image_filename = filename

        db.session.add(vehicle)
        db.session.flush()  # Get the vehicle ID

        # Handle specifications
        spec_types = request.form.getlist('spec_type[]')
        spec_labels = request.form.getlist('spec_label[]')
        spec_values = request.form.getlist('spec_value[]')

        for i, spec_type in enumerate(spec_types):
            if spec_values[i].strip():  # Only add if value is not empty
                label = spec_labels[i] if spec_type == 'custom' else str(dict(VEHICLE_SPEC_TYPES).get(spec_type, spec_labels[i]))
                spec = VehicleSpec(
                    vehicle_id=vehicle.id,
                    spec_type=spec_type,
                    label=label,
                    value=spec_values[i].strip()
                )
                db.session.add(spec)

        db.session.commit()

        flash(_('Vehicle "%(name)s" added successfully') % {'name': vehicle.name}, 'success')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle.id))

    tessie_configured = TessieService.is_configured()
    return render_template('vehicles/form.html',
                           vehicle=None,
                           vehicle_types=VEHICLE_TYPES,
                           fuel_types=FUEL_TYPES,
                           tracking_units=TRACKING_UNITS,
                           odometer_units=ODOMETER_UNITS,
                           spec_types=VEHICLE_SPEC_TYPES,
                           trip_purposes=TRIP_PURPOSES,
                           tessie_configured=tessie_configured)


@bp.route('/<int:vehicle_id>')
@login_required
def view(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check access
    if vehicle not in current_user.get_all_vehicles():
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    # Get recent activity
    recent_logs = vehicle.fuel_logs.order_by(FuelLog.date.desc(), FuelLog.odometer.desc()).limit(10).all()
    recent_expenses = vehicle.expenses.order_by(Expense.date.desc()).limit(10).all()

    # Get specifications
    specs = vehicle.specs.all()

    # Get statistics
    stats = {
        'total_fuel_cost': vehicle.get_total_fuel_cost(),
        'total_expense_cost': vehicle.get_total_expense_cost(),
        'total_charging_cost': vehicle.get_total_charging_cost(),
        'total_charging_kwh': vehicle.get_total_charging_kwh(),
        'avg_charging_consumption': vehicle.get_average_charging_consumption(),
        'cost_per_kwh': vehicle.get_cost_per_kwh(),
        'total_cost': vehicle.get_total_cost(),
        'total_allowance': vehicle.get_total_allowance(),
        'net_cost': vehicle.get_net_cost(),
        'total_distance': vehicle.get_total_distance(vehicle.get_effective_odometer_unit()),
        'avg_consumption': vehicle.get_average_consumption(current_user.consumption_unit, current_user.volume_unit),
        'cost_per_distance': vehicle.get_cost_per_distance(),
        'total_fuel_volume': vehicle.get_total_fuel_volume(),
        'total_co2_kg': vehicle.get_total_co2_kg(current_user.volume_unit),
        'fuel_logs_count': vehicle.fuel_logs.count(),
        'expenses_count': vehicle.expenses.count(),
        'charging_sessions_count': vehicle.charging_sessions.count(),
    }

    # Get reminders for this vehicle (not completed, ordered by due date)
    reminders = vehicle.reminders.filter_by(is_completed=False).order_by(Reminder.due_date).all()

    # Get parts for this vehicle
    parts = vehicle.parts.order_by(VehiclePart.part_type, VehiclePart.name).all()

    # Get active maintenance schedules, sorted soonest-due first
    from datetime import date as date_type
    today = date_type.today()
    maintenance_schedules = vehicle.maintenance_schedules.filter_by(is_active=True).all()
    maintenance_schedules.sort(key=lambda s: (
        s.next_due_date or date_type(9999, 12, 31),
        s.next_due_odometer or float('inf')
    ))

    # Check if DVLA integration is configured
    from app.services.dvla import DVLAService
    dvla_configured = DVLAService.is_configured()

    # Check if Tessie integration is configured
    tessie_configured = TessieService.is_configured()

    return render_template('vehicles/view.html',
                           vehicle=vehicle,
                           recent_logs=recent_logs,
                           recent_expenses=recent_expenses,
                           specs=specs,
                           stats=stats,
                           reminders=reminders,
                           reminder_types=REMINDER_TYPES,
                           parts=parts,
                           part_types=PART_TYPES,
                           maintenance_schedules=maintenance_schedules,
                           today=today,
                           dvla_configured=dvla_configured,
                           tessie_configured=tessie_configured,
                           annual_mileage_stats=vehicle.get_annual_mileage_stats())


@bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    if request.method == 'POST':
        vehicle.name = request.form.get('name')
        vehicle.vehicle_type = request.form.get('vehicle_type')
        vehicle.tracking_unit = request.form.get('tracking_unit', 'mileage')
        vehicle.odometer_unit = request.form.get('odometer_unit') or None
        vehicle.make = request.form.get('make')
        vehicle.model = request.form.get('model')
        vehicle.year = int(request.form.get('year')) if request.form.get('year') else None
        vehicle.registration = request.form.get('registration')
        vehicle.vin = request.form.get('vin')
        vehicle.fuel_type = request.form.get('fuel_type')
        vehicle.secondary_fuel_type = request.form.get('secondary_fuel_type') or None
        vehicle.tank_capacity = parse_decimal(request.form.get('tank_capacity')) if request.form.get('tank_capacity') else None
        vehicle.notes = request.form.get('notes')
        vehicle.annual_mileage_limit = parse_decimal(request.form.get('annual_mileage_limit')) if request.form.get('annual_mileage_limit') else None
        vehicle.annual_mileage_start_date = datetime.strptime(request.form.get('annual_mileage_start_date'), '%Y-%m-%d').date() if request.form.get('annual_mileage_start_date') else None

        vehicle.is_active = request.form.get('is_active') == 'on'
        vehicle.is_shared = request.form.get('is_shared') == 'on'
        submitted_purpose = request.form.get('default_trip_purpose')
        if submitted_purpose in dict(TRIP_PURPOSES):
            vehicle.default_trip_purpose = submitted_purpose

        # Handle Tessie integration fields
        vehicle.tessie_vin = request.form.get('tessie_vin') or None
        vehicle.tessie_enabled = request.form.get('tessie_enabled') == 'on'

        # Handle image upload
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                # Delete old image
                if vehicle.image_filename:
                    old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], vehicle.image_filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)

                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                vehicle.image_filename = filename

        # Handle specifications - delete existing and recreate
        VehicleSpec.query.filter_by(vehicle_id=vehicle.id).delete()

        spec_types = request.form.getlist('spec_type[]')
        spec_labels = request.form.getlist('spec_label[]')
        spec_values = request.form.getlist('spec_value[]')

        for i, spec_type in enumerate(spec_types):
            if spec_values[i].strip():  # Only add if value is not empty
                label = spec_labels[i] if spec_type == 'custom' else str(dict(VEHICLE_SPEC_TYPES).get(spec_type, spec_labels[i]))
                spec = VehicleSpec(
                    vehicle_id=vehicle.id,
                    spec_type=spec_type,
                    label=label,
                    value=spec_values[i].strip()
                )
                db.session.add(spec)

        db.session.commit()
        flash(_('Vehicle updated successfully'), 'success')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle.id))

    specs = vehicle.specs.all()
    tessie_configured = TessieService.is_configured()
    return render_template('vehicles/form.html',
                           vehicle=vehicle,
                           vehicle_types=VEHICLE_TYPES,
                           fuel_types=FUEL_TYPES,
                           tracking_units=TRACKING_UNITS,
                           odometer_units=ODOMETER_UNITS,
                           spec_types=VEHICLE_SPEC_TYPES,
                           specs=specs,
                           trip_purposes=TRIP_PURPOSES,
                           tessie_configured=tessie_configured)


@bp.route('/<int:vehicle_id>/delete', methods=['POST'])
@login_required
def delete(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    # Delete image
    if vehicle.image_filename:
        old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], vehicle.image_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    db.session.delete(vehicle)
    db.session.commit()
    flash(_('Vehicle deleted successfully'), 'success')
    return redirect(url_for('vehicles.index'))


@bp.route('/<int:vehicle_id>/share', methods=['GET', 'POST'])
@login_required
def share(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()

        if not user:
            flash(_('User not found'), 'error')
        elif user.id == current_user.id:
            flash(_('You are already the owner'), 'error')
        elif user in vehicle.shared_users.all():
            flash(_('Vehicle already shared with this user'), 'error')
        else:
            vehicle.shared_users.append(user)
            db.session.commit()
            flash(_('Vehicle shared with %(username)s') % {'username': user.username}, 'success')

        return redirect(url_for('vehicles.share', vehicle_id=vehicle.id))

    shared_users = vehicle.shared_users.all()
    return render_template('vehicles/share.html', vehicle=vehicle, shared_users=shared_users)


@bp.route('/<int:vehicle_id>/unshare/<int:user_id>', methods=['POST'])
@login_required
def unshare(vehicle_id, user_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    user = User.query.get_or_404(user_id)
    if user in vehicle.shared_users.all():
        vehicle.shared_users.remove(user)
        db.session.commit()
        flash(_('Sharing removed for %(username)s') % {'username': user.username}, 'success')

    return redirect(url_for('vehicles.share', vehicle_id=vehicle.id))


@bp.route('/<int:vehicle_id>/archive', methods=['POST'])
@login_required
def archive(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    vehicle.is_active = False
    db.session.commit()
    flash(_('Vehicle "%(name)s" has been archived') % {'name': vehicle.name}, 'success')
    return redirect(url_for('vehicles.index'))


@bp.route('/<int:vehicle_id>/unarchive', methods=['POST'])
@login_required
def unarchive(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    vehicle.is_active = True
    db.session.commit()
    flash(_('Vehicle "%(name)s" has been restored') % {'name': vehicle.name}, 'success')
    return redirect(url_for('vehicles.index'))


def collect_receipts(fuel_logs, expenses, upload_folder):
    """Collect receipt attachments for the PDF report (#219).

    Returns a (receipts, omitted) pair. Receipts are image attachments read
    off disk and inlined as data URIs: WeasyPrint fetches remote URLs without
    the user's session, so a link to the uploads route would land it on the
    login page instead of the picture. Anything we cannot inline — a PDF scan,
    a missing file, or one big enough to bloat the document — is listed in
    omitted so the report can say so rather than silently dropping it.
    """
    receipts = []
    omitted = []
    budget_left = MAX_RECEIPT_BYTES

    def add(record, kind, title, subtitle, cost):
        nonlocal budget_left
        for attachment in record.attachments.order_by(Attachment.id).all():
            extension = (attachment.file_type or '').lower().lstrip('.')
            if not extension and '.' in attachment.filename:
                extension = attachment.filename.rsplit('.', 1)[1].lower()

            entry = {
                'kind': kind,
                'date': record.date,
                'title': title,
                'subtitle': subtitle,
                'cost': cost,
                'filename': attachment.original_filename or attachment.filename,
            }

            if extension not in RECEIPT_IMAGE_TYPES:
                omitted.append(dict(entry, reason='not an image'))
                continue

            path = os.path.join(upload_folder, attachment.filename)
            try:
                size = os.path.getsize(path)
            except OSError:
                omitted.append(dict(entry, reason='file missing'))
                continue

            if size > budget_left:
                omitted.append(dict(entry, reason='too large to embed'))
                continue

            try:
                with open(path, 'rb') as handle:
                    data = handle.read()
            except OSError:
                omitted.append(dict(entry, reason='file could not be read'))
                continue

            budget_left -= len(data)
            mime = 'image/jpeg' if extension in ('jpg', 'jpeg') else f'image/{extension}'
            entry['data_uri'] = 'data:%s;base64,%s' % (mime, b64encode(data).decode('ascii'))
            receipts.append(entry)

    for log in fuel_logs:
        add(log, 'Fuel',
            log.station or 'Fuel fill-up',
            log.notes or '',
            log.total_cost)

    for expense in expenses:
        add(expense, 'Expense',
            expense.description,
            expense.vendor or '',
            expense.cost)

    receipts.sort(key=lambda entry: entry['date'], reverse=True)
    omitted.sort(key=lambda entry: entry['date'], reverse=True)
    return receipts, omitted


@bp.route('/<int:vehicle_id>/report')
@login_required
def report(vehicle_id):
    """Generate a PDF report for a vehicle"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check access
    if vehicle not in current_user.get_all_vehicles():
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    try:
        from weasyprint import HTML, CSS
    except ImportError:
        flash(_('PDF generation is not available. Please install weasyprint.'), 'error')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    # Gather all data for the report
    fuel_logs = vehicle.fuel_logs.order_by(FuelLog.date.desc(), FuelLog.odometer.desc()).all()
    expenses = vehicle.expenses.order_by(Expense.date.desc()).all()
    specs = vehicle.specs.all()
    parts = vehicle.parts.order_by(VehiclePart.part_type, VehiclePart.name).all()

    # Calculate statistics
    stats = {
        'total_fuel_cost': vehicle.get_total_fuel_cost(),
        'total_expense_cost': vehicle.get_total_expense_cost(),
        'total_cost': vehicle.get_total_cost(),
        'total_distance': vehicle.get_total_distance(vehicle.get_effective_odometer_unit()),
        'avg_consumption': vehicle.get_average_consumption(current_user.consumption_unit, current_user.volume_unit),
        'fuel_logs_count': len(fuel_logs),
        'expenses_count': len(expenses)
    }

    # Get branding
    branding = AppSettings.get_all_branding()

    # Receipts are opt-in (#219): they are what an accountant or employer
    # asks for, but they also make the file much bigger, so only attach
    # them when asked.
    include_receipts = request.args.get('receipts') == '1'
    receipts, receipts_omitted = [], []
    if include_receipts:
        receipts, receipts_omitted = collect_receipts(
            fuel_logs, expenses, current_app.config['UPLOAD_FOLDER'])

    # Render HTML template
    html_content = render_template(
        'vehicles/report_pdf.html',
        vehicle=vehicle,
        fuel_logs=fuel_logs,
        expenses=expenses,
        specs=specs,
        parts=parts,
        part_type_labels=dict(PART_TYPES),
        stats=stats,
        user=current_user,
        branding=branding,
        include_receipts=include_receipts,
        receipts=receipts,
        receipts_omitted=receipts_omitted,
        generated_at=datetime.utcnow()
    )

    # Generate PDF
    pdf = HTML(string=html_content, base_url=request.host_url).write_pdf()

    # Generate filename
    safe_name = vehicle.name.replace(' ', '_').replace('/', '-')
    filename = f'{safe_name}_report_{datetime.now().strftime("%Y%m%d")}.pdf'

    return Response(
        pdf,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# --- Vehicle Parts CRUD ---

@bp.route('/<int:vehicle_id>/parts')
@login_required
def parts(vehicle_id):
    """List all parts for a vehicle"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check access
    if vehicle not in current_user.get_all_vehicles():
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    # Get parts grouped by type
    parts = vehicle.parts.order_by(VehiclePart.part_type, VehiclePart.name).all()

    # Group parts by type for display
    parts_by_type = {}
    for part in parts:
        type_label = dict(PART_TYPES).get(part.part_type, part.part_type)
        if type_label not in parts_by_type:
            parts_by_type[type_label] = []
        parts_by_type[type_label].append(part)

    return render_template('vehicles/parts.html',
                           vehicle=vehicle,
                           parts=parts,
                           parts_by_type=parts_by_type,
                           part_types=PART_TYPES)


@bp.route('/<int:vehicle_id>/parts/new', methods=['GET', 'POST'])
@login_required
def new_part(vehicle_id):
    """Add a new part to a vehicle"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check access
    if vehicle not in current_user.get_all_vehicles():
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    if request.method == 'POST':
        part = VehiclePart(
            vehicle_id=vehicle.id,
            user_id=current_user.id,
            name=request.form.get('name'),
            part_type=request.form.get('part_type'),
            specification=request.form.get('specification') or None,
            quantity=parse_decimal(request.form.get('quantity')) if request.form.get('quantity') else None,
            unit=request.form.get('unit') or None,
            part_number=request.form.get('part_number') or None,
            supplier_url=request.form.get('supplier_url') or None,
            notes=request.form.get('notes') or None
        )

        db.session.add(part)
        db.session.commit()

        flash(_('Part "%(name)s" added successfully') % {'name': part.name}, 'success')
        return redirect(url_for('vehicles.parts', vehicle_id=vehicle.id))

    return render_template('vehicles/part_form.html',
                           vehicle=vehicle,
                           part=None,
                           part_types=PART_TYPES)


@bp.route('/<int:vehicle_id>/parts/<int:part_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_part(vehicle_id, part_id):
    """Edit an existing part"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    part = VehiclePart.query.get_or_404(part_id)

    # Check access
    if vehicle not in current_user.get_all_vehicles():
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    # Verify part belongs to vehicle
    if part.vehicle_id != vehicle.id:
        flash(_('Part not found'), 'error')
        return redirect(url_for('vehicles.parts', vehicle_id=vehicle.id))

    if request.method == 'POST':
        part.name = request.form.get('name')
        part.part_type = request.form.get('part_type')
        part.specification = request.form.get('specification') or None
        part.quantity = parse_decimal(request.form.get('quantity')) if request.form.get('quantity') else None
        part.unit = request.form.get('unit') or None
        part.part_number = request.form.get('part_number') or None
        part.supplier_url = request.form.get('supplier_url') or None
        part.notes = request.form.get('notes') or None

        db.session.commit()

        flash(_('Part updated successfully'), 'success')
        return redirect(url_for('vehicles.parts', vehicle_id=vehicle.id))

    return render_template('vehicles/part_form.html',
                           vehicle=vehicle,
                           part=part,
                           part_types=PART_TYPES)


@bp.route('/<int:vehicle_id>/parts/<int:part_id>/delete', methods=['POST'])
@login_required
def delete_part(vehicle_id, part_id):
    """Delete a part"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    part = VehiclePart.query.get_or_404(part_id)

    # Check access
    if vehicle not in current_user.get_all_vehicles():
        flash(_('Access denied'), 'error')
        return redirect(url_for('vehicles.index'))

    # Verify part belongs to vehicle
    if part.vehicle_id != vehicle.id:
        flash(_('Part not found'), 'error')
        return redirect(url_for('vehicles.parts', vehicle_id=vehicle.id))

    db.session.delete(part)
    db.session.commit()

    flash(_('Part deleted successfully'), 'success')
    return redirect(url_for('vehicles.parts', vehicle_id=vehicle.id))
