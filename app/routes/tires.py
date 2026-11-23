"""Tire sets and the distance each one has covered (issue #293).

A vehicle can own several sets — summer, winter, a spare set of alloys — and
each set goes on and off the vehicle over the years. Rather than make the user
work the mileage out by hand, every fitting is recorded as a period with an
odometer reading at each end, and the set's total distance is the sum of those
periods (see ``TireSet.get_distance``).
"""
from datetime import datetime, date
import math
import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from flask_babel import gettext as _
from sqlalchemy.exc import IntegrityError
from app import db
from app.utils import parse_decimal
from app.models import (
    Vehicle, TireSet, TireFitment, TIRE_TYPES, Tire, TireMeasurement, TIRE_POSITIONS, TREAD_UNITS,
)

bp = Blueprint('tires', __name__, url_prefix='/tires')


def _parse_date(value, fallback):
    """A yyyy-mm-dd form value, or ``fallback`` when it is missing or unusable."""
    if not value:
        return fallback
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return fallback


def _odometer_from_form(field, vehicle):
    """The odometer a fit/removal happened at, defaulting to the vehicle's latest."""
    value = request.form.get(field)
    if value:
        try:
            reading = parse_decimal(value)
        except ValueError:
            reading = None
        if reading is not None:
            return reading
    return vehicle.get_last_odometer()


def _accessible_set(set_id, vehicles):
    """A tire set the signed-in account may see, or None."""
    tire_set = db.get_or_404(TireSet, set_id)
    return tire_set if tire_set.vehicle in vehicles else None


CAR_WHEELS = ('front_left', 'front_right', 'rear_left', 'rear_right')
BIKE_WHEELS = ('front', 'rear')
TWO_WHEEL_VEHICLES = ('motorbike', 'scooter')


def _wheel_positions(vehicle):
    return BIKE_WHEELS if vehicle.vehicle_type in TWO_WHEEL_VEHICLES else CAR_WHEELS


def _measurement_values(measured_date, odometer):
    measured_date = date.fromisoformat(measured_date)
    odometer = parse_decimal(odometer)
    if odometer is not None and (not math.isfinite(odometer) or odometer < 0):
        raise ValueError
    return measured_date, odometer


MM_PER_THIRTY_SECOND = 25.4 / 32


def _submitted_tread_unit():
    # Forms from before the selector existed always supplied millimetres.
    unit = request.form.get('tread_unit', 'mm')
    if unit not in TREAD_UNITS:
        raise ValueError
    return unit


@bp.context_processor
def _tread_unit_context():
    preferred = current_user.tread_unit if current_user.tread_unit in TREAD_UNITS else 'mm'
    submitted = request.form.get('tread_unit')
    unit = submitted if submitted in TREAD_UNITS else preferred
    return dict(tread_unit=unit, tread_units=TREAD_UNITS)


def _depth(value, unit):
    raw = (value or '').strip()
    if '/' in raw:
        # An explicit fraction can be pasted into either display mode.
        fraction = re.fullmatch(r'([+-]?\d+(?:[.,]\d+)?)\s*/\s*32\s*["″”]?', raw)
        if not fraction:
            raise ValueError
        raw = fraction.group(1)
        unit = 'inch32'
    depth = parse_decimal(raw)
    if depth is None:
        return None
    millimetres = depth * MM_PER_THIRTY_SECOND if unit == 'inch32' else depth
    if not math.isfinite(millimetres) or not 0 <= millimetres <= 100:
        raise ValueError
    return round(millimetres, 12) if unit == 'inch32' else millimetres


@bp.app_template_filter('tread_display')
def _tread_display(depth_mm, unit):
    if unit == 'inch32':
        numerator = f'{depth_mm / MM_PER_THIRTY_SECOND:.2f}'.rstrip('0').rstrip('.')
        return f'{numerator}/32″'
    return f'{round(depth_mm, 2)} mm'


@bp.app_template_filter('tread_input')
def _tread_input(depth_mm, unit):
    if depth_mm is None:
        return ''
    value = depth_mm / MM_PER_THIRTY_SECOND if unit == 'inch32' else depth_mm
    return format(value, '.15g')


