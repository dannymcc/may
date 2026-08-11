# Customizable Welcome Screen ("Launchpad") — Final Design

**Repo:** `/Volumes/1TB_DAVINCI/may/move/may` · **Branch:** `dev` · **Migration head:** `85b42a298ff2` · **v1 requires zero migrations**

## Executive summary

May gets an admin-configurable, touch-first launcher page at `/welcome`: a responsive grid of big tappable panels (nav tiles, quick-action buttons, stat tiles, log tails, static key-value lists, external links, a clock), defined by one validated JSON document edited in a new admin settings section. The config lives in three `AppSettings` rows (enabled flag, config, last-known-good backup) — no new table, no migration. Users opt in via the existing per-user Start Page mechanism (`User.start_page = 'welcome'`, a `String(50)` that needs no schema change); `/` and login are untouched, and a broken config can never reach them. Reactive panels (`stat`, `log_tail`) poll via HTMX — already vendored and CSRF-wired but currently unused by any template — through a fragment endpoint whose URL deliberately contains `/api/` so the service worker's cache-everything-except-`/api/` policy skips it. The sharp security edge is the log panel: config may only name a bare filename (regex-validated, extension-allowlisted) resolved inside a single anchored directory (`data/logs/`, inside the existing Docker bind mount), symlink-checked with `resolve()` + `is_relative_to()`, read in bounded windows, rendered autoescaped, and forced admin-only. One honest finding the owner must see: **May writes no log files today** (verified — no `FileHandler` anywhere; gunicorn logs to stdout), so the log panel starts empty unless we add an opt-in rotating file handler or the owner mounts external logs.

---

## 1. Verified codebase facts this design builds on

Every row was re-verified by reading the current `dev` checkout.

| Fact | Where |
|---|---|
| `/` redirects authed users through a `page_routes` dict keyed by `User.start_page` (14 entries, `dashboard`…`allowance`; **no `people` entry today**); anonymous → login | `app/routes/main.py:11-34` |
| The same dict is duplicated in `get_start_page_url()`, used for post-login redirect | `app/routes/auth.py:130-151`, called at `auth.py:23,37` |
| `User.start_page` is `db.String(50)`, free-form, default `'dashboard'` — new values need no migration | `app/models.py:84` |
| Login supports Remember-me: `login_user(user, remember=remember)` — kiosk sessions survive reboots | `app/routes/auth.py:28,33` |
| `AppSettings` KV store: `key String(50)` unique, `value Text`, `get`/`set`/`get_all_branding` statics; already holds branding, SMTP, DVLA, Tessie, `registration_enabled` | `app/models.py:1224-1269` |
| Admin settings POSTs are separate routes on the auth blueprint (**`url_prefix='/auth'`**, `auth.py:17`) with `@admin_required` | `auth.py:375-482`; decorator `app/security.py:199` |
| `validate_webhook_url` (SSRF guard) already exists — reusable if remote feeds ever land | `app/security.py:116` |
| Settings page: hash-nav sections (`showSection`, nav items lines 14-80), `section-menu` at :405 with the Start Page `<select>` at :417-427, saved by `auth.menu_preferences` (`auth.py:349-353`); admin sections gated `{% if current_user.is_admin %}` (:69, :1048, :1363) | `app/templates/auth/settings.html` |
| HTMX vendored with CDN fallback (`base.html:137-150`); CSRF token auto-injected into every HTMX request via `htmx:configRequest` (`base.html:561`); **no template uses any `hx-` attribute today** (grep) | `base.html`, `app/static/vendor/htmx.min.js` |
| Tailwind is the vendored **Play-CDN runtime JIT** (`TAILWIND_ASSET_URL` injected by `inject_globals`, `app/__init__.py:371-386`; `darkMode:'class'` config at `base.html:127`) — classes are compiled client-side from the live DOM | `base.html:127`, `__init__.py:383-384` |
| Dark mode: `dark` class on `<html>` from `User.dark_mode` (`models.py:59`) + `may-theme` localStorage sync; critical dark CSS inlined | `base.html:2,10-29,169-181` |
| Branding primary color: `--primary-*` CSS vars set via JS (`base.html:109`) with utility classes at `base.html:183-196` |
| PWA: manifest linked at `base.html:47`, `start_url: "/"` (`app/static/manifest.json:5`), SW served from root scope | `app/routes/main.py:43-49` |
| **SW caches every GET except URLs containing `/api/`** — network-first, `cache.put` on success, cache fallback offline | `app/static/sw.js:51-80` |
| CSRF is global (`csrf.init_app`, `__init__.py:357`); only `api.bp` is exempted (`:362`) | `app/__init__.py` |
| Dashboard query shapes to reuse: all-time totals (`main.py:66-89`), cost-per-distance (`main.py:111-116`), cheapest-station latest-price subquery (`main.py:133-145`), **month-window sums in `get_monthly_spending`** (`main.py:186-196`) | `app/routes/main.py` |
| `Reminder.due_date` + `is_overdue`/`is_due_soon` (`models.py:1048,1074-1082`); `PersonTask.status`/`due_date` (`models.py:946-977`); `User.get_all_vehicles()` (`models.py:117`) | `app/models.py` |
| `fuel.quick` — the existing touch-optimized quick-entry form | `app/routes/fuel.py:370` |
| **No file logging anywhere** — no `FileHandler`/`basicConfig`/`addHandler` in `app/`, `config.py`, `run.py`, or `docker-entrypoint.sh`; data dir pattern: `UPLOAD_FOLDER = env or basedir/'data'/'uploads'` | `config.py:109` |
| Fork migration rule is real: upstream hand-rolls sequential-looking ids and `migrations/versions/` contains the near-collision pair `a1b2c3d4e5f6`/`a1b2c3d4e5f7`; fork migrations use random ids (`7c3e9a1d5b42`, `85b42a298ff2`, `f768be7719bd`) | `migrations/versions/` |
| No `jsonschema` dependency; repo convention is hand-rolled validators | `requirements.txt`, `app/security.py` |

