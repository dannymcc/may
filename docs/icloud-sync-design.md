# iCloud Calendar & Reminders Sync — Final Design

**Repo:** `/Volumes/1TB_DAVINCI/may/move/may` · **Branch:** `dev` · **Migration head:** `85b42a298ff2` (`add_person_vehicle_links`, nothing depends on it)
**Owner's goal:** "ensure that icloud calendar and reminders options are fully integratable into the app with all the options being synced with an additional features that better track reminders."

---

## Executive summary

May gains a two-way CalDAV sync engine targeting iCloud (and, for free, any CalDAV server — Fastmail, Nextcloud, Radicale). The user pastes an **app-specific password** generated at appleid.apple.com into Settings → Integrations; May discovers their calendars and Reminders lists, then: **pulls iCloud events** into the existing `CalendarEvent` model as a read-only mirror, **pushes May reminders and person tasks** as VTODOs into one chosen Reminders list, and **syncs completion state both ways** — tick off "MOT booking" on the iPhone during the school run and May marks it complete *and* spawns the next recurrence through the same code path the UI uses, pushing the new occurrence back as a fresh VTODO.

Architecture in one paragraph: a hand-rolled DAV client (`requests` + stdlib XML — six verbs, no `caldav` library) plus one new pure-Python dependency, `icalendar`, for parsing; credentials encrypted at rest with Fernet keyed by a **data-dir keyfile** (not `SECRET_KEY`, which is randomly regenerated per process when unset — `config.py:96-106`); change detection via ctag → RFC 6578 sync-token → etag fallback so an idle hour costs one HTTP request per calendar; every write etag-guarded (`If-Match` / `If-None-Match: *`) so conflicts surface as 412s resolved by last-write-wins with a completion-always-survives carve-out; sync piggybacks the existing hourly scheduler thread with a portable DB lease lock (mandatory — the Dockerfile runs `gunicorn --workers 2`, so that thread already runs twice), plus a synchronous "Sync now" button. "Better track reminders" extras chosen because they compose with sync: **snooze**, **per-reminder notification history** (which doubles as a sync audit trail: "completed via iCloud on your iPhone"), and an **overdue digest** that stays accurate precisely because completions flow back from the phone.

**Headline risk, flagged before any code is written:** iCloud accounts upgraded to the post-iOS-13 Reminders backend (CloudKit) may not surface CalDAV VTODOs in the Reminders app at all. A 30-minute live probe against a real account is the first task (Open question 1); the engine is deliberately server-agnostic so the VTODO path retains full value on other CalDAV servers either way, and a VEVENT+VALARM fallback is specced.

---

## 1. What exists today (every row verified by reading the file)

| Piece | Where | What it gives us |
|---|---|---|
| `CalendarEvent` model | `app/models.py:1112` | `external_uid` (indexed, :1138), `external_calendar_url`, `external_etag`, `source_type`/`source_id`, `timezone`, `recurrence_rule` — built for exactly this. Missing: an **object-href** column (remote hrefs are not always `{uid}.ics`). |
| `CalendarAlarm` model | `app/models.py:1184` | VALARM-shaped alarms with `notification_sent` latching, processed hourly — lets users attach May-side ntfy/Pushover alerts to *imported iCloud events*, something Apple Calendar can't do. |
| ICS writer | `app/services/calendar.py` | Hand-rolled `CalendarEventPayload`, `create_vevent` (:73), `build_icalendar` (:163), `escape_ical` (:31), `_alarm_trigger` (:56). **No parser exists anywhere. No VTODO writer.** |
| Minimal CalDAV publisher | `app/services/caldav.py` | One-way urllib `PUT` of a single event with `If-Match`, Basic auth; called only from `POST /api/v1/calendar/events/<id>/sync/caldav` (`app/routes/api.py:1871`); credentials passed per request, never stored; href derived as `{quote(uid)}.ics`. |
| Read-only ICS feed | `app/routes/calendar.py` | Token-auth feed; `generate_uid` (:58) → `remind-{id}-{user_id}@may-vehicle` (:199), `person-task-{id}-{user_id}@may-vehicle` (:229). |
| Reminder engine | `app/services/reminder_processor.py` | `process_due_reminders` (:22), `process_due_person_tasks` (:115), `process_due_calendar_alarms` (:182); one-shot `notification_sent` latch, reset on reschedule (documented convention, `app/models.py:953-955`). |
| Hourly scheduler | `app/__init__.py` `_start_reminder_scheduler` | Daemon thread, 60 s warmup, `time.sleep(3600)` loop, sequential try/except blocks. **Dockerfile CMD is `gunicorn --workers 2 --threads 4`** → this thread already runs in each worker; survivable for notifications (the `notification_sent` latch), NOT survivable for sync without a lock. |
| Recurrence-on-complete | `app/routes/reminders.py:216` (`complete`, spawn + duplicate guard **inline in the route**); `app/routes/people.py:44/64/104` (`apply_task_status` / `spawn_next_occurrence` / `complete_with_recurrence` — already module-level functions) | Completing a recurring item spawns the next occurrence as a *new row*. Reminder logic must be extracted to a service so sync can reuse it. |
| Credential precedent | `app/routes/auth.py:266,288,295,386` | `smtp_password`, `dvla_api_key`, `tessie_api_token` in `AppSettings` — **all plaintext**. Write-only-field convention exists for `ntfy_token` (`auth.py:338-342`: never rendered back, blank = keep). |
| SSRF guard | `app/security.py:116` `validate_webhook_url` | Scheme + private-IP validation, reusable for custom CalDAV URLs. |
| `SECRET_KEY` handling | `config.py:96-106` | Env var, else **random per-process** with a warning — and with 2 gunicorn workers each importing config independently, two *different* random keys coexist today. |
| DB backends | `config.py:36-66` | SQLite, PostgreSQL, MySQL/MariaDB all supported — locking must be portable. |
| Settings UI | `app/templates/auth/settings.html` | Integrations section at :550, card list at :770, "Calendar Subscription" card at :887. HTMX vendored (`config.py:14`). |
| `requirements.txt` | 18 lines | `requests` and `python-dateutil` already present; no `caldav`, no `icalendar`, no `cryptography`. |

