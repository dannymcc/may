# CalDAV facade

May speaks CalDAV. Apple Calendar, Apple Reminders, Fantastical, Thunderbird
and DAVx5 can two-way sync against it, and every item carries a set of extra
fields that iCalendar has no way to express.

The design borrows its shape from Mailpit: **be boringly conformant at the
wire protocol, own the storage, and put the innovation in a superset schema
the protocol never knew about.**

```
 clients ──CalDAV/TLS──▶ /caldav  (Radicale WSGI app, mounted in Flask)
                              │
                    ┌─────────┴─────────┐
                    │ app/caldav/       │
                    │  storage.py       │  Radicale storage plugin
                    │  auth.py          │  → May User + api_key
                    │  rights.py        │  → owner-only
                    │  mapping.py       │  Reminder ↔ VTODO, Event ↔ VEVENT
                    │  sidecar.py       │  X-MAY-* merge / extract
                    │  enrichment.py    │  pluggable field extraction
                    └─────────┬─────────┘
                              ▼
        caldav_collections · caldav_objects · caldav_versions · caldav_sidecar
                              +
                    reminders · calendar_events   (May's own tables)
```

## Setup

```bash
pip install -r requirements.txt   # adds radicale, vobject
flask db upgrade                  # creates the four caldav_* tables
```

Environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CALDAV_ENABLED` | `true` | Set false to skip mounting entirely |
| `CALDAV_PREFIX` | `/caldav` | Mount point inside the Flask app |
| `CALDAV_REALM` | `May` | HTTP Basic realm shown by clients |
| `CALDAV_ALLOW_LLM` | `false` | Enable the model-backed enricher |

If `radicale` is not installed the app still boots; `mount_caldav` logs a
warning and does nothing.

## Connecting a client

Server: `https://your-may-host/caldav/` (or just the hostname — `/.well-known/caldav`
redirects, which is what Apple clients and Fantastical probe first).

Username: your May username. Password: **your API key**, generated at
`/auth/settings`. The account password also works, but prefer the key: CalDAV
clients store the credential in the OS keychain and replay it on every poll,
so you want something revocable that is not your login password.

Two calendars appear:

| Collection | Component | Backed by |
| --- | --- | --- |
| `reminders` | `VTODO` | May `Reminder` rows |
| `events` | `VEVENT` | May `CalendarEvent` rows |

Anything you create in a third collection is stored verbatim and never touches
May's own tables — a plain sink, useful for testing what a client actually
sends.

This replaces the one-way `/api/calendar/feed` subscription for clients that
can do CalDAV. The feed still works and is still the right answer for
read-only subscribers.

## The sidecar contract

Extra fields live in `caldav_sidecar`, keyed by `(user_id, uid, recurrence_id)`.
They are merged into every `GET` as `X-MAY-*` properties and read back on `PUT`.

| Field | Property | Writable by client |
| --- | --- | --- |
| `estimate_minutes` | `X-MAY-ESTIMATE-MINUTES` | yes |
| `actual_minutes` | `X-MAY-ACTUAL-MINUTES` | yes |
| `energy` | `X-MAY-ENERGY` | yes |
| `contexts` | `X-MAY-CONTEXT` | yes |
| `source_url` / `source_ref` / `source_system` | `X-MAY-SOURCE-*` | yes |
| `blocked_by` / `blocks` | `X-MAY-BLOCKED-BY` / `X-MAY-BLOCKS` | yes |
| `reschedule_count` | `X-MAY-RESCHEDULE-COUNT` | no, computed |
| `slip_days` | `X-MAY-SLIP-DAYS` | no, computed |
| `touch_count` | `X-MAY-TOUCH-COUNT` | no, computed |

Dependencies are additionally emitted as `RELATED-TO;RELTYPE=DEPENDS-ON`
(RFC 9253) so clients that understand it get native behaviour.

**The sidecar is the source of truth, not the X-properties.** Some clients
round-trip unknown properties faithfully; Google strips them. Because every
read re-merges from the table and every write only applies the standard fields
we own, a stripping client cannot destroy anything. `tests/test_caldav.py::
TestWriteBack::test_sidecar_survives_a_stripping_client` is the regression
test for exactly this, and is the single most important test in the module.

**A user-set value is never overwritten by a derived one.** When a client sends
`X-MAY-ESTIMATE-MINUTES` explicitly, that field is added to `locked_fields` and
enrichers skip it from then on.

## Slip telemetry

Computed on every write, no user input:

* `touch_count` — every write, including no-op polls that change something.
* `reschedule_count` — increments when an *open* item's due date moves later.
* `slip_days` — cumulative days of that movement.

