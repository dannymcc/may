from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db
from app.utils import parse_decimal
from app.models import Vehicle, MileageAllowance

bp = Blueprint('allowance', __name__, url_prefix='/allowance')


@bp.route('/')
@login_required
def index():
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    allowances = MileageAllowance.query.filter(
        MileageAllowance.vehicle_id.in_(vehicle_ids)
    ).order_by(MileageAllowance.date.desc()).all()

    return render_template('allowance/index.html', allowances=allowances, vehicles=vehicles)


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
            return redirect(url_for('allowance.index'))

        try:
            date_str = request.form.get('date')
            allowance = MileageAllowance(
                vehicle_id=vehicle_id,
                user_id=current_user.id,
                date=datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date(),
                description=request.form.get('description') or None,
                distance=parse_decimal(request.form.get('distance')) if request.form.get('distance') else None,
                rate_per_unit=parse_decimal(request.form.get('rate_per_unit')) if request.form.get('rate_per_unit') else None,
                amount=parse_decimal(request.form.get('amount')),
            )
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the date and amount fields.'), 'error')
            return render_template('allowance/form.html', allowance=None, vehicles=vehicles,
                                   selected_vehicle_id=vehicle_id)

        db.session.add(allowance)
        db.session.commit()
        flash(_('Mileage allowance added successfully'), 'success')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    selected_vehicle_id = request.args.get('vehicle_id', type=int) or current_user.default_vehicle_id

    return render_template('allowance/form.html', allowance=None, vehicles=vehicles,
                           selected_vehicle_id=selected_vehicle_id)


@bp.route('/<int:allowance_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(allowance_id):
    allowance = MileageAllowance.query.get_or_404(allowance_id)
    vehicles = current_user.get_all_vehicles()

    # Check access
    if allowance.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('allowance.index'))

    if request.method == 'POST':
        try:
            date_str = request.form.get('date')
            allowance.date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else allowance.date
            allowance.description = request.form.get('description') or None
            allowance.distance = parse_decimal(request.form.get('distance')) if request.form.get('distance') else None
            allowance.rate_per_unit = parse_decimal(request.form.get('rate_per_unit')) if request.form.get('rate_per_unit') else None
            allowance.amount = parse_decimal(request.form.get('amount'))
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the date and amount fields.'), 'error')
            return render_template('allowance/form.html', allowance=allowance, vehicles=vehicles,
                                   selected_vehicle_id=allowance.vehicle_id)

        db.session.commit()
        flash(_('Mileage allowance updated successfully'), 'success')
        return redirect(url_for('vehicles.view', vehicle_id=allowance.vehicle_id))

    return render_template('allowance/form.html', allowance=allowance, vehicles=vehicles,
                           selected_vehicle_id=allowance.vehicle_id)


@bp.route('/<int:allowance_id>/delete', methods=['POST'])
@login_required
def delete(allowance_id):
    allowance = MileageAllowance.query.get_or_404(allowance_id)
    vehicles = current_user.get_all_vehicles()

    # Check access
    if allowance.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('allowance.index'))

    vehicle_id = allowance.vehicle_id
    db.session.delete(allowance)
    db.session.commit()
    flash(_('Mileage allowance deleted successfully'), 'success')
    return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))