---

## 2. Protocol layer (the part to get exactly right)

### 2.1 Auth & discovery

- **Auth:** HTTP Basic. Username = Apple ID email; password = app-specific password (`xxxx-xxxx-xxxx-xxxx`) the user generates at appleid.apple.com → Sign-In and Security → App-Specific Passwords. May never sees the real Apple password; the panel says so.
- **Bootstrap URL:** `https://caldav.icloud.com/`, user-editable (validated with `validate_webhook_url`) so any CalDAV server works.
- **Step 1 — principal:** `PROPFIND` Depth 0 requesting `<current-user-principal/>`.
- **Step 2 — home set:** `PROPFIND` Depth 0 on the principal requesting `<C:calendar-home-set/>` → e.g. `https://pNN-caldav.icloud.com/123456789/calendars/`. **Persist both** (`principal_url`, `calendar_home_url`) — the partition host is stable per account and skipping re-discovery saves round-trips every sync.
- **Redirect trap:** iCloud answers PROPFIND with `301` to the partition host, and `requests` downgrades redirected non-GET methods to GET, which breaks PROPFIND. The client sends `allow_redirects=False` and manually re-issues the *same method and body* to the `Location` target (cap 3 hops).
- **Step 3 — enumerate collections:** `PROPFIND` Depth 1 on the home set requesting `displayname`, `resourcetype`, `supported-calendar-component-set`, apple `calendar-color`, `CS:getctag`, `DAV:sync-token`. Collections advertising `VEVENT` are calendars; `VTODO` are Reminders lists; skip inbox/outbox/notification resourcetypes. Namespaces: `d="DAV:"`, `c="urn:ietf:params:xml:ns:caldav"`, `cs="http://calendarserver.org/ns/"`. One `requests.Session`, 15 s timeout (matching `caldav.py`), `User-Agent: May-Vehicle-Manager/1.0`.

### 2.2 Change detection: ctag → sync-token → etag diff, in that order

1. **Cheap idle check (every hourly tick):** one Depth-1 `PROPFIND` on the home set for `CS:getctag` covers all collections. Unchanged ctag *and* no dirty local objects → done. One request per account per idle hour.
2. **Incremental diff:** `REPORT sync-collection` (RFC 6578) with the stored `sync_token`, props `getetag` → changed hrefs, `<status>404` entries for deletions, fresh token. iCloud supports this.
3. **Token invalidation fallback** (on `DAV:valid-sync-token` precondition failure): clear the token; for **event** calendars run a `calendar-query` REPORT with a time-range window (−90 days, unbounded future — Open question 6) and diff etags; for the **VTODO** list (small) a full Depth-1 `getetag` listing diffed against stored etags.
4. **Fetch bodies:** `REPORT calendar-multiget` for changed hrefs, batched ≤ 50 per request.

### 2.3 Etag discipline (conflict safety lives here, not in timestamps)

- **Create:** `PUT` with `If-None-Match: *` — UID collision surfaces as 412 instead of a silent overwrite.
- **Update:** `PUT` with `If-Match: <stored etag>` — never blind-write. (Extends the pattern already in `caldav.py`.)
- **Delete:** `DELETE` with `If-Match`; 412 means it changed remotely since we last saw it → re-pull instead of destroying.
- **iCloud rewrites bodies.** Stored ICS never round-trips byte-identical, and PUT responses often omit the ETag header. After any PUT without an ETag, issue a `PROPFIND getetag` on the object and store that. Never detect changes by comparing our serialization to the remote body: remote change ⇔ etag change; local change ⇔ `content_hash` change (§4.3).
- **429 / `Retry-After`:** abort the pass, record `last_sync_status='rate_limited'`, resume next hourly tick. No tight retry loops against iCloud (they trigger lockouts).