---

## 2. What the two screens look like

### Wall tablet (landscape ~1024×600, PWA standalone, kiosk)

```
┌────────────────────────────────────────────────────────────────┐
│  09:41  Tue 11 Aug                                  May ▪ Home │  ← clock panel
├──────────────┬──────────────┬──────────────┬───────────────────┤
│  ⛽ LOG FUEL │  💸 EXPENSE  │  🔌 CHARGE   │  🧾 THIS MONTH    │
│  (quick)     │  (add)       │  (add)       │   £412.60         │
├──────────────┼──────────────┼──────────────┼───────────────────┤
│  🔔 DUE      │  🚗 VEHICLES │  🏠 HA DASH  │  📜 may.log       │
│   3 items    │              │  (external)  │  [20 lines,       │
│              │              │              │   admin only]     │
└──────────────┴──────────────┴──────────────┴───────────────────┘
```

No scrolling in kiosk fill mode (`grid-auto-rows: 1fr`, `100dvh` minus header); nav bar hidden — the screen *is* the nav.

### Phone (portrait, same config, reflowed)

Two columns, vertical scroll allowed, config order = visual order (put the most-tapped tiles first). Same JSON — only column count and fit mode differ by breakpoint.

### Touch ergonomics (applied in the tile partials)

| Concern | Rule |
|---|---|
| Hit target | Whole tile is one `<a>`/`<button>`; min `min-h-24` (96px) at `h:1` — well above 44pt/48dp floors; `gap-3` prevents fat-finger overlap |
| Tap latency | `touch-action: manipulation` (kills double-tap-zoom delay); `-webkit-tap-highlight-color: transparent` |
| Feedback | `active:scale-[0.97] transition-transform` + active shade — no hover dependence |
| Type scale | Label `text-lg font-semibold`; stat value `text-4xl font-bold tabular-nums` (readable from 2m) |
| Safe areas | `black-translucent` status bar is already set (`base.html:45`) → welcome template pads with `env(safe-area-inset-*)` in standalone |
| Dark mode | Inherits `html.dark` wholesale; tiles use the existing `bg-white dark:bg-gray-800` card vocabulary; `theme:"dark"` config forces the class on this page only (wall units want forced dark: glare, burn-in) |
| Branding | Tiles use the existing `--primary-*` vars (`base.html:109,183-196`) — admin brand color flows in automatically |
| A11y | Real links/buttons, `focus-visible:ring-2`; stat tiles `aria-live="polite"` so HTMX swaps announce |