Pulling a date forward is not a slip. Completing late is not a slip. An item
with a high `reschedule_count` is not a task, it is an unmade decision, and
that is the number worth putting in front of someone.

## Writing an enricher

Enrichers turn free text into structured fields. They run on `PUT`, keyed on a
digest of the text they read, so an unchanged item polled every 15 minutes is
enriched once rather than ninety-six times a day.

```python
from app.caldav.enrichment import Enricher, DerivedValue, register

@register
class InvoiceEnricher(Enricher):
    name = 'invoice'
    version = '1'
    fields = ('invoice_total',)
    priority = 60          # lower runs first; ties broken by confidence

    def applies_to(self, ctx):
        return 'invoice' in ctx.text.lower()

    def run(self, ctx):
        match = re.search(r'£\s?([\d,]+\.\d{2})', ctx.text)
        if not match:
            return {}
        return {'invoice_total': DerivedValue(
            float(match.group(1).replace(',', '')),
            confidence=0.9, evidence=match.group(0))}
```

A field with no column lands in `sidecar.derived` and is surfaced to clients as
`X-MAY-D-INVOICE-TOTAL` — new extractions ship without a migration. Add a
column later only when you want to query or index it.

Every derived value stores `{value, confidence, source, model, evidence,
computed_at}`, so "why does this say 90 minutes?" always has an answer.

### Model-backed enrichment

`LlmEnricher` is registered but inert. Turn it on with `CALDAV_ALLOW_LLM=true`
and install a backend:

```python
from app.caldav.enrichment import set_llm_backend

def backend(prompt, ctx):
    # call your provider, return
    # {"estimate_minutes": {"value": 90, "confidence": 0.8, "evidence": "..."}}
    ...

set_llm_backend(backend)
```

It runs at priority 900, so a deterministic regex match always beats it on a
tie, and its confidence is capped at 0.95 so it can never look more certain
than a literal `X-MAY-*` value. Exceptions are caught and logged — a provider
outage degrades enrichment, it does not fail the CalDAV write.

## History

Every write appends to `caldav_versions`: operation, full `.ics`, ETag,
User-Agent, timestamp. Deletes are tombstones, not row removals, which is also
what makes `sync-collection` able to report deletions.

```python
obj = CalDavObject.query.filter_by(href='may-reminder-12.ics').one()
for v in obj.versions:
    print(v.seq, v.operation, v.author, v.created_at)
```

Nothing purges this yet. Add a retention job before turning it loose on a busy
account.

## Sync

`sync-token` is `http://radicale.org/ns/sync/<n>` where `n` is a per-collection
monotonic counter. Every mutation bumps the collection and stamps the object's
`changed_seq`, so a delta is one indexed range scan. An unknown or future
token raises `ValueError`, which Radicale turns into the "invalid token" response
that makes clients fall back to a full resync.

ETags are derived from the serialized form, and `DTSTAMP` comes from the row's
`updated_at` rather than "now" — otherwise every read would mint a new ETag and
every client would re-download everything on every poll.

## Known gaps

Honest list, roughly in order of how likely you are to hit them:

* **Recurrence exceptions.** `RRULE` round-trips; `RECURRENCE-ID` overrides,
  `EXDATE`, and THISANDFUTURE edits do not. The schema has a `recurrence_id`
  column ready for this; the mapping layer does not use it yet.
* **Timezones.** Events serialize with a `TZID` from `dateutil`, but no
  `VTIMEZONE` component is emitted. Floating and UTC times are fine; named
  zones may drift on clients that will not resolve a bare TZID.
* **`Reminder.recurrence`** only models `monthly`/`yearly` + interval, so an
  inbound `FREQ=WEEKLY` degrades to `none`. May's model is the constraint here,
  not the mapping.
* **No scheduling.** No iTIP/iMIP, no attendees, no free/busy. Refusing to
  implement scheduling avoids a large amount of complexity that a personal
  vehicle log does not need.
* **No push.** CalDAV has no working push; clients poll (~15 min on iOS and
  DAVx5). May's own UI can use its existing channels for anything urgent.
* **Reconciliation is O(rows) per collection read.** Fine at personal scale.
  If it ever is not, drive the index from SQLAlchemy events on `Reminder` and
  `CalendarEvent` instead of re-projecting on read.
* **SQLite and multiple Gunicorn workers.** The storage lock is per-process.
  Either run one worker, or move to Postgres, before you add concurrency.

## Testing

```bash
pytest tests/test_caldav.py -v
```

The enrichment and telemetry tests run without the optional dependencies. The
protocol tests skip unless `radicale` and `vobject` are installed.

Worth doing by hand before trusting it with real data: add the account to
Fantastical and Apple Reminders, create an item in each, edit it in May, and
watch `caldav_versions` to see exactly which client wrote what.
