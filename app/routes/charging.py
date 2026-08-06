from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db
from app.utils import parse_decimal
from app.models import Vehicle, ChargingSession, CHARGER_TYPES

bp = Blueprint('charging', __name__, url_prefix='/charging')


@bp.route('/')
@login_required
def index():
    """List all charging sessions"""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    # Only show vehicles that can charge (EVs, hybrids, plug-in hybrids)
    ev_vehicles = [v for v in vehicles if v.is_electric()]

    # Get filter parameters
    vehicle_filter = request.args.get('vehicle', type=int)

    # Base query
    query = ChargingSession.query.filter(ChargingSession.vehicle_id.in_(vehicle_ids))

    # Apply filters
    if vehicle_filter:
        query = query.filter(ChargingSession.vehicle_id == vehicle_filter)

    sessions = query.order_by(ChargingSession.date.desc()).all()

    # Calculate totals
    total_kwh = sum(s.kwh_added or 0 for s in sessions)
    total_cost = sum(s.total_cost or 0 for s in sessions)

    return render_template('charging/index.html',
                           sessions=sessions,
                           vehicles=ev_vehicles,
                           charger_types=CHARGER_TYPES,
                           vehicle_filter=vehicle_filter,
                           total_kwh=total_kwh,
                           total_cost=total_cost)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Create a new charging session"""
    vehicles = current_user.get_all_vehicles()
    ev_vehicles = [v for v in vehicles if v.is_electric()]

    if not ev_vehicles:
        flash(_('No electric vehicles found. Add an EV or hybrid vehicle first.'), 'info')
        return redirect(url_for('vehicles.new'))

    if request.method == 'POST':
        vehicle_id = int(request.form.get('vehicle_id'))
        vehicle = Vehicle.query.get_or_404(vehicle_id)

        if vehicle not in vehicles:
            flash(_('Access denied'), 'error')
            return redirect(url_for('charging.index'))

        date_str = request.form.get('date')
        date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()

        start_time = None
        end_time = None
        if request.form.get('start_time'):
            start_time = datetime.strptime(request.form.get('start_time'), '%H:%M').time()
        if request.form.get('end_time'):
            end_time = datetime.strptime(request.form.get('end_time'), '%H:%M').time()

        session = ChargingSession(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            date=date,
            start_time=start_time,
            end_time=end_time,
            odometer=parse_decimal(request.form.get('odometer')) if request.form.get('odometer') else None,
            kwh_added=parse_decimal(request.form.get('kwh_added')) if request.form.get('kwh_added') else None,
            start_soc=int(request.form.get('start_soc')) if request.form.get('start_soc') else None,
            end_soc=int(request.form.get('end_soc')) if request.form.get('end_soc') else None,
            cost_per_kwh=parse_decimal(request.form.get('cost_per_kwh')) if request.form.get('cost_per_kwh') else None,
            total_cost=parse_decimal(request.form.get('total_cost')) if request.form.get('total_cost') else None,
            charger_type=request.form.get('charger_type'),
            location=request.form.get('location'),
            network=request.form.get('network'),
            notes=request.form.get('notes')
        )

        # Calculate total cost if not provided
        if session.kwh_added and session.cost_per_kwh and not session.total_cost:
            session.total_cost = round(session.kwh_added * session.cost_per_kwh, 2)

        db.session.add(session)
        db.session.commit()

        flash(_('Charging session logged successfully'), 'success')
        return redirect(url_for('charging.index'))

    # Pre-select vehicle if provided
    selected_vehicle_id = request.args.get('vehicle_id', type=int)

    return render_template('charging/form.html',
                           session=None,
                           vehicles=ev_vehicles,
                           charger_types=CHARGER_TYPES,
                           selected_vehicle_id=selected_vehicle_id)


@bp.route('/<int:session_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(session_id):
    """Edit an existing charging session"""
    session = ChargingSession.query.get_or_404(session_id)
    vehicles = current_user.get_all_vehicles()
    ev_vehicles = [v for v in vehicles if v.is_electric()]

    if session.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('charging.index'))

    if request.method == 'POST':
        date_str = request.form.get('date')
        session.date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else session.date

        if request.form.get('start_time'):
            session.start_time = datetime.strptime(request.form.get('start_time'), '%H:%M').time()
        else:
            session.start_time = None
        if request.form.get('end_time'):
            session.end_time = datetime.strptime(request.form.get('end_time'), '%H:%M').time()
        else:
            session.end_time = None

        session.odometer = parse_decimal(request.form.get('odometer')) if request.form.get('odometer') else None
        session.kwh_added = parse_decimal(request.form.get('kwh_added')) if request.form.get('kwh_added') else None
        session.start_soc = int(request.form.get('start_soc')) if request.form.get('start_soc') else None
        session.end_soc = int(request.form.get('end_soc')) if request.form.get('end_soc') else None
        session.cost_per_kwh = parse_decimal(request.form.get('cost_per_kwh')) if request.form.get('cost_per_kwh') else None
        session.total_cost = parse_decimal(request.form.get('total_cost')) if request.form.get('total_cost') else None
        session.charger_type = request.form.get('charger_type')
        session.location = request.form.get('location')
        session.network = request.form.get('network')
        session.notes = request.form.get('notes')

        # Calculate total cost if not provided
        if session.kwh_added and session.cost_per_kwh and not session.total_cost:
            session.total_cost = round(session.kwh_added * session.cost_per_kwh, 2)

        db.session.commit()
        flash(_('Charging session updated successfully'), 'success')
        return redirect(url_for('charging.index'))

    return render_template('charging/form.html',
                           session=session,
                           vehicles=ev_vehicles,
                           charger_types=CHARGER_TYPES,
                           selected_vehicle_id=session.vehicle_id)


@bp.route('/<int:session_id>/delete', methods=['POST'])
@login_required
def delete(session_id):
    """Delete a charging session"""
    session = ChargingSession.query.get_or_404(session_id)
    vehicles = current_user.get_all_vehicles()

    if session.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('charging.index'))

    db.session.delete(session)
    db.session.commit()
    flash(_('Charging session deleted successfully'), 'success')
    return redirect(url_for('charging.index'))