**Tailwind note (resolved against the code):** because Tailwind here is the runtime Play-CDN JIT with a MutationObserver, server-rendered dynamic classes compile at runtime — but grid column counts are still emitted as inline `style="grid-template-columns:repeat(N,minmax(0,1fr))"` and colors as a server-side map of complete literal class strings. This is robust if the project ever moves to a compiled Tailwind build, and it is also the security posture: config values never become class-string fragments.

---

## 3. Where the config lives: three `AppSettings` rows, not a new table

| Key (all ≤ 28 chars, fits `String(50)`) | Value |
|---|---|
| `welcome_screen_enabled` | `'true'`/`'false'`, default `'false'` (same convention as `registration_enabled`) |
| `welcome_screen_config` | the JSON document as text, ≤ 64 KB enforced |
| `welcome_screen_config_backup` | last-known-good JSON, rotated automatically on every successful save; one-click restore |

Justification over a `welcome_panels` table:

1. **Zero migrations.** This fork merges upstream regularly (`c59a434` merged v0.27.1) and has lived through a revision-id near-collision (`a1b2c3d4e5f6`/`a1b2c3d4e5f7` both exist in `migrations/versions/`). Shipping a feature with zero schema drift is a feature.
2. **Atomicity.** The document is validated as a whole; a single-row save is atomic in SQLite. Row-per-panel needs ordering columns, partial-validity states, and multi-row transactions for no v1 benefit.
3. **Precedent.** Branding, SMTP, DVLA, Tessie, and registration all live in `AppSettings` and are edited by the identical admin pattern (`auth.py:375-482`).
4. **Failure isolation.** A corrupt blob can only break the welcome renderer, which is built to survive it (§8).

Accepted tradeoffs: no per-panel querying, one-deep history, last-write-wins (fine for a self-hosted admin). **v2 escape hatch** when the visual editor lands: table `welcome_panels` (`id` PK, `slug VARCHAR(32) UNIQUE`, `panel_type VARCHAR(20)`, `title VARCHAR(60)`, `config_json TEXT`, `position INT`, `size_w`/`size_h SMALLINT`, `visibility VARCHAR(10)`, `enabled BOOL`, `updated_at`). Its migration id **must** be `uuid.uuid4().hex[:12]` with `down_revision` = the then-current head (today `85b42a298ff2`) — the fork rule is binding.

---

## 4. Config JSON schema (v1)

```json
{
  "version": 1,
  "title": "Garage",
  "theme": "auto",
  "grid": { "columns_phone": 2, "columns_tablet": 3, "columns_wall": 4,
            "fit": "scroll", "kiosk_reload_hour": 4 },
  "panels": [
    {"id": "log-fuel", "type": "quick_action", "action": "log_fuel", "title": "Log fuel", "icon": "fuel", "color": "primary", "size": {"w": 1, "h": 1}},
    {"id": "month",    "type": "stat", "metric": "total_cost_month", "title": "This month", "color": "green", "size": {"w": 2, "h": 1}, "refresh_seconds": 60},
    {"id": "due",      "type": "stat", "metric": "reminders_due", "title": "Due", "color": "red", "size": {"w": 1, "h": 1}, "refresh_seconds": 120},
    {"id": "vehicles", "type": "nav", "target": "vehicles", "title": "Vehicles", "icon": "car", "size": {"w": 1, "h": 1}},
    {"id": "house",    "type": "static_list", "title": "House", "items": [{"label": "Bin day", "value": "Tuesday"}], "size": {"w": 1, "h": 1}},
    {"id": "ha",       "type": "external_link", "url": "http://homeassistant.local:8123", "title": "Home Assistant", "icon": "home", "size": {"w": 1, "h": 1}},
    {"id": "applog",   "type": "log_tail", "file": "may.log", "lines": 20, "refresh_seconds": 30, "size": {"w": 2, "h": 2}},
    {"id": "clock",    "type": "clock", "show_date": true, "size": {"w": 4, "h": 1}}
  ]
}
```

