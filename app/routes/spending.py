"""Unified "Spending" section.

Fuel fill-ups, expenses, and EV charging sessions are the three things that
subtract money from the user. This blueprint presents them as a single
chronological ledger with per-category totals. It is a read-only aggregation:
adding/editing/deleting still happens through the existing fuel, expenses, and
charging blueprints, which this page links to.
"""
from datetime import datetime

from flask import Blueprint, render_template, request, url_for
from flask_login import login_required, current_user
from flask_babel import gettext as _

from app.models import FuelLog, Expense, ChargingSession

bp = Blueprint('spending', __name__, url_prefix='/spending')

# Charging is fuel — energy in, money out — so it is folded into the "fuel"
# category rather than shown as a separate one.
TYPE_FILTERS = ('fuel', 'expenses')


def _flag(name):
    """A show_menu_* flag defaults to on when unset (mirrors the templates)."""
    value = getattr(current_user, name, None)
    return value is None or value


@bp.route('/')
@login_required
def index():
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]
    vehicle_name = {v.id: v.name for v in vehicles}
    has_ev = any(v.is_electric() for v in vehicles)

    # "Fuel" now covers both fill-ups and charges; expenses is the other bucket.
    fuel_enabled = _flag('show_menu_fuel')
    expenses_enabled = _flag('show_menu_expenses')

    type_filter = request.args.get('type')
    if type_filter == 'charging':          # legacy links fold into fuel
        type_filter = 'fuel'
    if type_filter not in TYPE_FILTERS:
        type_filter = None
    vehicle_filter = request.args.get('vehicle', type=int)
    if vehicle_filter not in vehicle_name:
        vehicle_filter = None

    def fetch(model):
        if not vehicle_ids:
            return []
        query = model.query.filter(model.vehicle_id.in_(vehicle_ids))
        if vehicle_filter:
            query = query.filter(model.vehicle_id == vehicle_filter)
        return query.all()

    fuel_logs = fetch(FuelLog) if fuel_enabled else []
    charging = fetch(ChargingSession) if fuel_enabled else []
    expenses = fetch(Expense) if expenses_enabled else []

    totals = {
        'fuel': (sum(l.total_cost or 0 for l in fuel_logs)
                 + sum(c.total_cost or 0 for c in charging)),
        'expenses': sum(e.cost or 0 for e in expenses),
    }
    totals['all'] = totals['fuel'] + totals['expenses']

    entries = []
    if type_filter in (None, 'fuel'):
        for l in fuel_logs:
            entries.append({
                'date': l.date, 'created_at': l.created_at,
                'type': 'fuel', 'type_label': _('Fuel'),
                'vehicle': vehicle_name.get(l.vehicle_id, ''),
                'title': l.station or _('Fuel fill-up'),
                'subtitle': l.fuel_type or '',
                'cost': l.total_cost,
                'edit_url': url_for('fuel.edit', log_id=l.id),
            })
        for c in charging:
            entries.append({
                'date': c.date, 'created_at': c.created_at,
                'type': 'fuel', 'type_label': _('Fuel'),
                'vehicle': vehicle_name.get(c.vehicle_id, ''),
                'title': c.location or _('Charge'),
                'subtitle': c.network or _('Charging'),
                'cost': c.total_cost,
                'edit_url': url_for('charging.edit', session_id=c.id),
            })
    if type_filter in (None, 'expenses'):
        for e in expenses:
            entries.append({
                'date': e.date, 'created_at': e.created_at,
                'type': 'expense', 'type_label': _('Expense'),
                'vehicle': vehicle_name.get(e.vehicle_id, ''),
                'title': e.description,
                'subtitle': e.category,
                'cost': e.cost,
                'edit_url': url_for('expenses.edit', expense_id=e.id),
            })

    entries.sort(key=lambda x: (x['date'], x['created_at'] or datetime.min), reverse=True)

    return render_template('spending/index.html',
                           entries=entries,
                           totals=totals,
                           fuel_enabled=fuel_enabled,
                           expenses_enabled=expenses_enabled,
                           has_ev=has_ev,
                           vehicles=vehicles,
                           type_filter=type_filter,
                           vehicle_filter=vehicle_filter)
