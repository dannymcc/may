from flask import Blueprint, render_template, redirect, url_for, send_from_directory, current_app
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
from app import db
from app.models import Vehicle, FuelLog, Expense, ChargingSession, FuelPriceHistory, FuelStation, MileageAllowance, EXPENSE_CATEGORIES

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    if current_user.is_authenticated:
        # Redirect to user's configured start page
        start_page = current_user.start_page or 'dashboard'
        page_routes = {
            'dashboard': 'main.dashboard',
            'vehicles': 'vehicles.index',
            'fuel': 'fuel.index',
            'fuel_quick': 'fuel.quick',
            'expenses': 'expenses.index',
            'reminders': 'reminders.index',
            'maintenance': 'maintenance.index',
            'recurring': 'recurring.index',
            'documents': 'documents.index',
            'stations': 'stations.index',
            'trips': 'trips.index',
            'charging': 'charging.index',
            'notes': 'notes.index',
            'allowance': 'allowance.index',
        }
        route = page_routes.get(start_page, 'main.dashboard')
        return redirect(url_for(route))
    return redirect(url_for('auth.login'))


@bp.route('/offline')
def offline():
    """Offline page for PWA"""
    return render_template('offline.html')


@bp.route('/sw.js')
def service_worker():
    """Serve service worker from root URL for proper scope"""
    return send_from_directory(
        current_app.static_folder, 'sw.js',
        mimetype='application/javascript'
    )


@bp.route('/dashboard')
@login_required
def dashboard():
    vehicles = current_user.get_all_vehicles()

    # Calculate statistics
    total_fuel_cost = 0
    total_expense_cost = 0
    total_distance = 0
    recent_logs = []
    recent_expenses = []

    vehicle_ids = [v.id for v in vehicles]

    if vehicle_ids:
        # Total costs
        fuel_result = db.session.query(func.sum(FuelLog.total_cost)).filter(
            FuelLog.vehicle_id.in_(vehicle_ids)
        ).scalar()
        total_fuel_cost = fuel_result or 0

        expense_result = db.session.query(func.sum(Expense.cost)).filter(
            Expense.vehicle_id.in_(vehicle_ids)
        ).scalar()
        total_expense_cost = expense_result or 0

        # Total distance (uses user's distance_unit for Tessie conversion; raw logs are in their stored unit)
        for vehicle in vehicles:
            total_distance += vehicle.get_total_distance(current_user.distance_unit)

        # Recent activity
        recent_logs = FuelLog.query.filter(
            FuelLog.vehicle_id.in_(vehicle_ids)
        ).order_by(FuelLog.date.desc(), FuelLog.odometer.desc()).limit(5).all()

        recent_expenses = Expense.query.filter(
            Expense.vehicle_id.in_(vehicle_ids)
        ).order_by(Expense.date.desc()).limit(5).all()

    # Monthly spending for chart (last 6 months)
    monthly_data = get_monthly_spending(vehicle_ids)

    # Calculate total charging cost for EVs
    total_charging_cost = 0
    if vehicle_ids:
        charging_result = db.session.query(func.sum(ChargingSession.total_cost)).filter(
            ChargingSession.vehicle_id.in_(vehicle_ids)
        ).scalar()
        total_charging_cost = charging_result or 0

    # Total mileage allowance received (#208) — offsets running costs
    total_allowance = 0
    if vehicle_ids:
        allowance_result = db.session.query(func.sum(MileageAllowance.amount)).filter(
            MileageAllowance.vehicle_id.in_(vehicle_ids)
        ).scalar()
        total_allowance = allowance_result or 0

    # Calculate cost per distance
    total_cost = total_fuel_cost + total_expense_cost + total_charging_cost
    net_cost = total_cost - total_allowance
    cost_per_distance = None
    if total_distance > 0:
        cost_per_distance = total_cost / total_distance

    # Expenses grouped by category for the dashboard chart (#145),
    # with labels translated server-side
    expenses_by_category = {}
    if vehicle_ids:
        category_rows = db.session.query(
            Expense.category, func.sum(Expense.cost)
        ).filter(
            Expense.vehicle_id.in_(vehicle_ids)
        ).group_by(Expense.category).all()
        expenses_by_category = {
            str(dict(EXPENSE_CATEGORIES).get(cat, (cat or '').capitalize())): round(total, 2)
            for cat, total in category_rows if total
        }

    # Get cheapest stations (most recent prices)
    cheapest_stations = []
    if vehicle_ids:
        subquery = db.session.query(
            FuelPriceHistory.station_id,
            func.max(FuelPriceHistory.date).label('max_date')
        ).group_by(FuelPriceHistory.station_id).subquery()

        cheapest_stations = db.session.query(FuelPriceHistory).join(
            subquery,
            db.and_(
                FuelPriceHistory.station_id == subquery.c.station_id,
                FuelPriceHistory.date == subquery.c.max_date
            )
        ).order_by(FuelPriceHistory.price_per_unit.asc()).limit(3).all()

    return render_template('dashboard.html',
                           vehicles=vehicles,
                           total_fuel_cost=total_fuel_cost,
                           total_expense_cost=total_expense_cost,
                           total_charging_cost=total_charging_cost,
                           total_allowance=total_allowance,
                           net_cost=net_cost,
                           total_cost=total_cost,
                           expenses_by_category=expenses_by_category,
                           total_distance=total_distance,
                           cost_per_distance=cost_per_distance,
                           recent_logs=recent_logs,
                           recent_expenses=recent_expenses,
                           monthly_data=monthly_data,
                           cheapest_stations=cheapest_stations)


