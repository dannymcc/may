"""Bidirectional mapping between May models and iCalendar components.

``Reminder``      <-> VTODO
``CalendarEvent`` <-> VEVENT

The read direction is a projection: build the component from the May row, then
let :mod:`app.caldav.sidecar` stamp the extra fields on top.

The write direction is a *delta apply*, not a replace. Clients send back a
whole .ics, but we only copy across the standard fields we know how to own.
Anything we do not understand is preserved in ``CalDavObject.raw_ics`` and
anything the client dropped from our X-properties is re-added from the sidecar
on the next read. That asymmetry is the whole point -- it is what makes custom
fields survive a client that strips them.
"""

import re
from datetime import date, datetime, time, timedelta, timezone

from dateutil import tz

import vobject

UID_DOMAIN = 'may.local'

# href <-> May row. Stable and reversible, so a client that re-PUTs to the same
# href updates the same row rather than orphaning it.
HREF_RE = re.compile(r'^may-(?P<kind>reminder|event)-(?P<id>\d+)\.ics$')

PRODID = '-//May//Vehicle Manager CalDAV//EN'

# Reminder.recurrence -> RRULE FREQ
FREQ_BY_RECURRENCE = {'monthly': 'MONTHLY', 'yearly': 'YEARLY'}
RECURRENCE_BY_FREQ = {v: k for k, v in FREQ_BY_RECURRENCE.items()}


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def reminder_uid(reminder):
    return f'may-reminder-{reminder.id}@{UID_DOMAIN}'


def event_uid(event):
    return event.calendar_uid()


def href_for(kind, row_id):
    return f'may-{"reminder" if kind == "reminder" else "event"}-{row_id}.ics'


def parse_href(href):
    """``may-reminder-12.ics`` -> ``('reminder', 12)``; ``None`` if not ours."""
    match = HREF_RE.match(href or '')
    if not match:
        return None
    kind = 'reminder' if match.group('kind') == 'reminder' else 'calendar_event'
    return kind, int(match.group('id'))


# ---------------------------------------------------------------------------
# Small vobject helpers
# ---------------------------------------------------------------------------

def new_calendar():
    cal = vobject.iCalendar()
    cal.add('prodid').value = PRODID
    return cal


def _val(component, name, default=None):
    lines = component.contents.get(name.lower())
    if not lines:
        return default
    return lines[0].value


def _text(component, name, default=None):
    value = _val(component, name, default)
    return value.strip() if isinstance(value, str) else value


def _utcnow():
    return datetime.now(timezone.utc)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value


