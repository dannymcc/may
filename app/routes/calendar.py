"""Calendar integration for May.

Provides iCalendar feeds that can be subscribed to by calendar apps like:
- Apple Calendar
- Google Calendar
- Outlook
- Any app supporting webcal:// or .ics subscriptions

To subscribe to the calendar:
1. Generate an API key in Settings
2. Add a new calendar subscription with the URL:
   webcal://your-server/api/calendar/feed?token=YOUR_API_KEY

The feed includes:
- Upcoming maintenance schedules
- Recurring expense due dates
- Document expiry reminders
- Custom reminders
"""

from flask import Blueprint, request, Response
from app.models import (
    User, Vehicle, MaintenanceSchedule, RecurringExpense,
    Document, Reminder, CalendarEvent
)
from app.services.calendar import (
    CalendarAlarmPayload,
    CalendarEventPayload,
    build_icalendar,
    payload_from_calendar_event,
)
from datetime import date
from functools import wraps

bp = Blueprint('calendar', __name__, url_prefix='/api/calendar')


def token_required(f):
    """Decorator to require API token authentication via query param."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get('token')
        if not token:
            return Response('Unauthorized', status=401)

        user = User.query.filter_by(api_key=token).first()
        if not user:
            return Response('Invalid token', status=401)

        kwargs['user'] = user
        return f(*args, **kwargs)
    return decorated


def generate_uid(prefix, item_id, user_id):
    """Generate a unique UID for calendar events."""
    return f"{prefix}-{item_id}-{user_id}@may-vehicle"


def _display_alarm(days, summary):
    days = max(int(days or 0), 0)
    if days == 0:
        return []
    return [CalendarAlarmPayload(
        action='display',
        trigger_minutes_before=days * 1440,
        description=f'Reminder: {summary}',
    )]


@bp.route('/feed')
@token_required
def calendar_feed(user):
    """Generate iCalendar feed with all reminders and schedules."""
    events = []

    # Get all user's vehicles
    vehicles = Vehicle.query.filter_by(owner_id=user.id).all()
    vehicle_ids = [v.id for v in vehicles]

    # Maintenance schedules with due dates
    schedules = MaintenanceSchedule.query.filter(
        MaintenanceSchedule.vehicle_id.in_(vehicle_ids),
        MaintenanceSchedule.is_active == True,
        MaintenanceSchedule.next_due_date != None
    ).all()

    for schedule in schedules:
        if schedule.next_due_date:
            vehicle = next((v for v in vehicles if v.id == schedule.vehicle_id), None)
            vehicle_name = vehicle.name if vehicle else 'Vehicle'

            summary = f"🔧 {schedule.name} - {vehicle_name}"
            description = f"Maintenance due for {vehicle_name}"
            if schedule.next_due_odometer:
                unit = vehicle.get_effective_odometer_unit() if vehicle else 'km'
                description += f"\\nDue at: {schedule.next_due_odometer:.0f} {unit}"
            if schedule.notes:
                description += f"\\nNotes: {schedule.notes}"

            events.append(CalendarEventPayload(
                uid=generate_uid('maint', schedule.id, user.id),
                summary=summary,
                description=description,
                start=schedule.next_due_date,
                alarms=_display_alarm(schedule.remind_days_before or 7, summary),
            ))

    # Recurring expenses
    recurring = RecurringExpense.query.filter(
        RecurringExpense.vehicle_id.in_(vehicle_ids),
        RecurringExpense.is_active == True,
        RecurringExpense.next_due != None
    ).all()

    for item in recurring:
        if item.next_due:
            vehicle = next((v for v in vehicles if v.id == item.vehicle_id), None)
            vehicle_name = vehicle.name if vehicle else 'Vehicle'

            summary = f"💰 {item.name} - {vehicle_name}"
            description = f"Recurring expense due for {vehicle_name}"
            if item.amount:
                currency = vehicle.currency_symbol if vehicle else '£'
                description += f"\\nAmount: {currency}{item.amount:.2f}"
            if item.description:
                description += f"\\nNotes: {item.description}"

            events.append(CalendarEventPayload(
                uid=generate_uid('recur', item.id, user.id),
                summary=summary,
                description=description,
                start=item.next_due,
                alarms=_display_alarm(item.notify_before_days or 7, summary),
            ))

    # Document expiry dates
    documents = Document.query.filter(
        Document.vehicle_id.in_(vehicle_ids),
        Document.expiry_date != None,
        Document.remind_before_expiry == True
    ).all()

    for doc in documents:
        if doc.expiry_date and doc.expiry_date >= date.today():
            vehicle = next((v for v in vehicles if v.id == doc.vehicle_id), None)
            vehicle_name = vehicle.name if vehicle else 'Vehicle'

            summary = f"📄 {doc.title} expires - {vehicle_name}"
            description = f"Document expiry for {vehicle_name}"
            description += f"\\nDocument type: {doc.document_type}"
            if doc.reference_number:
                description += f"\\nReference: {doc.reference_number}"

            events.append(CalendarEventPayload(
                uid=generate_uid('doc', doc.id, user.id),
                summary=summary,
                description=description,
                start=doc.expiry_date,
                alarms=_display_alarm(doc.remind_days or 30, summary),
            ))

    # Custom reminders
    reminders = Reminder.query.filter(
        Reminder.vehicle_id.in_(vehicle_ids),
        Reminder.is_completed == False,
        Reminder.due_date != None
    ).all()

    for reminder in reminders:
        if reminder.due_date:
            vehicle = next((v for v in vehicles if v.id == reminder.vehicle_id), None)
            vehicle_name = vehicle.name if vehicle else 'Vehicle'

            summary = f"⏰ {reminder.title} - {vehicle_name}"
            description = reminder.description or f"Reminder for {vehicle_name}"

            events.append(CalendarEventPayload(
                uid=generate_uid('remind', reminder.id, user.id),
                summary=summary,
                description=description,
                start=reminder.due_date,
                alarms=_display_alarm(reminder.notify_days_before or 7, summary),
            ))

    generic_events = CalendarEvent.query.filter_by(user_id=user.id).all()
    events.extend(payload_from_calendar_event(event) for event in generic_events)

    ical = build_icalendar(
        events,
        calendar_name=f'May - {user.username}',
        calendar_description='Vehicle reminders, maintenance, document expiry dates, and custom calendar events',
    )

    response = Response(ical, mimetype='text/calendar')
    response.headers['Content-Disposition'] = 'attachment; filename="may-calendar.ics"'
    return response


@bp.route('/feed.ics')
@token_required
def calendar_feed_ics(user):
    """Alias for the feed with .ics extension."""
    return calendar_feed(user=user)