### 2.4 UID and href mapping

| Local object | UID on the server | Rationale |
|---|---|---|
| `Reminder` id N, user U | `remind-N-U@may-vehicle` | Identical to the feed's `generate_uid` scheme — one identity per logical item everywhere. |
| `PersonTask` id N, user U | `person-task-N-U@may-vehicle` | Same. |
| Pulled VEVENT | remote `UID` verbatim → `calendar_events.external_uid` | Remote is authoritative for its own objects. |

Pushed VTODOs also carry `X-MAY-TYPE:reminder|person_task` and `X-MAY-ID:<id>` as a recovery belt. UID is the primary key of the sync relationship; **href is stored, never derived** (iCloud may assign hrefs that aren't `{uid}.ics`; the `{quote(uid)}.ics` convention from `caldav.py` is only the *initial* PUT target).

**UX note:** a user who both subscribes to the read-only feed *and* enables sync sees duplicates (same UIDs in two collections; clients don't dedupe across collections). The settings panel says so and suggests removing the feed subscription once sync is on.

---

## 3. Dependencies: hand-rolled DAV client + `icalendar`, not the `caldav` package

- **Rejected: `python-caldav`.** Drags in `lxml` (C extension — slower multi-arch builds on `python:3.12-slim`), `vobject`, `recurring-ical-events`, and `icalendar` anyway; its abstraction hides exactly the redirect/etag behavior we must control, and iCloud quirks need custom handling on top regardless. The fork precedent is hand-rolled (`caldav.py`, `calendar.py`).
- **Rejected: fully hand-rolled parsing.** Writing ICS is easy (we already do); *parsing* RFC 5545 is a bug farm — line unfolding, parameter quoting, `TZID`/`VTIMEZONE`, `DATE` vs `DATE-TIME`, escaped text, Apple's `X-` soup.
- **Chosen:** HTTP via `requests` (present), WebDAV XML via stdlib `xml.etree.ElementTree` (responses come from the user's own authenticated server; ET doesn't resolve external entities by default — still parse defensively), parsing via **`icalendar>=6.0`** (pure Python; transitive deps `python-dateutil` — already present — and `tzdata`). Timezone conversion via stdlib `zoneinfo`. Writing continues through the existing builder, extended with `create_vtodo()`.

`requirements.txt` diff: `+ icalendar>=6.0`, `+ cryptography>=42.0` (§5; the only compiled addition, near-universal manylinux/musllinux wheels for the image's amd64+arm64 targets).

---

## 4. Data model & migration

**One migration file, fork rule honoured:** random uuid4-hex revision id (`python -c "import uuid; print(uuid.uuid4().hex[:12])"`), `down_revision = '85b42a298ff2'`, filename `migrations/versions/<randid>_add_caldav_sync_and_reminder_tracking.py`. Use `op.batch_alter_table` for the SQLite column additions.

### 4.1 `caldav_accounts` — one per user (unique constraint; drop it for multi-account v2)

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | Integer FK `users.id`, **unique**, not null | |
| `server_url` | String(500), default `'https://caldav.icloud.com'` | validated with `validate_webhook_url` when user-supplied |
| `username` | String(255), not null | Apple ID email |
| `password_encrypted` | Text, not null | Fernet token (§5) |
| `principal_url` / `calendar_home_url` | String(500) | persisted discovery results |
| `sync_enabled` | Boolean, default True | user pause toggle |
| `status` | String(20), default `'connected'` | `connected` / `error` / `auth_failed` / `needs_reauth` / `rate_limited` |
| `consecutive_failures` | Integer, default 0 | drives notify-after-3 for transient errors |
| `auth_failed_notified` | Boolean, default False | one notification per auth-failure episode, cleared on success |
| `last_sync_at` | DateTime | |
| `last_sync_status` | String(20) | `ok` / `partial` / `failed` |
| `last_sync_error` | Text | shown verbatim in Settings |
| `last_sync_summary` | String(255) | "14 events in, 6 tasks out, 2 completions in" |
| `sync_lease_until` | DateTime | cross-process lock (§6.5) |
| `created_at` / `updated_at` | DateTime | house style |

Why a table instead of `User` columns: `users` already carries ~40 columns; sync needs ~10 status/lock/discovery fields that don't belong on the auth model; credentials and state live and die together on disconnect (one `DELETE`, cascading); and multi-account v2 is one dropped constraint away.

### 4.2 `caldav_collections` — discovered calendars/lists + per-collection cursor

| Column | Type | Notes |
|---|---|---|
| `id` / `account_id` | PK / FK `caldav_accounts.id`, not null, cascade delete | |
| `href` | String(500), not null | `UniqueConstraint(account_id, href)` |
| `display_name` | String(255) | |
| `color` | String(20) | apple calendar-color, for UI chips |
| `component_type` | String(10) | `'VEVENT'` or `'VTODO'` from `supported-calendar-component-set` |
| `role` | String(20), default `'none'` | `'pull_events'` (checked calendar) / `'push_tasks'` (the one chosen Reminders list; server enforces ≤ 1 per account) / `'none'` |
| `ctag` | String(255) | cheap idle check |
| `sync_token` | String(500) | RFC 6578 cursor |
| `last_synced_at` / `created_at` | DateTime | |

Re-discovery upserts by href and **preserves existing `role` choices**.

### 4.3 `caldav_task_links` — Reminder/PersonTask ⇄ VTODO mapping

| Column | Type | Notes |
|---|---|---|
| `id` / `collection_id` | PK / FK `caldav_collections.id`, not null | |
| `target_type` | String(20), not null | `'reminder'` / `'person_task'` |
| `target_id` | Integer, not null | `UniqueConstraint(target_type, target_id)`; no FK (polymorphic; tombstones must outlive the May row) |
| `uid` | String(255), not null | index `(collection_id, uid)` |
| `href` | String(500), not null | actual remote href — never derived after creation |
| `etag` | String(255) | last known remote etag |
| `content_hash` | String(64) | sha256 of the last payload **we generated**; local-dirty ⇔ current hash ≠ stored hash — immune to iCloud body rewrites and to `updated_at` bumps from non-synced fields |
| `last_pushed_at` | DateTime | observability |
| `pending_delete` | Boolean, default False | local row deleted → next sync `DELETE`s the VTODO, then removes the link (works offline, retries) |
| `remote_deleted_at` | DateTime, nullable | user deleted it in Reminders → stop pushing, **never resurrect** (without this tombstone, the "no link → create" push rule would immediately re-push a remotely-deleted item) |
| `last_synced_at` | DateTime | |

A link table beats adding `external_*` columns to both `reminders` and `person_tasks`: one migration surface, uniform dirty/tombstone logic, and spawn-on-complete recurrence (new rows) maps naturally to new links.

### 4.4 Pull side reuses `CalendarEvent` almost as-is

One added column: `calendar_events.external_href` String(500) (object href; existing `external_calendar_url` keeps its publisher semantics: collection URL). Imported events get `source_type='caldav'`, `source_id=collection.id`, upsert key `(user_id, external_uid)` — `external_uid` is already indexed.

### 4.5 Extras columns/tables (§8)

- `reminders.snoozed_until` DateTime nullable; `person_tasks.snoozed_until` DateTime nullable.
- **`notification_log`**: `id` PK; `user_id` FK not null (indexed); `target_type` String(20) (`reminder`/`person_task`/`calendar_alarm`/`digest`/`sync`); `target_id` Integer nullable; `channel` String(20) (`email`/`webhook`/`ntfy`/`pushover`/`icloud_sync`); `title` String(255); `status` String(10) (`sent`/`failed`); `error` Text; `created_at` DateTime (indexed). Retention: prune rows > 180 days in the hourly loop.
- On `users`: `digest_enabled` Boolean default False, `digest_hour` Integer default 8, `last_digest_date` Date nullable.

---

## 5. Credential storage — encrypted at rest, keyed by a data-dir keyfile (concrete recommendation)

**Recommendation: Fernet (`cryptography`), key material in `data/.credential_key` — not derived from `SECRET_KEY`, and not the plaintext-`AppSettings` precedent.**

- **Why not plaintext** (despite `smtp_password`/`tessie_api_token`/`ntfy_token` precedent): an app-specific password unlocks the user's entire iCloud CalDAV surface, and the realistic leak vector for a self-hosted app is the SQLite file itself — copied into casual backups, attached to bug reports, synced offsite. DB-only exposure is the common case, and encryption defeats it.
- **Why not HKDF(`SECRET_KEY`)** (the obvious alternative, considered and rejected): `config.py:96-106` generates a **random per-process** key when the env var is unset — and with `--workers 2`, the two gunicorn workers hold two *different* random keys today. Credentials encrypted under one worker's key would be unreadable by the other and by every future restart. Gating the Connect button on `os.environ['SECRET_KEY']` being set patches this but adds setup friction and still bricks credentials on legitimate `SECRET_KEY` rotation. The keyfile has neither failure mode.
- **Mechanism:** new `app/services/credentials.py` (~40 lines): `get_fernet()` lazily creates `data/.credential_key` (32 urlsafe-random bytes, `chmod 0600`; `docker-entrypoint.sh` already normalizes bind-mount ownership) beside `may.db`; `encrypt_secret(str) -> str` / `decrypt_secret(str) -> str`. Optional `MAY_CREDENTIAL_KEY` env var overrides the file for operators who want the key off-volume (Open question 7). `InvalidToken` on decrypt (key replaced) → account `status='needs_reauth'` with error "credential key changed — re-enter your app-specific password"; never an unhandled exception in the scheduler.
- **Honest limits, documented in the panel help text:** keyfile and DB share a volume, so this protects DB-only leaks, not full-volume compromise.
- The password field follows the existing write-only convention (`auth.py:338-342`): never rendered back; blank = keep.

---

## 6. Sync engine

Two new modules, cleanly layered (satisfies the "new `app/services/caldav_sync.py`" requirement with the protocol split out):

- **`app/services/caldav_client.py`** — protocol only, no May models: `discover(server_url, username, password)`, `propfind`, `report` (sync-collection / calendar-multiget / calendar-query), `put(url, ics, etag=None, create=False)`, `delete(url, etag)`; manual PROPFIND-safe redirect replay (§2.1); ~250 lines.
- **`app/services/caldav_sync.py`** — engine: `sync_account(account)`, `pull_events`, `pull_task_state`, `push_tasks`; mapping, conflict policy, status machine, lease lock; the only module touching the DB; ~400 lines.
- Existing `app/services/caldav.py` keeps its API contract (`api.py:1871` unchanged) but `publish_event` is reimplemented over `caldav_client`, killing the urllib duplicate.

### 6.1 Direction matrix (v1 vs v2)

| Flow | v1 | v2 |
|---|---|---|
| iCloud VEVENTs → May `CalendarEvent` | **Pull, read-only mirror** incl. edits + deletions; May-local `CalendarAlarm`s allowed on imported events (ntfy/Pushover alerts on iCloud events — a genuine differentiator) | Two-way event editing; bulk push of May-native events |
| May `Reminder`/`PersonTask` → iCloud VTODO | **Create/update/complete/delete push** to one chosen list | Per-person Reminders lists |
| Completion / due-date / title edits on linked VTODOs → May | **Yes** (the headline feature) | Import *foreign* VTODOs created in the Reminders app |
| Alarms | Push one `VALARM` from `notify_days_before`; pulled VALARMs ignored | Map pulled VALARMs → `CalendarAlarm` |
| Recurrence | **No RRULE emitted** (§6.3); pulled event RRULEs stored verbatim in `recurrence_rule`, not expanded | RRULE expansion for dashboards |

### 6.2 Pull events (`role='pull_events'` collections)

Upsert keyed `(user_id, external_uid)`. Map `DTSTART/DTEND` → naive-UTC `start_at`/`end_at` via `zoneinfo` (original TZID stored in `timezone`); `VALUE=DATE` → `all_day=True`; `SUMMARY/DESCRIPTION/LOCATION/STATUS/URL/RRULE` → obvious columns; etag → `external_etag`, href → `external_href`. Remote deletion (sync-collection 404) → delete the local mirror row (safe: read-only mirror; cascade removes its alarms). Read-only is enforced twice: edit/delete UI hidden when `source_type='caldav'`, and the REST update/delete endpoints in `app/routes/api.py` return 409 for such events. Pulled events flow into the existing feed, dashboard, and `process_due_calendar_alarms` for free.

### 6.3 Push tasks (`role='push_tasks'` list): Reminder/PersonTask → VTODO

Serializer additions in `app/services/calendar.py`: `CalendarTodoPayload` + `create_vtodo()` + `payload_from_reminder()` / `payload_from_person_task()`, reusing `escape_ical` and `_alarm_trigger`:

| May | VTODO |
|---|---|
| link UID (feed scheme) | `UID` |
| `title` (+ vehicle/person prefix, reusing the feed's labeling) | `SUMMARY` |
| `description` | `DESCRIPTION` |
| `due_date` (both models are `db.Date`) | `DUE;VALUE=DATE` |
| `Reminder.is_completed`/`completed_at`; `PersonTask.status=='done'` | `STATUS:COMPLETED` + `COMPLETED:<utc>` + `PERCENT-COMPLETE:100`; else `NEEDS-ACTION` (`in_progress` → `IN-PROCESS`; `blocked` → `NEEDS-ACTION` + `X-MAY-BLOCKED:TRUE`) |
| `PersonTask.priority` | `PRIORITY`: urgent→1, high→4, normal→omit, low→9 (Apple buckets 1-4 high / 5 med / 6-9 low); reminders omit |
| `notify_days_before` | one `VALARM ACTION:DISPLAY`, `TRIGGER:-P{n}D` — the iPhone alerts natively at May's configured lead time |
| context | `CATEGORIES` = vehicle/person name; `X-MAY-TYPE` / `X-MAY-ID` |

**Recurrence: never emit `RRULE`.** May's model (verified: `reminders.py:216` spawn-on-complete with duplicate guard; `people.py:64` `spawn_next_occurrence`) creates the next occurrence on completion. An RRULE VTODO would make Apple spawn its own next occurrence too → duplicates. Each occurrence is a one-shot VTODO; the spawned row gets its own link and is pushed in the same pass.

Push set: rows with `user_id == account.user_id` only (shared-circle items owned by other users stay out — Open question 4), skipping links with `remote_deleted_at`. Dirty ⇔ no link, or `sha256(current payload) != link.content_hash`. Writes per §2.3; after PUT, refresh etag if omitted, store `content_hash` and `last_pushed_at`. `pending_delete` links → `DELETE` with `If-Match`, then drop the link; on 412 leave the remote copy (it changed — don't destroy) and drop the link anyway.

### 6.4 Completion reconciliation & conflicts

**Order matters twice:** within a pass, *pull before push* (a remote `COMPLETED` lands before we push a stale `NEEDS-ACTION`; the etag guard would catch it anyway — ordering avoids 412 churn). In the hourly loop, *sync before `process_due_reminders()`* so freshly pulled due-date changes notify correctly.

- **Remote completed → local:** must run the *same* code paths as the UI so recurrence spawns and duplicate guards apply. Refactor: extract the body of `reminders.complete` into `app/services/reminder_actions.py::complete_reminder(reminder, source='ui')` (+ `uncomplete_reminder`); move `apply_task_status`/`spawn_next_occurrence`/`complete_with_recurrence` from `people.py` into the same module. Routes keep flash/redirect; sync calls the services. Log `notification_log(channel='icloud_sync', title='Completed via iCloud: …')`.
- **Remote un-completed → local:** mirror `uncomplete` semantics (`is_completed=False, completed_at=None`; task → `todo`). If a spawned next occurrence already exists, leave it — matches the existing duplicate-guard philosophy (`reminders.py:233-246`).
- **Remote `DUE` changed → local:** update `due_date` **and reset `notification_sent=False`** — the model's documented reschedule convention (`models.py:953-955`).
- **412 on push (both sides changed):** re-fetch, then **whole-object last-write-wins** comparing remote `LAST-MODIFIED` vs local `updated_at`, ties → May wins (the richer record) — with one carve-out: **a completion on either side always survives**; un-doing a completion requires the newer side to explicitly say `NEEDS-ACTION`. Push the merged result so both sides converge. Field-level merge is v2; with one writer per side this is rare.
- **Remote VTODO deleted:** set `remote_deleted_at` tombstone; keep the May row; never resurrect; surface the count in settings ("3 reminders were deleted in Apple Reminders — unlinked"). (Alternative semantics — Open question 3.)
- **Local deleted:** delete routes set `pending_delete=True` on the link instead of orphaning it; the next pass propagates (§6.3).

### 6.5 Cadence, locking, and the 2-worker problem

- **Hourly:** a third try/except block in `reminder_loop` (`app/__init__.py`, same pattern as the existing two), placed **before** the reminder-processor block: `process_caldav_sync()` iterates accounts where `sync_enabled AND status NOT IN ('auth_failed','needs_reauth')`, each in its own try/except.
- **Lease lock (mandatory):** the scheduler thread runs in each of the 2 gunicorn workers, and "Sync now" adds a third path. Per-account optimistic claim: `UPDATE caldav_accounts SET sync_lease_until = :now_plus_10min WHERE id = :id AND (sync_lease_until IS NULL OR sync_lease_until < :now)` — proceed only if rowcount == 1, clear on finish. Portable across SQLite/Postgres/MySQL (all supported per `config.py`); also serializes manual-vs-scheduled sync.
- **Manual "Sync now":** synchronous in the request handler (ctag short-circuit makes warm syncs a handful of requests; 15 s per-call timeouts bound the worst case), returns an HTMX partial; 60 s cooldown since `last_sync_at`.
- **Failure policy:** 401 → `auth_failed`, halt until reconnect, notify once (`auth_failed_notified` latch). 403/5xx/timeout → `status='error'`, retry next hour, notify only after 3 consecutive failures. 429 → `rate_limited`, resume next tick. Mappings survive reconnection because they key on UID, not credentials.
- **Idle cost:** one PROPFIND per account per hour + zero writes when nothing is dirty.

---

## 7. Settings UI, routes, error surfacing

New blueprint `app/routes/caldav_settings.py` (`url_prefix='/settings/caldav'`, registered in `create_app`), all `@login_required`, **not admin-gated** — credentials are personal, unlike DVLA/Tessie. Keeps `auth.py` from growing further.

| Route | Method | Does |
|---|---|---|
| `/connect` | POST | validate `server_url` → `discover()` → encrypt + store account, upsert collections, render picker partial; 401 → inline "check your app-specific password" with a link to the appleid.apple.com walkthrough |
| `/test` | POST | re-run discovery with stored creds; HTMX inline ok/fail badge; updates `status` |
| `/collections` | POST | save `pull_events` checkboxes + `push_tasks` radio (server enforces ≤ 1) |
| `/sync` | POST | manual sync (lease + 60 s cooldown); returns status partial with fresh `last_sync_summary` |
| `/pause` | POST | toggle `sync_enabled` |
| `/disconnect` | POST | delete account row (cascades collections + links); confirm dialog offers "also remove the N imported events" (`source_type='caldav'`) |
| `/status` | GET | HTMX-polled partial: last sync time/status/error, per-collection counts |

**UI:** card "iCloud Calendar & Reminders" in Settings → Integrations (`section-integrations`, `settings.html:550`), next to "Calendar Subscription" (:887), as partial `app/templates/auth/_caldav_settings.html`. States: *disconnected* (form + app-specific-password walkthrough + "your Apple password is never used") → *connected* (status chip green/amber/red from `account.status`, `last_sync_summary`, `last_sync_error` verbatim on failure, calendar picker with color chips, Reminders-list radio, Sync now / Pause / Disconnect). All buttons HTMX (`hx-post`, swap the partial) — the stack is already vendored. Password field never pre-filled.

**Ambient error surfacing:** dismissible banner partial on the Reminders index and dashboard when `status in ('auth_failed','needs_reauth')`; one-shot notification through the user's existing `NotificationService` channel on auth failure and after 3 consecutive transient failures; all recorded in `notification_log`, so the history view (§8.2) doubles as a sync audit trail.

---

## 8. "Better track reminders" extras (each composes with sync)

1. **Snooze** — `snoozed_until` on both tables; `POST /reminders/<id>/snooze` and `POST /people/<person_id>/tasks/<task_id>/snooze` (matching existing route shapes) with presets 1 d / 3 d / 1 w / custom. Semantics: processors skip items with `snoozed_until > now`, **and snoozing resets `notification_sent=False`** so the alert re-arms and fires when the snooze lapses — turning the one-shot notification into a repeatable nudge. **Composes:** snooze shifts *notification*, not `due_date`, so it never dirties the synced VTODO (CalDAV has no snooze); the server keeps the true due date, May just stops nagging. Snoozed items are excluded from the digest.
2. **Per-reminder notification history** — `notification_log` written by `NotificationService.send_notification` (`notifications.py:173`), the digest, and the sync engine. Surfaced as an HTMX partial (`GET /reminders/<id>/history`) on the reminder/task edit pages: every send, channel, success/failure — and iCloud-sourced completions ("completed via iCloud on your iPhone"). **Composes:** answers the two trust questions every syncing system raises — "did May actually notify me?" and "where was this ticked off?" — and gives send failures somewhere visible to land instead of only the container log.
3. **Overdue digest** (v1.1) — opt-in `digest_enabled`/`digest_hour`; `process_daily_digests()` in `reminder_processor.py`, called from the hourly loop: when the hour has passed and `last_digest_date < today`, send one message listing overdue + due-today + due-in-7-days items (excluding snoozed) plus *completed via iCloud since the last digest* (from `notification_log`); stamp `last_digest_date`; log as `target_type='digest'`. **Composes:** because completions flow back from the phone, the digest is accurate — items ticked off in Reminders yesterday don't reappear, which is exactly what makes digests from non-syncing tools useless. Hour is server-local like the rest of the app (Open question 5).

---

## 9. File-level implementation map

| File | Change |
|---|---|
| `requirements.txt` | + `icalendar>=6.0`, `cryptography>=42.0` |
| `app/services/credentials.py` | **new** — Fernet + data-dir keyfile + `MAY_CREDENTIAL_KEY` override (§5) |
| `app/services/caldav_client.py` | **new** — DAV verbs, discovery, redirect replay, XML in/out (§2, §6) |
| `app/services/caldav_sync.py` | **new** — engine, status machine, lease lock (§6) |
| `app/services/reminder_actions.py` | **new** — `complete_reminder`/`uncomplete_reminder` extracted from `routes/reminders.py:216`; `apply_task_status`/`spawn_next_occurrence`/`complete_with_recurrence` moved from `routes/people.py`; routes and sync both call these |
| `app/services/calendar.py` | + `CalendarTodoPayload`, `create_vtodo`, `payload_from_reminder`, `payload_from_person_task`; + `parse_icalendar()` wrapper around the `icalendar` lib |
| `app/services/caldav.py` | reimplement `publish_event` over `caldav_client`; API contract at `api.py:1871` unchanged |
| `app/services/notifications.py` | write `notification_log` rows inside `send_notification` |
| `app/services/reminder_processor.py` | snooze gating in both processors; + `process_daily_digests()` (v1.1) |
| `app/models.py` | + `CalDAVAccount`, `CalDAVCollection`, `CalDAVTaskLink`, `NotificationLog`; `CalendarEvent.external_href`; snooze/digest columns |
| `migrations/versions/<uuid4hex12>_add_caldav_sync_and_reminder_tracking.py` | **new** — random id, `down_revision='85b42a298ff2'`, `batch_alter_table` for SQLite |
| `app/__init__.py` | register blueprint; third scheduler block (sync **before** reminder processing) |
| `app/routes/caldav_settings.py` | **new** blueprint (§7) |
| `app/routes/reminders.py`, `app/routes/people.py` | delegate complete/uncomplete to `reminder_actions`; snooze routes; deletes set `pending_delete` on links |
| `app/routes/api.py` | 409 on update/delete of `source_type='caldav'` events |
| `app/templates/auth/_caldav_settings.html`, `app/templates/partials/caldav_status_banner.html` | **new** partials; card in `settings.html` Integrations section |
| Reminder/task templates | snooze menu; history partial; "synced / pending / from iCloud" badge driven by `caldav_task_links` |
| Tests | `tests/test_caldav_client.py` (XML fixtures, redirect replay, no network); `tests/test_caldav_sync.py` (fake-transport dict server: ctag short-circuit, sync-token invalidation fallback, 412 LWW + completion carve-out, tombstone no-resurrect, VTODO round-trip through `icalendar`); `tests/test_reminder_extras.py` (snooze re-arm, log rows) |

---

## 10. v1 scope cut (buildable in one session)

**Step 0, before any code: 30-minute live probe** against a real iCloud account — does a CalDAV-PUT VTODO appear in the iOS Reminders app? (Open question 1.) The rest of v1 is unaffected either way; the answer decides whether the fallback in Q1 gets promoted.

**In (ordered; each step lands independently on `dev`):**
1. Migration (all tables/columns, random id) + models + `credentials.py`.
2. `caldav_client.py`: discovery + the six verbs + redirect replay.
3. Settings blueprint + panel: connect / test / collection pickers / disconnect.
4. `caldav_sync.py`: event pull (read-only mirror, API 409 guard) → VTODO push → completion/due-date pull with `reminder_actions` refactor; etag discipline; ctag/sync-token change detection; lease lock; hourly block + Sync now; status machine + error surfacing.
5. Snooze (columns landed in step 1; routes + processor gate + buttons).

**Out to v1.1 (fast follows, days not weeks):** notification history UI (the table and the sync-engine writes land in v1; the `NotificationService` hook and the history partial follow) · overdue digest · status banner on dashboard/reminders pages · auth-failure push notification.

**Out to v2:** two-way event editing · bulk push of May-native events · importing foreign VTODOs (needs an "Inbox" concept) · per-person Reminders lists · multi-account · field-level merge · RRULE expansion · pulled-VALARM mapping · MKCALENDAR "create a May list" · sync-run audit table.

---

## 11. Open questions for the owner

1. **Biggest risk — modern iCloud Reminders visibility.** Accounts upgraded to post-iOS-13 Reminders (CloudKit) may not display CalDAV VTODOs in the Reminders app at all. Must be verified against a real upgraded account *before* building the push path (§10 step 0). If confirmed broken: promote a **VEVENT+VALARM fallback** (a "May" calendar whose events carry alerts) from v2 to v1 for iCloud, and keep VTODO push for non-iCloud CalDAV servers — the engine is component-agnostic either way. Related: does iCloud accept `MKCALENDAR` with a VTODO component set? Probe before promising "create a May list".
2. **Remote VTODO deletion semantics** — v1 tombstones (keeps the May reminder, stops syncing, shows an "unlinked" count). Alternative: treat deletion-in-Reminders as completion. Tombstone is the safe default but leaves a silently unsynced reminder; needs a call.
3. **Foreign VTODOs** — should tasks created directly in the chosen Reminders list import into May (v2)? If yes, what do they attach to — an "Inbox" pseudo-context?
4. **Shared-circle semantics** — v1 pushes only rows where `user_id == account.user_id`, so a spouse's connected account won't carry tasks on a shared Person owned by the other user. Acceptable, or should shared-visibility items push to every connected account (risking N copies)?
5. **Digest hour and event-import window** — digest uses server-local time like the rest of the app (`date.today()` throughout); event pull windows at −90 days, unbounded future. Confirm both, or is this the moment to add `users.timezone`?
6. **Scheduler duplication** — the per-worker scheduler thread is a pre-existing wart the lease lock papers over. Worth a separate fix (env-gated single scheduler worker), and/or a `CALDAV_SYNC_ENABLED` env opt-out for operators who prefer external cron?
7. **Key custody** — keyfile beside the DB protects DB-only leaks, not full-volume compromise. Is documenting that sufficient, or should the panel actively recommend the `MAY_CREDENTIAL_KEY` env override?