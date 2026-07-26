import os
import uuid
from io import BytesIO
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, Response
from flask_login import login_required, current_user
from flask_babel import gettext as _
from werkzeug.utils import secure_filename
from app import db
from app.models import Vehicle, VehicleSpec, VehiclePart, FuelLog, Expense, User, Reminder, VehicleNote, VEHICLE_TYPES, FUEL_TYPES, VEHICLE_SPEC_TYPES, REMINDER_TYPES, PART_TYPES, TRACKING_UNITS, ODOMETER_UNITS, AppSettings
from app.services.tessie import TessieService

bp = Blueprint('vehicles', __name__, url_prefix='/vehicles')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def tank_capacity_to_liters(value, volume_unit):
    """Convert a tank capacity value from the user's volume unit to liters."""
    if volume_unit == 'us_gal':
        return value * 3.78541
    elif volume_unit == 'gal':
        return value * 4.54609
    return value  # already liters


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
            tank_capacity=tank_capacity_to_liters(float(request.form.get('tank_capacity')), current_user.volume_unit) if request.form.get('tank_capacity') else None,
            notes=request.form.get('notes')
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
    recent_logs = vehicle.fuel_logs.order_by(FuelLog.date.desc()).limit(10).all()
    recent_expenses = vehicle.expenses.order_by(Expense.date.desc()).limit(10).all()

    # Get specifications
    specs = vehicle.specs.all()

    # Get statistics
    stats = {
        'total_fuel_cost': vehicle.get_total_fuel_cost(),
        'total_expense_cost': vehicle.get_total_expense_cost(),
        'total_cost': vehicle.get_total_cost(),
        'total_distance': vehicle.get_total_distance(vehicle.get_effective_odometer_unit()),
        'avg_consumption': vehicle.get_average_consumption(current_user.consumption_unit),
        'fuel_logs_count': vehicle.fuel_logs.count(),
        'expenses_count': vehicle.expenses.count()
    }

    # Get reminders for this vehicle (not completed, ordered by due date)
    reminders = vehicle.reminders.filter_by(is_completed=False).order_by(Reminder.due_date).all()

    # Get parts for this vehicle
    parts = vehicle.parts.order_by(VehiclePart.part_type, VehiclePart.name).all()

    # Check if DVLA integration is configured
    from app.services.dvla import DVLAService
    dvla_configured = DVLAService.is_configured()

    # Check if Tessie integration is configured
    tessie_configured = TessieService.is_configured()

    # Get recent notes for this vehicle
    recent_notes = vehicle.vehicle_notes.order_by(
        VehicleNote.is_pinned.desc(), VehicleNote.updated_at.desc()
    ).limit(3).all()

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
                           dvla_configured=dvla_configured,
                           tessie_configured=tessie_configured,
                           recent_notes=recent_notes)


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
        vehicle.tank_capacity = tank_capacity_to_liters(float(request.form.get('tank_capacity')), current_user.volume_unit) if request.form.get('tank_capacity') else None
        vehicle.notes = request.form.get('notes')

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
    fuel_logs = vehicle.fuel_logs.order_by(FuelLog.date.desc()).all()
    expenses = vehicle.expenses.order_by(Expense.date.desc()).all()
    specs = vehicle.specs.all()

    # Calculate statistics
    stats = {
        'total_fuel_cost': vehicle.get_total_fuel_cost(),
        'total_expense_cost': vehicle.get_total_expense_cost(),
        'total_cost': vehicle.get_total_cost(),
        'total_distance': vehicle.get_total_distance(vehicle.get_effective_odometer_unit()),
        'avg_consumption': vehicle.get_average_consumption(current_user.consumption_unit),
        'fuel_logs_count': len(fuel_logs),
        'expenses_count': len(expenses)
    }

    # Get branding
    branding = AppSettings.get_all_branding()

    # Render HTML template
    html_content = render_template(
        'vehicles/report_pdf.html',
        vehicle=vehicle,
        fuel_logs=fuel_logs,
        expenses=expenses,
        specs=specs,
        stats=stats,
        user=current_user,
        branding=branding,
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
            quantity=float(request.form.get('quantity')) if request.form.get('quantity') else None,
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
        part.quantity = float(request.form.get('quantity')) if request.form.get('quantity') else None
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
