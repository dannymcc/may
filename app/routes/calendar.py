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

from flask import Blueprint, request, Response, url_for
from app import db
from app.models import (
    User, Vehicle, MaintenanceSchedule, RecurringExpense,
    Document, Reminder
)
from datetime import datetime, timedelta, date
from functools import wraps
import hashlib
from app.utils import utcnow

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


def escape_ical(text):
    """Escape text for iCalendar format."""
    if not text:
        return ''
    # Escape backslashes first, then other special chars
    text = str(text).replace('\\', '\\\\')
    text = text.replace(';', '\\;')
    text = text.replace(',', '\\,')
    text = text.replace('\n', '\\n')
    return text


def format_datetime(dt):
    """Format datetime for iCalendar (UTC)."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.strftime('%Y%m%d')
    return dt.strftime('%Y%m%dT%H%M%SZ')


def format_date(d):
    """Format date for all-day events."""
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime('%Y%m%d')


def create_vevent(uid, summary, description, dtstart, dtend=None, all_day=True, alarm_days=7):
    """Create a VEVENT component."""
    lines = [
        'BEGIN:VEVENT',
        f'UID:{uid}',
        f'DTSTAMP:{format_datetime(utcnow())}',
        f'SUMMARY:{escape_ical(summary)}',
    ]

    if description:
        lines.append(f'DESCRIPTION:{escape_ical(description)}')

    if all_day:
        lines.append(f'DTSTART;VALUE=DATE:{format_date(dtstart)}')
        if dtend:
            lines.append(f'DTEND;VALUE=DATE:{format_date(dtend)}')
        else:
            # All-day event for single day
            next_day = dtstart + timedelta(days=1) if isinstance(dtstart, date) else dtstart.date() + timedelta(days=1)
            lines.append(f'DTEND;VALUE=DATE:{format_date(next_day)}')
    else:
        lines.append(f'DTSTART:{format_datetime(dtstart)}')
        if dtend:
            lines.append(f'DTEND:{format_datetime(dtend)}')

    # Add alarm
    if alarm_days > 0:
        lines.extend([
            'BEGIN:VALARM',
            'ACTION:DISPLAY',
            f'TRIGGER:-P{alarm_days}D',
            f'DESCRIPTION:Reminder: {escape_ical(summary)}',
            'END:VALARM'
        ])

    lines.append('END:VEVENT')
    return '\r\n'.join(lines)


@bp.route('/feed')
@token_required
def calendar_feed(user):
    """Generate iCalendar feed with all reminders and schedules."""
    events = []

    # Get all user's vehicles
    vehicles = Vehicle.query.filter_by(owner_id=user.id).all()
    vehicle_ids = [v.id for v in vehicles]

    if not vehicle_ids:
        # Empty calendar
        ical = '\r\n'.join([
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            'PRODID:-//May Vehicle Management//EN',
            'CALSCALE:GREGORIAN',
            'METHOD:PUBLISH',
            f'X-WR-CALNAME:May - {user.username}',
            'END:VCALENDAR'
        ])
        return Response(ical, mimetype='text/calendar')

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
                unit = vehicle.get_reading_unit() if vehicle else 'km'
                description += f"\\nDue at: {schedule.next_due_odometer:.0f} {unit}"
            if schedule.notes:
                description += f"\\nNotes: {schedule.notes}"

            events.append(create_vevent(
                uid=generate_uid('maint', schedule.id, user.id),
                summary=summary,
                description=description,
                dtstart=schedule.next_due_date,
                alarm_days=schedule.remind_days_before or 7
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

            events.append(create_vevent(
                uid=generate_uid('recur', item.id, user.id),
                summary=summary,
                description=description,
                dtstart=item.next_due,
                alarm_days=item.notify_before_days or 7
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

            events.append(create_vevent(
                uid=generate_uid('doc', doc.id, user.id),
                summary=summary,
                description=description,
                dtstart=doc.expiry_date,
                alarm_days=doc.remind_days or 30
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

            events.append(create_vevent(
                uid=generate_uid('remind', reminder.id, user.id),
                summary=summary,
                description=description,
                dtstart=reminder.due_date,
                alarm_days=7
            ))

    # Build the complete iCalendar
    ical_lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//May Vehicle Management//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:May - {user.username}',
        'X-WR-CALDESC:Vehicle reminders, maintenance, and document expiry dates',
    ]

    for event in events:
        ical_lines.append(event)

    ical_lines.append('END:VCALENDAR')

    ical = '\r\n'.join(ical_lines)

    response = Response(ical, mimetype='text/calendar')
    response.headers['Content-Disposition'] = 'attachment; filename="may-calendar.ics"'
    return response


@bp.route('/feed.ics')
@token_required
def calendar_feed_ics(user):
    """Alias for the feed with .ics extension."""
    return calendar_feed(user=user)
