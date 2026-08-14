"""Sidecar <-> iCalendar bridge.

Custom fields are written into the .ics as ``X-MAY-*`` properties so that
clients which round-trip unknown properties (Apple Calendar, DAVx5,
Thunderbird) show and preserve them. But we never *depend* on that: the
sidecar table is the source of truth, and every GET re-merges it. If a client
strips the X-properties -- and some will -- nothing is lost.

Direction of trust:

* GET  -- sidecar overwrites whatever X-properties are in the stored .ics.
* PUT  -- writable X-properties are read back into the sidecar and the fields
          they touch are *locked*, meaning enrichers may no longer overwrite
          them. Read-only telemetry properties in an inbound PUT are ignored.
"""

import hashlib
import re
from datetime import datetime

# field name -> (X-property, kind, writable)
#   kind is one of: int, str, csv, enum
FIELD_SPECS = (
    ('estimate_minutes', 'X-MAY-ESTIMATE-MINUTES', 'int', True),
    ('actual_minutes', 'X-MAY-ACTUAL-MINUTES', 'int', True),
    ('energy', 'X-MAY-ENERGY', 'enum', True),
    ('contexts', 'X-MAY-CONTEXT', 'csv', True),
    ('source_url', 'X-MAY-SOURCE-URL', 'str', True),
    ('source_ref', 'X-MAY-SOURCE-REF', 'str', True),
    ('source_system', 'X-MAY-SOURCE-SYSTEM', 'str', True),
    ('blocked_by', 'X-MAY-BLOCKED-BY', 'csv', True),
    ('blocks', 'X-MAY-BLOCKS', 'csv', True),
    # Telemetry is computed by May. Emitted so it is visible in the client,
    # ignored on the way back in.
    ('reschedule_count', 'X-MAY-RESCHEDULE-COUNT', 'int', False),
    ('slip_days', 'X-MAY-SLIP-DAYS', 'int', False),
    ('touch_count', 'X-MAY-TOUCH-COUNT', 'int', False),
)

WRITABLE_FIELDS = tuple(f for f, _, _, w in FIELD_SPECS if w)
_BY_FIELD = {f: (prop, kind, writable) for f, prop, kind, writable in FIELD_SPECS}
_BY_PROP = {prop.lower(): (f, kind, writable) for f, prop, kind, writable in FIELD_SPECS}

# Derived fields with no typed column are surfaced under this prefix so an
# enricher can invent a field ("X-MAY-D-INVOICE-TOTAL") without a migration.
DERIVED_PREFIX = 'X-MAY-D-'

ENERGY_LEVELS = ('low', 'medium', 'high')


# ---------------------------------------------------------------------------
# vobject helpers
# ---------------------------------------------------------------------------

def _drop(component, prop):
    """Remove every instance of ``prop`` from ``component``."""
    key = prop.lower()
    if key in component.contents:
        del component.contents[key]


def _set(component, prop, value):
    _drop(component, prop)
    if value in (None, '', [], ()):
        return
    line = component.add(prop)
    line.value = str(value)


def _get(component, prop):
    lines = component.contents.get(prop.lower())
    if not lines:
        return None
    value = lines[0].value
    return value.strip() if isinstance(value, str) else value


def _coerce(kind, raw):
    if raw is None:
        return None
    if kind == 'int':
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None
    if kind == 'csv':
        return [part.strip() for part in str(raw).split(',') if part.strip()]
    if kind == 'enum':
        value = str(raw).strip().lower()
        return value if value in ENERGY_LEVELS else None
    value = str(raw).strip()
    return value or None


def _render(kind, value):
    if value in (None, '', [], ()):
        return None
    if kind == 'csv':
        return ','.join(str(v) for v in value)
    return str(value)


# ---------------------------------------------------------------------------
# Merge / extract
# ---------------------------------------------------------------------------

def merge_into_component(component, sidecar):
    """Stamp sidecar state onto a vobject component, in place.

    Called on every read. Sidecar wins over whatever the stored .ics says.
    """
    if sidecar is None:
        return component

    for field, prop, kind, _writable in FIELD_SPECS:
        _set(component, prop, _render(kind, getattr(sidecar, field, None)))

    # Derived fields without a typed column, plus a manifest so a human
    # looking at the raw .ics can tell which values a machine produced.
    for prop in [p for p in list(component.contents) if p.startswith(DERIVED_PREFIX.lower())]:
        del component.contents[prop]

    derived = sidecar.derived or {}
    machine_written = []
    for name, meta in sorted(derived.items()):
        if name in _BY_FIELD:
            # Has a typed column; already emitted above. Just record the origin.
            if not sidecar.is_locked(name):
                machine_written.append(name)
            continue
        value = meta.get('value') if isinstance(meta, dict) else meta
        rendered = ','.join(str(v) for v in value) if isinstance(value, (list, tuple)) else value
        _set(component, DERIVED_PREFIX + name.replace('_', '-').upper(), rendered)
        machine_written.append(name)

    _set(component, 'X-MAY-DERIVED-FIELDS', ','.join(machine_written) if machine_written else None)
    return component


def extract_from_component(component):
    """Read writable X-properties out of an inbound component.

    Returns ``(values, present)`` where ``present`` is the set of fields the
    client actually sent -- those get locked against future enrichment.
    """
    values, present = {}, set()
    for field, prop, kind, writable in FIELD_SPECS:
        if not writable:
            continue
        raw = _get(component, prop)
        if raw is None:
            continue
        coerced = _coerce(kind, raw)
        if coerced is None and kind != 'csv':
            continue
        values[field] = coerced
        present.add(field)
    return values, present


def apply_client_values(sidecar, values, present):
    """Write client-supplied values onto the sidecar and lock those fields."""
    for field, value in values.items():
        setattr(sidecar, field, value)
    for field in present:
        sidecar.lock(field)
    return sidecar


def strip_may_properties(component):
    """Remove every X-MAY-* property. Used before hashing for change
    detection, so our own round-tripped values never look like a client edit."""
    for prop in [p for p in list(component.contents) if p.startswith('x-may-')]:
        del component.contents[prop]
    return component


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def record_touch(sidecar, due_at=None, completed=False, now=None):
    """Update slip telemetry. Call once per inbound write.

    A task whose due date moves later while still open is a reschedule. That
    is the signal worth having: an item rescheduled six times is not a task,
    it is an unmade decision.
    """
    now = now or datetime.utcnow()
    sidecar.touch_count = (sidecar.touch_count or 0) + 1
    sidecar.last_touched_at = now

    if due_at is None:
        return sidecar

    due_at = _as_datetime(due_at)
    if sidecar.first_due_at is None:
        sidecar.first_due_at = due_at
    elif not completed and sidecar.last_due_at and due_at > sidecar.last_due_at:
        sidecar.reschedule_count = (sidecar.reschedule_count or 0) + 1
        sidecar.slip_days = (sidecar.slip_days or 0) + (due_at - sidecar.last_due_at).days

    sidecar.last_due_at = due_at
    return sidecar


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    return datetime(value.year, value.month, value.day)


# ---------------------------------------------------------------------------
# Change detection for the enrichment pipeline
# ---------------------------------------------------------------------------

_WS = re.compile(r'\s+')


def context_digest(*parts):
    """Stable hash of the text an enricher reads.

    Enrichment is skipped when this is unchanged, which keeps an LLM enricher
    from being billed for every DAVx5 poll that rewrites an unchanged event.
    """
    joined = '\x1f'.join(_WS.sub(' ', str(p or '')).strip().lower() for p in parts)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()
