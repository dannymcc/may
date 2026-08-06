import os
import uuid
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.utils import parse_decimal
from app.models import Vehicle, FuelLog, Attachment, FuelStation, FuelPriceHistory, FUEL_TYPES
from app.security import validate_file_upload, secure_filename_with_uuid, validate_positive_number
from flask_babel import gettext as _
from app.services.tessie import TessieService

bp = Blueprint('fuel', __name__, url_prefix='/fuel')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}


def allowed_file(filename):
    """Legacy function - use validate_file_upload for new code"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/')
@login_required
def index():
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    # Get all fuel logs for user's vehicles
    logs = FuelLog.query.filter(
        FuelLog.vehicle_id.in_(vehicle_ids)
    ).order_by(FuelLog.date.desc(), FuelLog.odometer.desc()).all()

    # #175 — also surface charging sessions on this page when the user has EVs
    from app.models import ChargingSession
    charging_sessions = ChargingSession.query.filter(
        ChargingSession.vehicle_id.in_(vehicle_ids)
    ).order_by(ChargingSession.date.desc()).all() if vehicle_ids else []

    return render_template('fuel/index.html',
                           logs=logs,
                           vehicles=vehicles,
                           charging_sessions=charging_sessions)


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
            return redirect(url_for('fuel.index'))

        date_str = request.form.get('date')
        date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()

        # Validate numeric inputs
        odometer, err = validate_positive_number(request.form.get('odometer'), 'Odometer', max_value=9999999)
        if err:
            flash(err, 'error')
            return render_template('fuel/new.html', vehicles=vehicles)

        volume, err = validate_positive_number(request.form.get('volume'), 'Volume', max_value=10000)
        if err:
            flash(err, 'error')
            return render_template('fuel/new.html', vehicles=vehicles)

        price_per_unit, err = validate_positive_number(request.form.get('price_per_unit'), 'Price per unit', max_value=1000)
        if err:
            flash(err, 'error')
            return render_template('fuel/new.html', vehicles=vehicles)

        discount_per_unit = None
        if request.form.get('discount_per_unit'):
            discount_per_unit, err = validate_positive_number(request.form.get('discount_per_unit'), 'Discount per unit', max_value=1000)
            if err:
                flash(err, 'error')
                return render_template('fuel/new.html', vehicles=vehicles)

        total_cost, err = validate_positive_number(request.form.get('total_cost'), 'Total cost', max_value=100000)
        if err:
            flash(err, 'error')
            return render_template('fuel/new.html', vehicles=vehicles)

        log = FuelLog(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            date=date,
            odometer=odometer,
            volume=volume,
            price_per_unit=price_per_unit,
            discount_per_unit=discount_per_unit,
            total_cost=total_cost,
            fuel_type=request.form.get('fuel_type') or None,
            is_full_tank=request.form.get('is_full_tank') == 'on',
            is_missed=request.form.get('is_missed') == 'on',
            station=request.form.get('station'),
            notes=request.form.get('notes')
        )

        # Calculate total cost if not provided, applying any per-unit discount (#209)
        if log.volume and log.price_per_unit and not log.total_cost:
            effective_price = log.price_per_unit - (log.discount_per_unit or 0)
            log.total_cost = round(log.volume * effective_price, 2)

        db.session.add(log)
        db.session.commit()

        # Auto-save fuel price to history if station is selected
        station_id = request.form.get('station_id', type=int)
        if station_id and log.price_per_unit:
            station = FuelStation.query.get(station_id)
            if station:
                # Save price history
                price_history = FuelPriceHistory(
                    station_id=station_id,
                    user_id=current_user.id,
                    fuel_log_id=log.id,
                    date=log.date,
                    fuel_type=log.fuel_type or vehicle.fuel_type or 'petrol',
                    price_per_unit=log.price_per_unit
                )
                db.session.add(price_history)
                station.increment_usage()
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
                    fuel_log_id=log.id
                )
                db.session.add(attachment)
                db.session.commit()

        flash(_('Fuel log added successfully'), 'success')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    # Pre-select vehicle: explicit param > default vehicle preference
    selected_vehicle_id = request.args.get('vehicle_id', type=int) or current_user.default_vehicle_id

    # Get all fuel stations for dropdown (stations are system-wide)
    stations = FuelStation.query.order_by(
        FuelStation.is_favorite.desc(),
        FuelStation.times_used.desc()
    ).all()

    return render_template('fuel/form.html',
                           log=None,
                           vehicles=vehicles,
                           stations=stations,
                           fuel_types=FUEL_TYPES,
                           selected_vehicle_id=selected_vehicle_id)


@bp.route('/<int:log_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(log_id):
    log = FuelLog.query.get_or_404(log_id)
    vehicles = current_user.get_all_vehicles()

    # Check access
    if log.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('fuel.index'))

    if request.method == 'POST':
        # Capture old values before updating for price history sync
        old_price = log.price_per_unit
        old_date = log.date

        new_vehicle_id = request.form.get('vehicle_id', type=int)
        if new_vehicle_id:
            new_vehicle = Vehicle.query.get_or_404(new_vehicle_id)
            if new_vehicle in vehicles:
                log.vehicle_id = new_vehicle_id
        date_str = request.form.get('date')
        log.date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else log.date
        log.odometer = parse_decimal(request.form.get('odometer'))
        log.volume = parse_decimal(request.form.get('volume')) if request.form.get('volume') else None
        log.price_per_unit = parse_decimal(request.form.get('price_per_unit')) if request.form.get('price_per_unit') else None
        log.discount_per_unit = parse_decimal(request.form.get('discount_per_unit')) if request.form.get('discount_per_unit') else None
        log.total_cost = parse_decimal(request.form.get('total_cost')) if request.form.get('total_cost') else None
        log.fuel_type = request.form.get('fuel_type') or None
        log.is_full_tank = request.form.get('is_full_tank') == 'on'
        log.is_missed = request.form.get('is_missed') == 'on'
        log.station = request.form.get('station')
        log.notes = request.form.get('notes')

        # Calculate total cost if not provided, applying any per-unit discount (#209)
        if log.volume and log.price_per_unit and not log.total_cost:
            effective_price = log.price_per_unit - (log.discount_per_unit or 0)
            log.total_cost = round(log.volume * effective_price, 2)

        # Reconcile fuel price history with the edited log.
        # Issue #170: linking a station to an existing log via edit must
        # both create the price-history row (so it shows in "cheapest fuel")
        # and bump the station's `times_used` counter.
        station_id = request.form.get('station_id', type=int)
        # Prefer the exact FK link (#254); fall back to the legacy heuristic
        # only for rows created before fuel_log_id existed. Restricting the
        # heuristic to unlinked rows stops it from grabbing a different log's
        # entry that happens to share the same date and price.
        existing_entry = FuelPriceHistory.query.filter_by(fuel_log_id=log.id).first()
        if not existing_entry and old_price and old_date:
            existing_entry = FuelPriceHistory.query.filter_by(
                user_id=current_user.id,
                date=old_date,
                price_per_unit=old_price,
                fuel_log_id=None,
            ).first()
            if existing_entry:
                # Adopt the legacy row so future edits match exactly.
                existing_entry.fuel_log_id = log.id

        if existing_entry:
            if not log.price_per_unit:
                db.session.delete(existing_entry)
            else:
                existing_entry.price_per_unit = log.price_per_unit
                existing_entry.date = log.date
                if station_id and existing_entry.station_id != station_id:
                    new_station = FuelStation.query.get(station_id)
                    if new_station:
                        # Reassigning the log moves the usage count too (#252):
                        # decrement the station we're leaving before bumping the
                        # new one, so no station is over-counted.
                        old_station = existing_entry.station
                        if old_station and old_station.times_used:
                            old_station.times_used = max(0, old_station.times_used - 1)
                        existing_entry.station_id = station_id
                        new_station.increment_usage()
        elif station_id and log.price_per_unit:
            new_station = FuelStation.query.get(station_id)
            if new_station:
                db.session.add(FuelPriceHistory(
                    station_id=station_id,
                    user_id=current_user.id,
                    fuel_log_id=log.id,
                    date=log.date,
                    fuel_type=log.fuel_type or log.vehicle.fuel_type or 'petrol',
                    price_per_unit=log.price_per_unit,
                ))
                new_station.increment_usage()

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
                    fuel_log_id=log.id
                )
                db.session.add(attachment)

        db.session.commit()
        flash(_('Fuel log updated successfully'), 'success')
        return redirect(url_for('vehicles.view', vehicle_id=log.vehicle_id))

    # Get all fuel stations for dropdown (stations are system-wide)
    stations = FuelStation.query.order_by(
        FuelStation.is_favorite.desc(),
        FuelStation.times_used.desc()
    ).all()

    return render_template('fuel/form.html',
                           log=log,
                           vehicles=vehicles,
                           stations=stations,
                           fuel_types=FUEL_TYPES,
                           selected_vehicle_id=log.vehicle_id)


@bp.route('/<int:log_id>/delete', methods=['POST'])
@login_required
def delete(log_id):
    log = FuelLog.query.get_or_404(log_id)
    vehicles = current_user.get_all_vehicles()

    # Check access
    if log.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('fuel.index'))

    vehicle_id = log.vehicle_id

    # Delete attachments
    for attachment in log.attachments.all():
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    # Clean up matching fuel price history entries and keep each affected
    # station's usage counter in step with the chart view (#252): deleting a
    # log must decrement the overview "used N times" counter, not just drop the
    # price-history row the chart reads from.
    # Prefer the exact FK link (#254); the legacy heuristic only considers
    # unlinked rows so it can never delete another log's price entry.
    entries = FuelPriceHistory.query.filter_by(fuel_log_id=log.id).all()
    if not entries and log.price_per_unit and log.date:
        entries = FuelPriceHistory.query.filter(
            FuelPriceHistory.user_id == current_user.id,
            FuelPriceHistory.date == log.date,
            FuelPriceHistory.price_per_unit == log.price_per_unit,
            FuelPriceHistory.fuel_log_id.is_(None)
        ).all()
    if entries:
        for entry in entries:
            station = entry.station
            if station and station.times_used:
                station.times_used = max(0, station.times_used - 1)
            db.session.delete(entry)

    db.session.delete(log)
    db.session.commit()
    flash(_('Fuel log deleted successfully'), 'success')
    return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))


@bp.route('/<int:log_id>/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(log_id, attachment_id):
    log = FuelLog.query.get_or_404(log_id)
    vehicles = current_user.get_all_vehicles()

    if log.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('fuel.index'))

    attachment = Attachment.query.get_or_404(attachment_id)
    if attachment.fuel_log_id != log_id:
        flash(_('Access denied'), 'error')
        return redirect(url_for('fuel.edit', log_id=log_id))

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(attachment)
    db.session.commit()
    flash(_('Attachment deleted'), 'success')
    return redirect(url_for('fuel.edit', log_id=log_id))


@bp.route('/quick', methods=['GET', 'POST'])
@login_required
def quick():
    """Quick entry mode - simplified single-screen fuel entry for mobile"""
    from app.models import FuelStation

    vehicles = current_user.get_all_vehicles()

    if not vehicles:
        flash(_('Please add a vehicle first'), 'info')
        return redirect(url_for('vehicles.new'))

    # Get all fuel stations for dropdown (stations are system-wide)
    stations = FuelStation.query.order_by(
        FuelStation.is_favorite.desc(),
        FuelStation.times_used.desc()
    ).all()

    if request.method == 'POST':
        vehicle_id = int(request.form.get('vehicle_id'))
        vehicle = Vehicle.query.get_or_404(vehicle_id)

        if vehicle not in vehicles:
            flash(_('Access denied'), 'error')
            return redirect(url_for('fuel.quick'))

        volume = parse_decimal(request.form.get('volume')) if request.form.get('volume') else None
        total_cost = parse_decimal(request.form.get('total_cost')) if request.form.get('total_cost') else None
        price_per_unit = parse_decimal(request.form.get('price_per_unit')) if request.form.get('price_per_unit') else None

        # Derive missing value if two of the three are provided
        if volume and price_per_unit and not total_cost:
            total_cost = round(volume * price_per_unit, 2)
        elif volume and total_cost and not price_per_unit:
            price_per_unit = round(total_cost / volume, 3)

        log = FuelLog(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            date=datetime.now().date(),
            odometer=parse_decimal(request.form.get('odometer')),
            volume=volume,
            total_cost=total_cost,
            price_per_unit=price_per_unit,
            fuel_type=request.form.get('fuel_type') or None,
            is_full_tank=request.form.get('is_full_tank') == 'on',
            station=request.form.get('station'),
        )

        db.session.add(log)
        db.session.commit()

        # Associate with a saved station the same way fuel.new() does (#252):
        # record a FuelPriceHistory row and bump the usage counter together, so
        # quick logs show up in the station chart view and keep the overview
        # counter in step. Prefer the station_id sent by the dropdown; fall back
        # to a name match for manually typed stations.
        station_id = request.form.get('station_id', type=int)
        station = None
        if station_id:
            station = FuelStation.query.get(station_id)
        else:
            station_name = request.form.get('station')
            if station_name:
                station = FuelStation.query.filter_by(
                    user_id=current_user.id,
                    name=station_name
                ).first()
        if station and log.price_per_unit:
            db.session.add(FuelPriceHistory(
                station_id=station.id,
                user_id=current_user.id,
                fuel_log_id=log.id,
                date=log.date,
                fuel_type=log.fuel_type or vehicle.fuel_type or 'petrol',
                price_per_unit=log.price_per_unit,
            ))
            station.increment_usage()
            db.session.commit()

        flash(_('Fuel log added!'), 'success')

        # Return to quick entry or vehicle page based on preference
        if request.form.get('add_another'):
            return redirect(url_for('fuel.quick', vehicle_id=vehicle_id))
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    # Pre-select vehicle: explicit param > default vehicle preference > single vehicle
    selected_vehicle_id = request.args.get('vehicle_id', type=int)
    if not selected_vehicle_id and current_user.default_vehicle_id in [v.id for v in vehicles]:
        selected_vehicle_id = current_user.default_vehicle_id
    if not selected_vehicle_id and len(vehicles) == 1:
        selected_vehicle_id = vehicles[0].id

    # Get last odometer for selected vehicle
    last_odometer = None
    if selected_vehicle_id:
        vehicle = Vehicle.query.get(selected_vehicle_id)
        if vehicle:
            last_odometer = vehicle.get_last_odometer()

    return render_template('fuel/quick.html',
                           vehicles=vehicles,
                           stations=stations,
                           selected_vehicle_id=selected_vehicle_id,
                           last_odometer=last_odometer)