def _tread_positions(tire_set):
    """Infer the latest known occupant of each wheel from dated observations."""
    last_at_wheel = {}
    last_position_by_tire = {}
    unassigned = []
    for tire in tire_set.tires:
        for measurement in tire.measurements:
            position = measurement.position
            if not position:
                continue
            # The relationship is ordered newest first, including same-day IDs.
            last_position_by_tire.setdefault(tire.id, measurement)
            previous = last_at_wheel.get(position)
            if previous is None or (measurement.measured_date, measurement.id) > (previous.measured_date, previous.id):
                last_at_wheel[position] = measurement
        if tire.id not in last_position_by_tire and tire.latest_measurement:
            unassigned.append(tire.latest_measurement)

    # If the last occupant moved, the position is unknown. An older observation
    # at that wheel cannot make a replaced tire current again.
    at_wheel = {position: measurement.tire.latest_measurement
                for position, measurement in last_at_wheel.items()
                if last_position_by_tire[measurement.tire_id] is measurement}
    return at_wheel, unassigned


def _save_tread_thresholds(tire_set, unit):
    warning = (_depth(request.form['tread_warning_mm'], unit)
               if 'tread_warning_mm' in request.form else tire_set.tread_warning_mm)
    replacement = (_depth(request.form['tread_replace_mm'], unit)
                   if 'tread_replace_mm' in request.form else tire_set.tread_replace_mm)
    if warning is not None and replacement is not None and warning < replacement:
        raise ValueError
    tire_set.tread_warning_mm = warning
    tire_set.tread_replace_mm = replacement


def _save_tread_form(tire_set, vehicle):
    if 'tread_config_present' not in request.form:
        return
    tire_set.tread_tracking = request.form.get('tread_tracking') == 'on'
    if not tire_set.tread_tracking:
        return

    unit = _submitted_tread_unit()
    _save_tread_thresholds(tire_set, unit)
    readings = [(position, _depth(request.form.get(f'depth_{position}'), unit))
                for position in _wheel_positions(vehicle)]
    readings = [(position, depth) for position, depth in readings if depth is not None]
    if not readings:
        return

    measured_date, odometer = _measurement_values(request.form.get('tread_date', ''),
                                                   request.form.get('tread_odometer'))
    tires = {str(tire.id): tire for tire in tire_set.tires}
    labels = {tire.label for tire in tire_set.tires}
    latest_at_wheel, _unassigned = _tread_positions(tire_set)
    used = set()
    for position, depth in readings:
        tire_id = request.form.get(f'tire_{position}', '')
        previous = latest_at_wheel.get(position)
        if tire_id.startswith('replace:'):
            if (previous is None or tire_id != f'replace:{previous.tire_id}'
                    or measured_date < previous.measured_date):
                raise ValueError
            tire_id = ''
        elif not tire_id and previous is not None:
            raise ValueError
        if tire_id:
            if tire_id not in tires or tire_id in used:
                raise ValueError
            used.add(tire_id)
            tire = tires[tire_id]
        else:
            label = base_label = str(dict(TIRE_POSITIONS)[position])
            suffix = 2
            while label in labels:
                label = f'{base_label} ({suffix})'
                suffix += 1
            labels.add(label)
            tire = Tire(tire_set=tire_set, label=label)
            db.session.add(tire)

        if any((row.measured_date, row.depth_mm, row.odometer, row.position)
               == (measured_date, depth, odometer, position) for row in tire.measurements):
            continue
        db.session.add(TireMeasurement(tire=tire, measured_date=measured_date,
                                       depth_mm=depth, odometer=odometer, position=position))


def _tread_distances(tire_set):
    """Set mileage at readings inside a known, matching fitment interval."""
    fitments = list(reversed(tire_set.fitments.all()))
    distances = {}
    for tire in tire_set.tires:
        for measurement in tire.measurements:
            if measurement.odometer is None:
                continue
            matches = []
            previous_distance = 0
            for fitment in fitments:
                removed = fitment.removed_odometer
                if (fitment.fitted_date <= measurement.measured_date
                        and (removed is None or (fitment.removed_date is not None
                                                 and measurement.measured_date <= fitment.removed_date))
                        and measurement.odometer >= fitment.fitted_odometer
                        and (removed is None or measurement.odometer <= removed)
                        and (fitment.axle == 'all' or measurement.position.startswith(fitment.axle))):
                    matches.append(previous_distance + measurement.odometer - fitment.fitted_odometer)
                if removed is not None:
                    previous_distance += max(0, removed - fitment.fitted_odometer)
            if len(matches) == 1:
                distances[measurement.id] = matches[0]
    return distances


