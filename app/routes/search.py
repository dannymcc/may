"""Global search across a user's records (#112)."""
from datetime import datetime

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.models import (
    Expense, FuelLog, Document, Note, Trip, ChargingSession
)

bp = Blueprint('search', __name__, url_prefix='/search')

RESULT_LIMIT = 50


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _apply_dates(query, column, date_from, date_to):
    if date_from:
        query = query.filter(column >= date_from)
    if date_to:
        query = query.filter(column <= date_to)
    return query


@bp.route('/')
@login_required
def index():
    q = request.args.get('q', '').strip()
    date_from = _parse_date(request.args.get('date_from'))
    date_to = _parse_date(request.args.get('date_to'))

    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    results = None
    if vehicle_ids and (q or date_from or date_to):
        like = f'%{q}%'
        results = {}

        expenses = Expense.query.filter(Expense.vehicle_id.in_(vehicle_ids))
        if q:
            expenses = expenses.filter(or_(
                Expense.description.ilike(like),
                Expense.vendor.ilike(like),
                Expense.notes.ilike(like),
                Expense.category.ilike(like),
            ))
        expenses = _apply_dates(expenses, Expense.date, date_from, date_to)
        results['expenses'] = expenses.order_by(Expense.date.desc()).limit(RESULT_LIMIT).all()

        fuel_logs = FuelLog.query.filter(FuelLog.vehicle_id.in_(vehicle_ids))
        if q:
            fuel_logs = fuel_logs.filter(or_(
                FuelLog.station.ilike(like),
                FuelLog.notes.ilike(like),
            ))
        fuel_logs = _apply_dates(fuel_logs, FuelLog.date, date_from, date_to)
        results['fuel_logs'] = fuel_logs.order_by(FuelLog.date.desc()).limit(RESULT_LIMIT).all()

        documents = Document.query.filter(Document.vehicle_id.in_(vehicle_ids))
        if q:
            documents = documents.filter(or_(
                Document.title.ilike(like),
                Document.description.ilike(like),
                Document.original_filename.ilike(like),
            ))
        # Documents have no logged date; filter on issue date where present
        documents = _apply_dates(documents, Document.issue_date, date_from, date_to)
        results['documents'] = documents.order_by(Document.created_at.desc()).limit(RESULT_LIMIT).all()

        notes = Note.query.filter(Note.vehicle_id.in_(vehicle_ids))
        if q:
            notes = notes.filter(or_(
                Note.title.ilike(like),
                Note.content.ilike(like),
            ))
        notes = _apply_dates(notes, Note.date, date_from, date_to)
        results['notes'] = notes.order_by(Note.date.desc()).limit(RESULT_LIMIT).all()

        trips = Trip.query.filter(Trip.vehicle_id.in_(vehicle_ids))
        if q:
            trips = trips.filter(or_(
                Trip.description.ilike(like),
                Trip.start_location.ilike(like),
                Trip.end_location.ilike(like),
                Trip.notes.ilike(like),
            ))
        trips = _apply_dates(trips, Trip.date, date_from, date_to)
        results['trips'] = trips.order_by(Trip.date.desc()).limit(RESULT_LIMIT).all()

        charging = ChargingSession.query.filter(ChargingSession.vehicle_id.in_(vehicle_ids))
        if q:
            charging = charging.filter(or_(
                ChargingSession.location.ilike(like),
                ChargingSession.notes.ilike(like),
            ))
        charging = _apply_dates(charging, ChargingSession.date, date_from, date_to)
        results['charging'] = charging.order_by(ChargingSession.date.desc()).limit(RESULT_LIMIT).all()

    total = sum(len(v) for v in results.values()) if results is not None else 0

    return render_template('search/index.html',
                           q=q,
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''),
                           results=results,
                           total=total,
                           result_limit=RESULT_LIMIT)