def get_monthly_spending(vehicle_ids):
    """Get monthly fuel and expense spending for the last 6 months"""
    months = []
    fuel_costs = []
    expense_costs = []

    now = datetime.now()
    for i in range(5, -1, -1):
        month = now.month - i
        year = now.year
        while month <= 0:
            month += 12
            year -= 1
        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        if month == 12:
            month_end = month_start.replace(year=year + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=month + 1, day=1)

        months.append(month_start.strftime('%b'))

        if vehicle_ids:
            fuel = db.session.query(func.sum(FuelLog.total_cost)).filter(
                FuelLog.vehicle_id.in_(vehicle_ids),
                FuelLog.date >= month_start,
                FuelLog.date < month_end
            ).scalar() or 0

            expense = db.session.query(func.sum(Expense.cost)).filter(
                Expense.vehicle_id.in_(vehicle_ids),
                Expense.date >= month_start,
                Expense.date < month_end
            ).scalar() or 0
        else:
            fuel = 0
            expense = 0

        fuel_costs.append(round(fuel, 2))
        expense_costs.append(round(expense, 2))

    return {
        'labels': months,
        'fuel': fuel_costs,
        'expenses': expense_costs
    }


@bp.route('/timeline/<int:vehicle_id>')
@login_required
def timeline(vehicle_id):
    """Service timeline showing maintenance history and expenses"""
    vehicles = current_user.get_all_vehicles()
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in vehicles:
        return redirect(url_for('main.dashboard'))

    # Get all fuel logs, expenses, and charging sessions for timeline
    fuel_logs = vehicle.fuel_logs.order_by(FuelLog.date.desc(), FuelLog.odometer.desc()).all()
    expenses = vehicle.expenses.order_by(Expense.date.desc()).all()
    charging_sessions = vehicle.charging_sessions.order_by(ChargingSession.date.desc()).all()

    # Combine into timeline events
    timeline_events = []

    for log in fuel_logs:
        timeline_events.append({
            'date': log.date,
            'type': 'fuel',
            'title': f"Fuel: {log.volume:.1f} L" if log.volume else "Fuel Log",
            'description': log.station or '',
            'cost': log.total_cost or 0,
            'odometer': log.odometer
        })

    for expense in expenses:
        timeline_events.append({
            'date': expense.date,
            'type': 'expense',
            'title': expense.description,
            'description': str(dict(EXPENSE_CATEGORIES).get(expense.category, expense.category.capitalize())),
            'cost': expense.cost or 0,
            'odometer': expense.odometer
        })

    for session in charging_sessions:
        timeline_events.append({
            'date': session.date,
            'type': 'charging',
            'title': f"Charging: {session.kwh_added:.1f} kWh" if session.kwh_added else "Charging Session",
            'description': session.location or '',
            'cost': session.total_cost or 0,
            'odometer': session.odometer
        })

    # Sort by date descending
    timeline_events.sort(key=lambda x: x['date'], reverse=True)

    # Prepare chart data - monthly costs for the last 12 calendar months.
    # Walk real calendar months rather than 30-day steps: fixed-size steps
    # drift against month boundaries, duplicating some months and skipping
    # others in the chart (#270).
    chart_data = {'labels': [], 'fuel': [], 'expenses': [], 'charging': []}
    today = datetime.now()
    months = []
    year, month = today.year, today.month
    for _ in range(12):
        months.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    for year, month in reversed(months):
        month_start = datetime(year, month, 1)
        if month == 12:
            month_end = datetime(year + 1, 1, 1)
        else:
            month_end = datetime(year, month + 1, 1)

        chart_data['labels'].append(month_start.strftime('%b %Y'))

        fuel_cost = db.session.query(func.sum(FuelLog.total_cost)).filter(
            FuelLog.vehicle_id == vehicle_id,
            FuelLog.date >= month_start,
            FuelLog.date < month_end
        ).scalar() or 0

        expense_cost = db.session.query(func.sum(Expense.cost)).filter(
            Expense.vehicle_id == vehicle_id,
            Expense.date >= month_start,
            Expense.date < month_end
        ).scalar() or 0

        charging_cost = db.session.query(func.sum(ChargingSession.total_cost)).filter(
            ChargingSession.vehicle_id == vehicle_id,
            ChargingSession.date >= month_start,
            ChargingSession.date < month_end
        ).scalar() or 0

        chart_data['fuel'].append(round(fuel_cost, 2))
        chart_data['expenses'].append(round(expense_cost, 2))
        chart_data['charging'].append(round(charging_cost, 2))

    return render_template('timeline/index.html',
                           vehicle=vehicle,
                           timeline_events=timeline_events,
                           chart_data=chart_data)