def _render_tire_set_form(tire_set, vehicles, selected_vehicle_id):
    latest_at_wheel, _unassigned = _tread_positions(tire_set) if tire_set else ({}, [])
    suggested_odometer = None
    if tire_set:
        fitment = tire_set.current_fitment
        if fitment and fitment.fitted_date <= date.today():
            reading = tire_set.vehicle.get_last_odometer()
            if reading and reading >= fitment.fitted_odometer:
                suggested_odometer = reading

    return render_template(
        'tires/form.html', tire_set=tire_set, vehicles=vehicles,
        selected_vehicle_id=selected_vehicle_id, tire_types=TIRE_TYPES,
        car_wheels=CAR_WHEELS, bike_wheels=BIKE_WHEELS, two_wheel_vehicles=TWO_WHEEL_VEHICLES,
        position_labels=dict(TIRE_POSITIONS), today=date.today(), latest_at_wheel=latest_at_wheel,
        suggested_odometer=suggested_odometer, tread_distances=_tread_distances(tire_set) if tire_set else {},
    )


@bp.route('/')
@login_required
def index():
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    tire_sets = TireSet.query.filter(
        TireSet.vehicle_id.in_(vehicle_ids)
    ).order_by(TireSet.is_retired, TireSet.name).all()

    # One odometer lookup per vehicle rather than one per open fitment
    vehicle_odometers = {v.id: v.get_last_odometer() for v in vehicles}

    tread_latest_by_set = {}
    for tire_set in tire_sets:
        if tire_set.tracks_tread:
            wheels, unassigned = _tread_positions(tire_set)
            tread_latest_by_set[tire_set.id] = sorted([*wheels.values(), *unassigned],
                                                       key=lambda measurement: measurement.tire_id)

    return render_template('tires/index.html',
                           tire_sets=tire_sets,
                           vehicles=vehicles,
                           vehicle_odometers=vehicle_odometers,
                           tread_latest_by_set=tread_latest_by_set,
                           tire_types=TIRE_TYPES,
                           today=date.today())


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    vehicles = current_user.get_all_vehicles()

    if not vehicles:
        flash(_('Please add a vehicle first'), 'info')
        return redirect(url_for('vehicles.new'))

    if request.method == 'POST':
        vehicle = db.get_or_404(Vehicle, request.form.get('vehicle_id', type=int))

        if vehicle not in vehicles:
            flash(_('Access denied'), 'error')
            return redirect(url_for('tires.index'))

        name = (request.form.get('name') or '').strip()
        if not name:
            flash(_('Please give the tire set a name'), 'error')
            return _render_tire_set_form(None, vehicles, vehicle.id)

        try:
            tire_set = TireSet(
                vehicle_id=vehicle.id,
                user_id=current_user.id,
                name=name,
                tire_type=request.form.get('tire_type') or 'all_season',
                size=request.form.get('size') or None,
                purchase_date=_parse_date(request.form.get('purchase_date'), None),
                purchase_odometer=parse_decimal(request.form.get('purchase_odometer')),
                cost=parse_decimal(request.form.get('cost')),
                notes=request.form.get('notes') or None,
            )
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the odometer and cost fields.'), 'error')
            return _render_tire_set_form(None, vehicles, vehicle.id)

        try:
            db.session.add(tire_set)
            _save_tread_form(tire_set, vehicle)
            db.session.commit()
        except (ValueError, TypeError, IntegrityError):
            db.session.rollback()
            flash(_('Check the tread depths, date, odometer and tire selection.'), 'error')
            return _render_tire_set_form(None, vehicles, vehicle.id)

        flash(_('Tire set "%(name)s" added', name=tire_set.name), 'success')
        return redirect(url_for('tires.index'))

    selected_vehicle_id = request.args.get('vehicle_id', type=int) or current_user.default_vehicle_id

    return _render_tire_set_form(None, vehicles, selected_vehicle_id)