**Top level:** `version` required, must be `1` (unknown version → hard reject on save, fallback on render). `title` ≤ 60 chars, escaped. `theme` enum `auto`/`dark`/`light`. `grid.columns_*` clamped 1-6 (defaults 2/3/4); `fit` enum `scroll`/`fill` (kiosk forces `fill` unless overridden); `kiosk_reload_hour` 0-23 or `null` (nightly `location.reload()` in kiosk mode — picks up config changes, flushes memory on cheap tablets). `panels` required, 1-30 items. Raw text ≤ 64 KB.

**Common panel fields:**

| Field | Rule |
|---|---|
| `id` | required, `^[a-z0-9_-]{1,32}$`, unique — it becomes a URL segment (§6) |
| `type` | required, one of the registry below |
| `title` | ≤ 60 chars, rendered under Jinja autoescape |
| `icon` | name from a bundled inline-SVG set (~15 names: `fuel, car, receipt, bolt, bell, wrench, note, home, map, person, …`) or a single emoji grapheme. Never raw SVG/HTML |
| `color` | enum `primary, green, amber, red, purple, gray` → server-side map to complete literal Tailwind class strings (light+dark pairs). Never raw CSS/hex — no style injection; `primary` rides the branding vars |
| `size` | `{w: 1-4, h: 1-2}`, clamped; `w` further clamped to the breakpoint's column count at render |
| `visibility` | `"all"` (default) / `"admin"`; **forced to `admin` for `log_tail`**; enforced server-side per render AND per poll |
| `enabled` | default `true` |
| `refresh_seconds` | only on dynamic types; clamped (§7) |

**Panel type registry (v1) — every data source verified:**

| Type | Extra fields | Backing code |
|---|---|---|
| `nav` | `target`: key of the consolidated `PAGE_ROUTES` registry (§5) — never a raw URL (kills `javascript:`/open-redirect by construction) | `url_for()` on the mapped endpoint |
| `quick_action` | `action`: `log_fuel` → `fuel.quick` (`fuel.py:370`), `add_expense`, `add_charge`, `add_trip`, `add_note`, `add_reminder` → the existing `…/new` routes; optional `vehicle_id` (int, must be in `current_user.get_all_vehicles()`, silently dropped if not) | deep links into existing create forms; `fuel/quick.html` is already touch-optimized |
| `stat` | `metric` from registry; optional `vehicle_id` (same ownership check) | `vehicle_count` (`get_all_vehicles`); `fuel_cost_month`/`expense_cost_month`/`total_cost_month` (month-window sums per `get_monthly_spending`, `main.py:186-196`); `cost_per_distance` (`main.py:111-116`); `reminders_due` (`Reminder.due_date`/`is_completed`, `models.py:1048,1074-1082`); `tasks_due` (`PersonTask.status != 'done'` + `due_date`, `models.py:946-977`); `cheapest_station` (latest-price subquery, `main.py:133-145`); `last_fuel` (recent-log query shape, `main.py:83-85`) |
| `log_tail` | `file` (bare filename, §7); `lines` 5-200 (default 20) | bounded tail of an allowlisted file under `LOGS_DIR` |
| `static_list` | `items`: ≤ 12 of `{label ≤ 40, value ≤ 120}` | none — this **is** the owner's "JSON data filled out via admin settings", rendered escaped |
| `external_link` | `url`: parsed with `urllib.parse`, scheme must be `http`/`https`, ≤ 500 chars; rendered `target="_blank" rel="noopener noreferrer"` with the hostname shown on the tile | none |
| `clock` | `show_date` bool | client-side JS, no server data |

**Explicitly rejected for v1:** a raw-HTML panel (config-driven stored XSS), server-fetched remote JSON feeds (SSRF — if ever wanted, gate through the existing `validate_webhook_url`, `app/security.py:116`), and per-user layouts. A file-based JSON panel (`json_file` rendering `LOGS_DIR/<name>.json` as key-values) is v1.5 — it shares the §7 machinery and is deferred only for session scope.

**Validation strategy:** hand-rolled declarative validator in `app/services/welcome.py` — no `jsonschema` dependency, matching repo convention, and error strings can flow through flask-babel. `validate_welcome_config(raw_text) -> (config | None, errors: list[str])` collects **all** errors with JSON-path locations (`panels[3].target: unknown value 'garage'`), not first-error-only — admins fix a textarea in one pass. **On save: hard reject** (nothing stored). **On render: degrade** (§8). Unknown keys are ignored with a save-time warning (forward compatibility).