def _as_datetime(value, tzname=None, end_of_day=False):
    """Coerce a date or datetime to a naive UTC-ish datetime for storage.

    May stores naive datetimes, so we normalise here rather than leaking
    tz-aware values into the models.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    clock = time(23, 59, 59) if end_of_day else time(0, 0)
    return datetime.combine(value, clock)


def _tzinfo(name):
    if not name or name.upper() == 'UTC':
        return timezone.utc
    return tz.gettz(name) or timezone.utc


def _rrule_string(recurrence, interval, until=None):
    freq = FREQ_BY_RECURRENCE.get((recurrence or 'none').lower())
    if not freq:
        return None
    parts = [f'FREQ={freq}']
    if interval and int(interval) > 1:
        parts.append(f'INTERVAL={int(interval)}')
    if until:
        parts.append('UNTIL=' + _as_datetime(until).strftime('%Y%m%dT%H%M%SZ'))
    return ';'.join(parts)


def _parse_rrule(value):
    """``FREQ=YEARLY;INTERVAL=2`` -> ``('yearly', 2)``."""
    if not value:
        return 'none', 1
    parts = dict(
        piece.split('=', 1) for piece in str(value).split(';') if '=' in piece)
    recurrence = RECURRENCE_BY_FREQ.get(parts.get('FREQ', '').upper(), 'none')
    try:
        interval = max(int(parts.get('INTERVAL', 1)), 1)
    except (TypeError, ValueError):
        interval = 1
    return recurrence, interval


def _add_alarm(component, minutes_before, summary=None, description=None,
               action='DISPLAY'):
    alarm = component.add('valarm')
    alarm.add('action').value = (action or 'DISPLAY').upper()
    alarm.add('trigger').value = timedelta(minutes=-abs(int(minutes_before or 0)))
    alarm.add('description').value = description or summary or 'Reminder'
    if summary:
        alarm.add('summary').value = summary
    return alarm


def _alarm_minutes(component):
    """Largest lead time across all VALARMs, in minutes. ``None`` if no alarms."""
    leads = []
    for alarm in component.contents.get('valarm', []):
        trigger = _val(alarm, 'trigger')
        if isinstance(trigger, timedelta):
            leads.append(int(abs(trigger.total_seconds()) // 60))
    return max(leads) if leads else None


def _related(component, uids, reltype):
    for uid in uids or []:
        line = component.add('related-to')
        line.value = str(uid)
        line.params['RELTYPE'] = [reltype]


# ---------------------------------------------------------------------------
# Reminder <-> VTODO
# ---------------------------------------------------------------------------

def reminder_to_component(reminder, sidecar=None, vehicle_label=None):
    """Project a May Reminder into a VTODO inside a VCALENDAR."""
    cal = new_calendar()
    todo = cal.add('vtodo')

    todo.add('uid').value = reminder_uid(reminder)
    todo.add('dtstamp').value = _utcnow()
    todo.add('summary').value = reminder.title or 'Reminder'

    if reminder.description:
        todo.add('description').value = reminder.description

    if reminder.due_date:
        # DUE, not DTSTART. The distinction between "when it is owed" and
        # "when I will do it" is most of GTD, and every mainstream UI
        # conflates them. May keeps DUE authoritative.
        todo.add('due').value = _as_date(reminder.due_date)

    categories = [c for c in (reminder.reminder_type, vehicle_label) if c]
    if categories:
        todo.add('categories').value = categories

    if reminder.is_completed:
        todo.add('status').value = 'COMPLETED'
        todo.add('percent-complete').value = '100'
        completed = reminder.completed_at or datetime.utcnow()
        todo.add('completed').value = completed.replace(tzinfo=timezone.utc)
    else:
        todo.add('status').value = 'NEEDS-ACTION'

    rrule = _rrule_string(reminder.recurrence, reminder.recurrence_interval)
    if rrule:
        todo.add('rrule').value = rrule

    if reminder.notify_days_before:
        _add_alarm(todo, int(reminder.notify_days_before) * 24 * 60,
                   summary=reminder.title)

    if sidecar is not None:
        _related(todo, sidecar.blocked_by, 'DEPENDS-ON')
        _related(todo, sidecar.blocks, 'SIBLING')

    return cal


def component_to_reminder(todo, reminder, user_id):
    """Apply an inbound VTODO onto a Reminder. Returns ``(reminder, changed)``.

    Only the fields May owns are copied. Everything else in the component is
    the client's business and is preserved verbatim in ``raw_ics``.
    """
    changed = {}

    def assign(attr, value):
        if getattr(reminder, attr, None) != value:
            changed[attr] = (getattr(reminder, attr, None), value)
            setattr(reminder, attr, value)

    if reminder.user_id is None:
        reminder.user_id = user_id

    assign('title', (_text(todo, 'summary') or 'Untitled')[:100])
    assign('description', _text(todo, 'description'))

    due = _val(todo, 'due') or _val(todo, 'dtstart')
    if due is not None:
        assign('due_date', _as_date(due))

    status = (_text(todo, 'status') or '').upper()
    percent = _text(todo, 'percent-complete')
    completed_at = _val(todo, 'completed')
    is_completed = status == 'COMPLETED' or percent == '100' or completed_at is not None
    assign('is_completed', bool(is_completed))
    if is_completed:
        assign('completed_at', _as_datetime(completed_at) or datetime.utcnow())
    else:
        assign('completed_at', None)

    recurrence, interval = _parse_rrule(_val(todo, 'rrule'))
    assign('recurrence', recurrence)
    assign('recurrence_interval', interval)

    minutes = _alarm_minutes(todo)
    if minutes is not None:
        assign('notify_days_before', max(int(round(minutes / 1440)), 0))

    # A reschedule means the previously-sent notification is stale.
    if 'due_date' in changed or 'is_completed' in changed:
        reminder.notification_sent = False

    return reminder, changed


# ---------------------------------------------------------------------------
# CalendarEvent <-> VEVENT
# ---------------------------------------------------------------------------

def event_to_component(event, sidecar=None, alarms=None):
    """Project a May CalendarEvent into a VEVENT inside a VCALENDAR."""
    cal = new_calendar()
    vevent = cal.add('vevent')

    vevent.add('uid').value = event_uid(event)
    vevent.add('dtstamp').value = _utcnow()
    vevent.add('summary').value = event.title or 'Event'

    if event.description:
        vevent.add('description').value = event.description
    if event.location:
        vevent.add('location').value = event.location
    if event.url:
        vevent.add('url').value = event.url

    tzinfo = _tzinfo(event.timezone)
    if event.all_day:
        vevent.add('dtstart').value = _as_date(event.start_at)
        end = _as_date(event.end_at or event.start_at) + timedelta(days=1)
        vevent.add('dtend').value = end
    else:
        vevent.add('dtstart').value = event.start_at.replace(tzinfo=tzinfo)
        end_at = event.end_at or (event.start_at + timedelta(hours=1))
        vevent.add('dtend').value = end_at.replace(tzinfo=tzinfo)

    if event.status:
        vevent.add('status').value = str(event.status).upper()
    if event.event_type:
        vevent.add('categories').value = [event.event_type]

    if event.recurrence_rule:
        rule = event.recurrence_rule
        if event.recurrence_until and 'UNTIL=' not in rule.upper():
            rule = f'{rule};UNTIL=' + _as_datetime(event.recurrence_until).strftime('%Y%m%dT%H%M%SZ')
        vevent.add('rrule').value = rule

    for alarm in (alarms if alarms is not None else []):
        if getattr(alarm, 'is_enabled', True):
            _add_alarm(vevent, alarm.trigger_minutes_before,
                       summary=alarm.summary or event.title,
                       description=alarm.description,
                       action=(alarm.action or 'display'))

    if sidecar is not None:
        _related(vevent, sidecar.blocked_by, 'DEPENDS-ON')
        _related(vevent, sidecar.blocks, 'SIBLING')

    return cal


def component_to_event(vevent, event, user_id):
    """Apply an inbound VEVENT onto a CalendarEvent. Returns ``(event, changed)``."""
    changed = {}

    def assign(attr, value):
        if getattr(event, attr, None) != value:
            changed[attr] = (getattr(event, attr, None), value)
            setattr(event, attr, value)

    if event.user_id is None:
        event.user_id = user_id
    if not event.external_uid:
        event.external_uid = _text(vevent, 'uid')

    assign('title', (_text(vevent, 'summary') or 'Untitled')[:200])
    assign('description', _text(vevent, 'description'))
    assign('location', (_text(vevent, 'location') or None))
    assign('url', (_text(vevent, 'url') or None))

    dtstart = _val(vevent, 'dtstart')
    dtend = _val(vevent, 'dtend')
    all_day = dtstart is not None and not isinstance(dtstart, datetime)
    assign('all_day', bool(all_day))
    assign('start_at', _as_datetime(dtstart))

    if dtend is not None:
        # All-day DTEND is exclusive per RFC 5545; May stores it inclusive.
        end = _as_datetime(dtend)
        if all_day and end is not None:
            end = end - timedelta(days=1)
        assign('end_at', end)

    if isinstance(dtstart, datetime) and dtstart.tzinfo is not None:
        name = getattr(dtstart.tzinfo, 'zone', None) or str(dtstart.tzinfo)
        assign('timezone', name[:64])

    status = _text(vevent, 'status')
    if status:
        assign('status', status.lower())

    categories = _val(vevent, 'categories')
    if categories:
        first = categories[0] if isinstance(categories, (list, tuple)) else categories
        assign('event_type', str(first)[:50])

    rrule = _val(vevent, 'rrule')
    assign('recurrence_rule', str(rrule)[:500] if rrule else None)

    return event, changed


# ---------------------------------------------------------------------------
# Enrichment context
# ---------------------------------------------------------------------------

def context_from_component(component, uid, user_id, raw_ics='', sidecar=None):
    """Build an :class:`~app.caldav.enrichment.EnrichmentContext` from a component."""
    from app.caldav.enrichment import EnrichmentContext

    categories = _val(component, 'categories') or []
    if isinstance(categories, str):
        categories = [categories]

    return EnrichmentContext(
        uid=uid,
        component=component.name,
        summary=_text(component, 'summary') or '',
        description=_text(component, 'description') or '',
        location=_text(component, 'location') or '',
        url=_text(component, 'url') or '',
        categories=[str(c) for c in categories],
        due=_as_datetime(_val(component, 'due')),
        dtstart=_as_datetime(_val(component, 'dtstart')),
        raw_ics=raw_ics,
        user_id=user_id,
        sidecar=sidecar,
    )


def primary_component(vobject_item):
    """The VEVENT/VTODO/VJOURNAL inside a VCALENDAR wrapper."""
    if vobject_item.name != 'VCALENDAR':
        return vobject_item
    for child in vobject_item.components():
        if child.name in ('VEVENT', 'VTODO', 'VJOURNAL'):
            return child
    return None


def resolve_dependencies(sidecar, find_uid):
    """Turn free-text dependency hints into real UIDs where possible.

    ``find_uid(text)`` should return a UID or ``None``. Unresolved entries are
    kept verbatim -- a dangling human-readable dependency is more useful than
    a silently dropped one.
    """
    for attr in ('blocked_by', 'blocks'):
        values = list(getattr(sidecar, attr, None) or [])
        if not values:
            continue
        resolved = []
        for entry in values:
            resolved.append(entry if '@' in str(entry) else (find_uid(entry) or entry))
        if resolved != values:
            setattr(sidecar, attr, resolved)
    return sidecar