@bp.route('/<int:set_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(set_id):
    vehicles = current_user.get_all_vehicles()
    tire_set = _accessible_set(set_id, vehicles)
    if tire_set is None:
        flash(_('Access denied'), 'error')
        return redirect(url_for('tires.index'))

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name:
            flash(_('Please give the tire set a name'), 'error')
            return _render_tire_set_form(tire_set, vehicles, tire_set.vehicle_id)

        try:
            purchase_odometer = parse_decimal(request.form.get('purchase_odometer'))
            cost = parse_decimal(request.form.get('cost'))
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the odometer and cost fields.'), 'error')
            return _render_tire_set_form(tire_set, vehicles, tire_set.vehicle_id)

        tire_set.purchase_odometer = purchase_odometer
        tire_set.cost = cost
        tire_set.name = name
        tire_set.tire_type = request.form.get('tire_type') or 'all_season'
        tire_set.size = request.form.get('size') or None
        tire_set.purchase_date = _parse_date(request.form.get('purchase_date'), None)
        tire_set.notes = request.form.get('notes') or None
        tire_set.is_retired = request.form.get('is_retired') == 'on'

        try:
            _save_tread_form(tire_set, tire_set.vehicle)
            db.session.commit()
        except (ValueError, TypeError, IntegrityError):
            db.session.rollback()
            flash(_('Check the tread depths, date, odometer and tire selection.'), 'error')
            return _render_tire_set_form(tire_set, vehicles, tire_set.vehicle_id)
        flash(_('Tire set updated'), 'success')
        return redirect(url_for('tires.index'))

    return _render_tire_set_form(tire_set, vehicles, tire_set.vehicle_id)


@bp.route('/<int:set_id>/fit', methods=['POST'])
@login_required
def fit(set_id):
    """Record a tire set going on to the vehicle."""
    vehicles = current_user.get_all_vehicles()
    tire_set = _accessible_set(set_id, vehicles)
    if tire_set is None:
        flash(_('Access denied'), 'error')
        return redirect(url_for('tires.index'))

    if tire_set.is_fitted:
        flash(_('That tire set is already on the vehicle'), 'info')
        return redirect(url_for('tires.index'))
    if tire_set.is_retired:
        flash(_('That tire set is retired. Reinstate it before fitting it again.'), 'error')
        return redirect(url_for('tires.index'))

    vehicle = tire_set.vehicle
    fitted_date = _parse_date(request.form.get('fitted_date'), date.today())
    fitted_odometer = _odometer_from_form('fitted_odometer', vehicle)

    axle = request.form.get('axle', 'all')
    if axle not in ('all', 'front', 'rear'):
        flash(_('Invalid axle'), 'error')
        return redirect(url_for('tires.index'))
    previous = TireFitment.query.join(TireSet).filter(
        TireSet.vehicle_id == vehicle.id,
        TireFitment.removed_odometer.is_(None),
    ).all()
    overlapping = [f for f in previous if axle == 'all' or f.axle in ('all', axle)]
    if (not math.isfinite(fitted_odometer) or fitted_odometer < 0
            or any(fitted_odometer < f.fitted_odometer or fitted_date < f.fitted_date
                   for f in overlapping)):
        flash(_('The fitting date and reading cannot precede the current fitting.'), 'error')
        return redirect(url_for('tires.index'))
    for old in overlapping:
        old.removed_date = fitted_date
        old.removed_odometer = fitted_odometer
        if old.axle == 'all' and axle != 'all':
            # The unaffected pair stays fitted, continuing its distance history.
            db.session.add(TireFitment(
                tire_set_id=old.tire_set_id, axle='rear' if axle == 'front' else 'front',
                fitted_date=fitted_date, fitted_odometer=fitted_odometer,
            ))
        else:
            flash(_('Took "%(name)s" off the vehicle', name=old.tire_set.name), 'info')

    db.session.add(TireFitment(
        tire_set_id=tire_set.id,
        axle=axle,
        fitted_date=fitted_date,
        fitted_odometer=fitted_odometer,
    ))
    db.session.commit()

    flash(_('Fitted "%(name)s"', name=tire_set.name), 'success')
    return redirect(url_for('tires.index'))


@bp.route('/<int:set_id>/remove', methods=['POST'])
@login_required
def remove(set_id):
    """Record a tire set coming off the vehicle."""
    vehicles = current_user.get_all_vehicles()
    tire_set = _accessible_set(set_id, vehicles)
    if tire_set is None:
        flash(_('Access denied'), 'error')
        return redirect(url_for('tires.index'))

    fitment = tire_set.current_fitment
    if fitment is None:
        flash(_('That tire set is not on the vehicle'), 'info')
        return redirect(url_for('tires.index'))

    removed_date = _parse_date(request.form.get('removed_date'), date.today())
    removed_odometer = _odometer_from_form('removed_odometer', tire_set.vehicle)

    if (not math.isfinite(removed_odometer) or removed_odometer < fitment.fitted_odometer
            or removed_date < fitment.fitted_date):
        flash(_('The odometer reading cannot be lower than the one the set was fitted at'), 'error')
        return redirect(url_for('tires.index'))

    fitment.removed_date = removed_date
    fitment.removed_odometer = removed_odometer
    db.session.commit()

    flash(_('Took "%(name)s" off the vehicle', name=tire_set.name), 'success')
    return redirect(url_for('tires.index'))


@bp.route('/fitments/<int:fitment_id>/delete', methods=['POST'])
@login_required
def delete_fitment(fitment_id):
    """Drop a fitting period recorded by mistake."""
    fitment = db.get_or_404(TireFitment, fitment_id)
    vehicles = current_user.get_all_vehicles()

    if fitment.tire_set.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('tires.index'))

    db.session.delete(fitment)
    db.session.commit()
    flash(_('Fitting record deleted'), 'success')
    return redirect(url_for('tires.index'))