---

## 5. Single route registry (kills an existing duplication)

`main.py:16-31` and `auth.py:133-148` carry two identical copies of the start-page map. Move it to `app/services/welcome.py` as `PAGE_ROUTES` and import it in both places (no circular import: the service imports models only, never routes). `nav` targets, `quick_action` actions, and the start-page feature all validate against this one dict. Adding `'welcome': 'welcome.index'` — and optionally the currently missing `'people': 'people.index'` — becomes a one-line change.

*Merge-friction note:* consolidating touches two upstream-owned files, but the dict changes rarely upstream and the alternative (a third hand-synced copy in the validator) is how the duplication happened in the first place. Consolidate.

---

## 6. Routes and serving

New blueprint `app/routes/welcome.py`, registered in the blueprint block (`app/__init__.py:471-489`).

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/welcome` | GET | `@login_required` | Full screen from `get_welcome_config()`. If `welcome_screen_enabled != 'true'` → redirect to `main.dashboard`. `?kiosk=1` hides chrome, forces `fit: fill`, arms the nightly reload |
| `/welcome/api/panel/<panel_id>` | GET | **manual auth check** | HTMX fragment for one reactive panel. Re-loads config server-side, finds the panel by id, re-checks `visibility` — the id is the only client input; query params ignored. 404 if unknown/disabled/non-reactive/not visible |
| `/auth/welcome-settings` | POST | `@login_required @admin_required` | Save: validate → reject-or-store → rotate backup. Lives in `auth.py` next to `smtp_settings` (:375) matching the existing pattern (auth blueprint prefix is `/auth` — verified `auth.py:17`) |
| `/auth/welcome-settings/restore` | POST | admin | Swap `welcome_screen_config_backup` into place (re-validated anyway) |
| `/auth/welcome-settings/validate` | POST | admin | `{ok, errors[]}` JSON for the settings page's Validate button (plain `fetch`; CSRF is global, token from the meta tag) |

**Why `/welcome/api/panel/…` and not `/welcome/panel/…` (resolved against `sw.js`):** the service worker caches **every** GET whose URL does not contain `/api/` (`sw.js:57-59`), and `cache.put` ignores `Cache-Control`. Putting `/api/` in the fragment path makes the SW skip it entirely — polls are never SW-cached, and offline a failed HTMX request simply leaves the last-rendered tile in place (exactly the right kiosk behavior: the full page is SW-cached, fragments are not). Additionally set `Cache-Control: no-store` on fragment responses for the browser HTTP cache. Note `csrf.exempt(api.bp)` (`__init__.py:362`) exempts only the api *blueprint*, not this path — irrelevant anyway for GET.

**Fragment auth (from Proposal 1, kept):** `@login_required` would 302-redirect an expired session to the login page, which HTMX would swap *into a tile*. Instead the fragment route checks manually: `if not current_user.is_authenticated: return '', 401, {'HX-Redirect': url_for('auth.login')}` — HTMX navigates the whole page to login.

**Reach — per-user opt-in, no takeover of `/`:** add `'welcome': 'welcome.index'` to `PAGE_ROUTES` and a "Welcome Screen" `<option>` to the Start Page select (`settings.html:417-427`, saved untouched by `menu_preferences`, `auth.py:349-353`). `start_page` is a free `String(50)` — config data only, no migration. Login flow and `/` for everyone else are untouched.

**Kiosk recipe (documented in the settings section):** create a dedicated non-admin user (e.g. `wallpanel`), set its Start Page to Welcome, log in on the tablet with **Remember me** (verified: `login_user(user, remember=remember)`, `auth.py:28,33` — session survives reboots), Add to Home Screen. The PWA `start_url` is `/` (`manifest.json:5`), which redirects through `start_page` → the panel screen launches standalone-fullscreen. Chrome hiding: wrap the `<nav>` (`base.html:256`) in `{% block navbar %}…{% endblock %}` — a two-line, upstream-merge-safe diff — and `welcome/index.html` overrides it empty when `kiosk=1`. **No anonymous/tokenized access in v1** (open question 3).

**Nav entry:** when enabled, show a "Home" link in the nav for all users, read via a `WELCOME_ENABLED` value added to the existing `inject_globals` context processor (`__init__.py:371-386`). Deliberately **no** `show_menu_welcome` User column — the per-user menu toggles are all columns (`models.py:86-98`) and adding one forces a migration for a nicety; v2.

---

## 7. Reactive updates: HTMX polling, per panel

HTMX is already loaded (local + CDN fallback, `base.html:137-150`) and CSRF-wired (`base.html:561`), but no template uses an `hx-` attribute today (grep-verified) — this feature is the first real consumer; nothing to install.

```html
<div id="panel-{{ p.id }}"
     hx-get="{{ url_for('welcome.panel', panel_id=p.id) }}"
     hx-trigger="load, every {{ p.interval }}s [document.visibilityState === 'visible']"
     hx-swap="outerHTML">…</div>
