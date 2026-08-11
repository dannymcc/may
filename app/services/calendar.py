"""Portable calendar serialization helpers for feeds, APIs, and CalDAV."""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass
class CalendarAlarmPayload:
    action: str = 'display'
    trigger_minutes_before: int = 15
    summary: str | None = None
    description: str | None = None
    attendee_email: str | None = None


@dataclass
class CalendarEventPayload:
    uid: str
    summary: str
    start: date | datetime
    description: str | None = None
    end: date | datetime | None = None
    all_day: bool = True
    location: str | None = None
    status: str | None = None
    url: str | None = None
    recurrence_rule: str | None = None
    person_name: str | None = None
    alarms: list[CalendarAlarmPayload] = field(default_factory=list)


def escape_ical(text):
    """Escape text for iCalendar format."""
    if not text:
        return ''
    text = str(text).replace('\\', '\\\\')
    text = text.replace(';', '\\;')
    text = text.replace(',', '\\,')
    text = text.replace('\n', '\\n')
    return text


def format_datetime(dt):
    """Format datetime for iCalendar (UTC/floating compatible)."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.strftime('%Y%m%d')
    return dt.strftime('%Y%m%dT%H%M%SZ')


def format_date(d):
    """Format date for all-day events."""
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime('%Y%m%d')


def _alarm_trigger(minutes_before):
    minutes = max(int(minutes_before or 0), 0)
    if minutes and minutes % 1440 == 0:
        return f'-P{minutes // 1440}D'
    return f'-PT{minutes}M'


def _event_description(event):
    """Description for an event, prefixed with the person it concerns."""
    if not event.person_name:
        return event.description
    person_line = f'Person: {event.person_name}'
    if not event.description:
        return person_line
    return f'{person_line}\n{event.description}'


def create_vevent(event):
    """Create a VEVENT component from a CalendarEventPayload."""
    lines = [
        'BEGIN:VEVENT',
        f'UID:{event.uid}',
        f'DTSTAMP:{format_datetime(datetime.utcnow())}',
        f'SUMMARY:{escape_ical(event.summary)}',
    ]

    description = _event_description(event)
    if description:
        lines.append(f'DESCRIPTION:{escape_ical(description)}')
    if event.location:
        lines.append(f'LOCATION:{escape_ical(event.location)}')
    elif event.person_name:
        lines.append(f'LOCATION:{escape_ical(event.person_name)}')
    if event.person_name:
        lines.append(f'X-MAY-PERSON:{escape_ical(event.person_name)}')
    if event.status:
        lines.append(f'STATUS:{event.status.upper()}')
    if event.url:
        lines.append(f'URL:{escape_ical(event.url)}')
    if event.recurrence_rule:
        rule = event.recurrence_rule
        lines.append(rule if rule.upper().startswith('RRULE:') else f'RRULE:{rule}')

    if event.all_day:
        lines.append(f'DTSTART;VALUE=DATE:{format_date(event.start)}')
        end = event.end
        if end is None:
            start_date = event.start if isinstance(event.start, date) else event.start.date()
            end = start_date + timedelta(days=1)
        lines.append(f'DTEND;VALUE=DATE:{format_date(end)}')
    else:
        lines.append(f'DTSTART:{format_datetime(event.start)}')
        if event.end:
            lines.append(f'DTEND:{format_datetime(event.end)}')

    for alarm in event.alarms:
        action = (alarm.action or 'display').upper()
        if action in ('SMTP', 'EMAIL'):
            action = 'EMAIL'
        elif action not in ('DISPLAY', 'AUDIO'):
            action = 'DISPLAY'

        lines.extend([
            'BEGIN:VALARM',
            f'ACTION:{action}',
            f'TRIGGER:{_alarm_trigger(alarm.trigger_minutes_before)}',
            f'DESCRIPTION:{escape_ical(alarm.description or alarm.summary or event.summary)}',
        ])
        if action == 'EMAIL':
            lines.append(f'SUMMARY:{escape_ical(alarm.summary or event.summary)}')
            if alarm.attendee_email:
                lines.append(f'ATTENDEE:mailto:{alarm.attendee_email}')
        lines.append('END:VALARM')

    lines.append('END:VEVENT')
    return '\r\n'.join(lines)


def payload_from_calendar_event(event):
    """Build a payload from a CalendarEvent, keeping any person context attached."""
    alarms = [
        CalendarAlarmPayload(
            action=alarm.action,
            trigger_minutes_before=alarm.trigger_minutes_before,
            summary=alarm.summary,
            description=alarm.description,
            attendee_email=alarm.attendee_email,
        )
        for alarm in event.alarms
        if alarm.is_enabled and alarm.action != 'none'
    ]
    return CalendarEventPayload(
        uid=event.calendar_uid(),
        summary=event.title,
        description=event.description,
        start=event.start_at,
        end=event.end_at,
        all_day=event.all_day,
        location=event.location,
        status=event.status,
        url=event.url,
        recurrence_rule=event.recurrence_rule,
        person_name=event.person.name if event.person else None,
        alarms=alarms,
    )


def build_icalendar(events, calendar_name, calendar_description=None):
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//May Vehicle Management//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:{escape_ical(calendar_name)}',
    ]
    if calendar_description:
        lines.append(f'X-WR-CALDESC:{escape_ical(calendar_description)}')

    for event in events:
        lines.append(create_vevent(event))

    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines)