@bp.route('/<int:set_id>/delete', methods=['POST'])
@login_required
def delete(set_id):
    vehicles = current_user.get_all_vehicles()
    tire_set = _accessible_set(set_id, vehicles)
    if tire_set is None:
        flash(_('Access denied'), 'error')
        return redirect(url_for('tires.index'))

    name = tire_set.name
    db.session.delete(tire_set)
    db.session.commit()

    flash(_('Tire set "%(name)s" deleted', name=name), 'success')
    return redirect(url_for('tires.index'))


@bp.route('/<int:set_id>/tread', methods=['GET', 'POST'])
@bp.route('/<int:set_id>/tread/<int:measurement_id>/edit', methods=['GET', 'POST'])
@login_required
def tread(set_id, measurement_id=None):
    tire_set = _accessible_set(set_id, current_user.get_all_vehicles())
    if tire_set is None:
        flash(_('Access denied'), 'error')
        return redirect(url_for('tires.index'))
    if tire_set.tread_tracking is False or not current_user.can_write('tires'):
        return redirect(url_for('tires.edit', set_id=set_id, _anchor='tread-history'))
    editing = db.get_or_404(TireMeasurement, measurement_id) if measurement_id else None
    if editing and editing.tire.tire_set_id != set_id:
        abort(404)
    if request.method == 'POST':
        try:
            unit = _submitted_tread_unit()
            if request.form.get('action') == 'thresholds':
                _save_tread_thresholds(tire_set, unit)
                db.session.commit()
                return redirect(url_for('tires.edit', set_id=set_id, _anchor='tread-heading'))
            measured_date, odometer = _measurement_values(request.form.get('measured_date', ''),
                                                           request.form.get('odometer'))
            depth = _depth(request.form.get('depth_mm'), unit)
            position = request.form.get('position', '')
            if depth is None or position not in dict(TIRE_POSITIONS):
                raise ValueError
            tire_id = request.form.get('tire_id', type=int)
            if request.form.get('tire_id') not in (None, '', '0') and tire_id is None:
                raise ValueError
            if tire_id:
                tire = db.get_or_404(Tire, tire_id)
                if tire.tire_set_id != tire_set.id:
                    raise ValueError
            else:
                label = (request.form.get('label') or '').strip()
                if not label or len(label) > 100 or any(t.label == label for t in tire_set.tires):
                    raise ValueError
                tire = Tire(tire_set=tire_set, label=label)
                db.session.add(tire)
            if editing is None:
                tire_set.tread_tracking = True
            measurement = editing or TireMeasurement()
            measurement.tire = tire
            measurement.measured_date = measured_date
            measurement.depth_mm = depth
            measurement.odometer = odometer
            measurement.position = position
            db.session.add(measurement)
            db.session.commit()
            return redirect(url_for('tires.tread', set_id=set_id))
        except (ValueError, TypeError, IntegrityError):
            db.session.rollback()
            flash(_('Invalid tread measurement. Check the tire, date, depth and reading.'), 'error')
    at_wheel, _unassigned = _tread_positions(tire_set)
    current_positions = {measurement.tire_id: position for position, measurement in at_wheel.items()}
    return render_template('tires/tread.html', tire_set=tire_set, current_positions=current_positions,
                           positions=dict(TIRE_POSITIONS), today=date.today(), editing=editing)


@bp.route('/measurements/<int:measurement_id>/delete', methods=['POST'])
@login_required
def delete_measurement(measurement_id):
    measurement = db.get_or_404(TireMeasurement, measurement_id)
    tire_set = _accessible_set(measurement.tire.tire_set_id, current_user.get_all_vehicles())
    if tire_set is None:
        flash(_('Access denied'), 'error')
        return redirect(url_for('tires.index'))
    db.session.delete(measurement)
    db.session.commit()
    return redirect(url_for('tires.edit', set_id=tire_set.id, _anchor='tread-history'))