```

- **Clamps (server-side at render, never trusted from config):** `stat` 15-3600 s, default 60; `log_tail` 10-3600 s, default 30. `nav`/`quick_action`/`static_list`/`external_link`/`clock` never poll.
- **Stagger:** rendered interval gets ±10 % deterministic jitter (hash of panel id) so a 12-panel wall screen doesn't fire 12 simultaneous SQLite reads on the minute. Queries are the same cheap read-only aggregates the dashboard already runs per page load — no writer contention.
- **Visibility filter** in the trigger stops background phone tabs from polling.
- Same auth trust level as the dashboard; no extra rate limiting in v1 (noted as v2 hardening).

---

## 8. Security — the log panel is the sharp edge

Threat model: the config is admin-written, but "admin typed it" is not a defense — a compromised admin session, a config pasted from a forum, a tampered DB row, or a future visual-editor bug must never become arbitrary-file-read or stored XSS. All rules enforced in `app/services/welcome.py`:

1. **Config never names a path.** `log_tail.file` must match `^[a-z0-9_-]{1,32}\.(log|txt|jsonl)$` — no path separators, no leading dot, no NUL, extension allowlisted. Traversal is unrepresentable *by construction* before any filesystem code runs.
2. **Single anchored root.** `config.py` gains `LOGS_DIR = os.environ.get('LOGS_DIR') or str(basedir / 'data' / 'logs')`, mirroring the `UPLOAD_FOLDER` pattern (`config.py:109`). In Docker that is `/app/data/logs`, inside the one bind mount users already manage; created at startup alongside the existing `os.makedirs(UPLOAD_FOLDER)` (`__init__.py:352`). Nothing outside it is ever readable. No subdirectories in v1.
3. **Symlink-proof resolution:** `resolved = (Path(LOGS_DIR) / name).resolve()`, then require `resolved.is_relative_to(Path(LOGS_DIR).resolve())` (Python 3.12) and `resolved.is_file()`. `resolve()` follows symlinks, so a malicious `may.log → /etc/shadow` symlink dropped into the dir fails containment — defense-in-depth on top of rule 1.
4. **Bounded reads.** Seek to at most 256 KB from EOF, read once, decode `errors='replace'`, `splitlines()[-lines:]` (≤ 200). Never read a whole file, never follow it; polling re-reads the window.
5. **Escaped rendering only.** Output inside `<pre>` under Jinja autoescape; `|safe` is banned in welcome templates — log content is hostile input (it may contain user-supplied strings).
6. **`log_tail` is admin-only, enforced twice.** The validator rewrites `visibility` to `admin` for this type regardless of config (logs leak usernames, tokens, IPs); both the full render and the fragment endpoint re-check `current_user.is_admin` on every request — the poll endpoint never trusts page-render filtering.
7. **No free-text file entry in the UI.** The settings section lists filenames currently present in `LOGS_DIR` (re-validated against the regex before display) — admins pick from what exists.
8. **The request contributes nothing but a panel id.** Filename, line count, and refresh all come from the validated stored config.
9. **No injection surface elsewhere:** routes/actions/metrics/colors/icons are enum lookups; URLs are scheme-checked; every string is autoescaped; there is no raw-HTML panel type.

**Honest finding the owner must see:** May writes **no log files today** (verified — no logging handler setup anywhere; gunicorn logs to container stdout). v1 `log_tail` panels display files *other processes* drop into `data/logs/` (cron jobs, other containers' mounted logs, backup scripts). Optional ~20-line add-on: an opt-in `RotatingFileHandler` (env `MAY_FILE_LOG=1`, 1 MB × 3, `data/logs/may.log`) so the panel has a first-party source on day one. Open question 1.

---

## 9. Failure modes — bad config can never break login or the dashboard

- **Isolation by construction:** `auth.login`, `main.index`, and `main.dashboard` never read the config; the only readers are the welcome blueprint and the admin settings section. Unknown `start_page` values already fall through to `main.dashboard` (`main.py:32`, `auth.py:149`).
- **Loader is total:** `get_welcome_config()` returns `(config, errors)`; missing key, parse failure, or validation failure yields a built-in `DEFAULT_CONFIG` (nav tiles: dashboard, log fuel, vehicles, expenses, reminders, settings + clock) — it never raises. `/welcome` always renders; admins see a dismissable banner listing the errors with a link to the editor; non-admins see the default tiles. A kiosk showing defaults beats a kiosk showing a stack trace.
- **Per-panel containment:** each tile render is wrapped in `try/except`; a crashing panel logs via `current_app.logger.exception` and becomes a gray "panel error: `<id>`" tile for admins, silently omitted for others. One bad metric can't blank the wall screen.
- **Save-time gate:** invalid JSON is rejected wholesale with per-path errors and the unsaved text re-rendered; the stored document is only ever one that passed full validation. Render-side validation still guards against hand-edited DB rows and version drift.
- **Rollback:** every successful save rotates the previous good doc into `welcome_screen_config_backup`; one-click restore in settings.
- **Feature off:** `welcome_screen_enabled != 'true'` → `/welcome` redirects to the dashboard, and `start_page='welcome'` users fall through via the registry default. Nothing dangles.

---

## 10. Admin editing UX (v1: validated JSON textarea, honestly)

New admin-gated **"Welcome Screen"** section in `auth/settings.html`, following the exact existing pattern: sidebar `settings-nav-item` + `showSection('welcome', event)` (pattern at :14-80), a `section-welcome` div gated `{% if current_user.is_admin %}` (like branding). Contents:

1. **Enable toggle** → `welcome_screen_enabled` (same toggle markup as `registration_enabled`, :299-308).
2. **JSON editor:** `<textarea rows="22" class="font-mono">`; **Validate** button (fetch → `/auth/welcome-settings/validate`, errors listed with paths under the textarea); **Load example** (inserts the §4 sample client-side); **Save**; **Open welcome screen ↗** preview link; **Restore previous version** when a backup exists.
3. **Reference helper (read-only):** available `nav` targets, `quick_action` names, `stat` metrics, icon/color names, and detected log files in `LOGS_DIR`.
4. **Kiosk recipe** (§6) as help text.

The per-user side is one `<option value="welcome">` in the existing Start Page select (:417-427) — the `menu_preferences` handler needs no change.

Visual drag-and-drop editing is explicitly **v2**; the schema (stable ids, ordered list, enum-driven fields) is designed so a visual editor emits the same document.

---

## 11. Migrations

**v1: none.** Storage is three rows in the existing `app_settings` table; per-user opt-in reuses the existing `start_page` string column. Given this fork's collision history with upstream's hand-rolled sequential ids, zero schema drift is itself a feature. If v2 adds `welcome_panels` (§3), the revision id **must** be `uuid.uuid4().hex[:12]` with `down_revision` = the then-current head.

---

## 12. File-level implementation plan

| File | Change |
|---|---|
| `app/services/welcome.py` | **new** — `PAGE_ROUTES` (consolidated), `QUICK_ACTIONS`, `METRICS` (each a `callable(user, vehicle_id) -> {value, unit, caption}` reusing the §4-verified query shapes), `ICONS`, `COLORS`; `validate_welcome_config`, `get_welcome_config`, `DEFAULT_CONFIG`; `list_log_files`, `tail_log` with §8 containment |
| `app/routes/welcome.py` | **new** — blueprint; `index()` (login_required; visibility filtering, clamped+jittered intervals, kiosk flag), `panel(panel_id)` at `/welcome/api/panel/<id>` (manual auth + `HX-Redirect` on 401, `Cache-Control: no-store`) |
| `app/templates/welcome/index.html` | **new** — extends base; overrides `navbar` block when kiosk; grid with inline `grid-template-columns`, safe-area padding, fill mode, nightly reload timer, admin error banner |
| `app/templates/welcome/panels/` | **new** — `_nav.html`, `_quick_action.html`, `_stat.html`, `_log_tail.html`, `_static_list.html`, `_external_link.html`, `_clock.html`, `_error.html`; `_stat`/`_log_tail` carry the `hx-*` attributes so the same partial serves full render and poll swap |
| `app/routes/main.py` | delete inline dict (:16-31), import `PAGE_ROUTES` |
| `app/routes/auth.py` | same import in `get_start_page_url`; add `welcome_settings`, `welcome_settings_restore`, `welcome_settings_validate` POSTs next to `smtp_settings` (:375); pass welcome context into `settings()` render (:301) |
| `app/templates/auth/settings.html` | admin sidebar item + `section-welcome`; `<option value="welcome">` in the Start Page select (:417-427) |
| `app/templates/base.html` | wrap `<nav>` (:256) in `{% block navbar %}`; conditional "Home" nav link |
| `app/__init__.py` | register `welcome.bp` (:471-489); `WELCOME_ENABLED` in `inject_globals` (:371-386); `os.makedirs(LOGS_DIR)` next to the existing upload-dir creation (:352) |
| `config.py` | `LOGS_DIR` (env-overridable, default `basedir / 'data' / 'logs'`) |

---

## 13. v1 scope cut — buildable in one session

Build order: `services/welcome.py` (validator + registries + 6-8 metrics + log tail + defaults) → welcome blueprint (2 routes) → templates (index + 8 partials) → settings section (toggle, textarea, validate, example, restore, log-file list, kiosk recipe) → `PAGE_ROUTES` consolidation → start-page option → navbar block + `?kiosk=1` + nightly reload → manual test at phone width and a 1024×600 window, light and dark.

**In v1:** all seven panel types (`log_tail` admin-forced; `static_list` covers the owner's "JSON data via admin settings" ask), HTMX polling with clamps/jitter/visibility filter/`HX-Redirect`, `/api/`-path SW bypass, config backup + restore, default-config fallback + admin banner, `LOGS_DIR` containment reader, kiosk chrome-hiding + fill mode.

**v1.5:** `json_file` panel (key-value render of `LOGS_DIR/<name>.json`, ≤ 256 KB, same allowlist/escaping); optional opt-in `RotatingFileHandler`.

**v2:** visual editor emitting the same schema; `welcome_panels` table (random-id migration); tokenized no-login kiosk access; remote JSON/URL feeds (SSRF-gated via `validate_webhook_url`); Home Assistant entity tiles (`app/routes/homeassistant.py` already exists); per-device profiles (the KV design extends to `welcome_screen_config:<slug>` keys without a migration); `show_menu_welcome` column; fragment rate limiting.

## 14. Open questions for the owner

1. **Log sources:** May writes no log files today (verified — stdout only). Is `data/logs/` purely for externally dropped/mounted logs, or should v1.5 add the opt-in `MAY_FILE_LOG=1` rotating `may.log` so the panel works out of the box?
2. **Log visibility:** v1 hard-forces `log_tail` to admin-only. Must a shared household wall screen ever show logs to non-admins? (One-line policy change, but a real information-disclosure decision.)
3. **Kiosk auth:** is a dedicated logged-in kiosk user with a Remember-me session acceptable, or do you need a no-login signed-URL mode? (Real security surface — v2 with its own review.)
4. **"JSON data" meaning:** does `static_list` (key-values typed into the admin config) cover your intent, or do you need file-based JSON (`v1.5 json_file`) or remote URLs (v2, SSRF-gated) first?
5. **Reach:** per-user opt-in via Start Page, or force the welcome screen as `/` for everyone on this install (e.g. an `AppSettings` default-start-page key for new users)?
6. **Editor bar:** is the validated JSON textarea acceptable for v1, with the visual editor as v2?
7. **Metric wishlist:** v1 ships vehicle count, month costs, cost-per-distance, reminders/tasks due, cheapest station, last fuel — anything you'd tap daily that's missing (specific vehicle odometer, next MOT date via the existing DVLA fields)?