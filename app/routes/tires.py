"""Tire sets and the distance each one has covered (issue #293).

A vehicle can own several sets — summer, winter, a spare set of alloys — and
each set goes on and off the vehicle over the years. Rather than make the user
work the mileage out by hand, every fitting is recorded as a period with an
odometer reading at each end, and the set's total distance is the sum of those
periods (see ``TireSet.get_distance``).
"""
from datetime import datetime, date
import math
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db
from app.utils import parse_decimal
from app.models import Vehicle, TireSet, TireFitment, TIRE_TYPES

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

    return render_template('tires/index.html',
                           tire_sets=tire_sets,
                           vehicles=vehicles,
                           vehicle_odometers=vehicle_odometers,
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
            return render_template('tires/form.html', tire_set=None, vehicles=vehicles,
                                   selected_vehicle_id=vehicle.id, tire_types=TIRE_TYPES)

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
            return render_template('tires/form.html', tire_set=None, vehicles=vehicles,
                                   selected_vehicle_id=vehicle.id, tire_types=TIRE_TYPES)

        db.session.add(tire_set)
        db.session.commit()

        flash(_('Tire set "%(name)s" added', name=tire_set.name), 'success')
        return redirect(url_for('tires.index'))

    selected_vehicle_id = request.args.get('vehicle_id', type=int) or current_user.default_vehicle_id

    return render_template('tires/form.html', tire_set=None, vehicles=vehicles,
                           selected_vehicle_id=selected_vehicle_id, tire_types=TIRE_TYPES)


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
            return render_template('tires/form.html', tire_set=tire_set, vehicles=vehicles,
                                   selected_vehicle_id=tire_set.vehicle_id, tire_types=TIRE_TYPES)

        try:
            tire_set.purchase_odometer = parse_decimal(request.form.get('purchase_odometer'))
            tire_set.cost = parse_decimal(request.form.get('cost'))
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the odometer and cost fields.'), 'error')
            return render_template('tires/form.html', tire_set=tire_set, vehicles=vehicles,
                                   selected_vehicle_id=tire_set.vehicle_id, tire_types=TIRE_TYPES)

        tire_set.name = name
        tire_set.tire_type = request.form.get('tire_type') or 'all_season'
        tire_set.size = request.form.get('size') or None
        tire_set.purchase_date = _parse_date(request.form.get('purchase_date'), None)
        tire_set.notes = request.form.get('notes') or None
        tire_set.is_retired = request.form.get('is_retired') == 'on'

        db.session.commit()
        flash(_('Tire set updated'), 'success')
        return redirect(url_for('tires.index'))

    return render_template('tires/form.html', tire_set=tire_set, vehicles=vehicles,
                           selected_vehicle_id=tire_set.vehicle_id, tire_types=TIRE_TYPES)


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
