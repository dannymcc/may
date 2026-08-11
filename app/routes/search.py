"""Global search across a user's records (#112)."""
from datetime import datetime, time, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.models import (
    Expense, FuelLog, Document, Note, Trip, ChargingSession, Person, PersonTask,
    PERSON_TASK_STATUSES
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


def _apply_dates_to_timestamp(query, column, date_from, date_to):
    """Apply the date filters to a datetime column, covering the whole end day."""
    if date_from:
        query = query.filter(column >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(column < datetime.combine(date_to, time.min) + timedelta(days=1))
    return query


@bp.route('/')
@login_required
def index():
    q = request.args.get('q', '').strip()
    date_from = _parse_date(request.args.get('date_from'))
    date_to = _parse_date(request.args.get('date_to'))

    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    people = current_user.get_all_people()
    person_ids = [p.id for p in people]

    results = None
    if (vehicle_ids or person_ids) and (q or date_from or date_to):
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

        matched_people = Person.query.filter(Person.id.in_(person_ids))
        if q:
            matched_people = matched_people.filter(or_(
                Person.name.ilike(like),
                Person.email.ilike(like),
                Person.organization.ilike(like),
                Person.role_title.ilike(like),
                Person.notes.ilike(like),
            ))
        # People have no logged date; filter on when they were added
        matched_people = _apply_dates_to_timestamp(matched_people, Person.created_at, date_from, date_to)
        results['people'] = matched_people.order_by(Person.name).limit(RESULT_LIMIT).all()

        person_tasks = PersonTask.query.filter(PersonTask.person_id.in_(person_ids))
        if q:
            person_tasks = person_tasks.filter(or_(
                PersonTask.title.ilike(like),
                PersonTask.description.ilike(like),
            ))
        person_tasks = _apply_dates(person_tasks, PersonTask.due_date, date_from, date_to)
        results['person_tasks'] = person_tasks.order_by(PersonTask.due_date.desc()).limit(RESULT_LIMIT).all()

    total = sum(len(v) for v in results.values()) if results is not None else 0

    return render_template('search/index.html',
                           q=q,
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''),
                           results=results,
                           total=total,
                           result_limit=RESULT_LIMIT,
                           task_status_labels=dict(PERSON_TASK_STATUSES))
