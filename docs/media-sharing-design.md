# Media Library & Sharing — Final Design

Target: May at `/Volumes/1TB_DAVINCI/may/move/may` (Flask + SQLAlchemy + Jinja2/Tailwind + HTMX, Flask-Migrate, single container on :5050, SQLite by default with Postgres/MySQL/MariaDB supported via `DATABASE_URL`).

## Executive summary

Media enters May two ways: **in-app uploads** (May owns the bytes, stored uuid-sharded under `/app/data/media/uploads/`) and a **single read-only library folder** bind-mounted at `/library` that May scans and indexes but never writes to. Media is "given to people" three ways: direct attachment to a `Person` (visible to anyone who can see that person, with per-person captions and ordering), user-owned **collections/albums** assignable to one or more people, and **tokenized share links** (`/s/<token>`) that let outsiders view/download without an account. The permission model is derivative, never ambient: an item is visible beyond its owner only through a person link, a collection assigned to a visible person, an instance-shared collection, or the instance-wide library. Share tokens are 256-bit, stored only as SHA-256 hashes, revocable instantly, and every failure mode is a uniform 404. One dialect-safe migration (random alembic id — fork requirement), one authenticated blueprint (`media`), one public blueprint (`media_public`), and a scanner that piggybacks on the existing hourly background thread. No new dependencies: Pillow is already pinned (`pillow>=12.3.0`, requirements.txt line 9).

## 0. Verified codebase grounding

Every load-bearing claim below was checked against the repo:

- Migration head is `7c3e9a1d5b42` (`add_people_and_person_tasks`); nothing revises it. That file defines the inspector-guard helpers to copy: `_create_index_if_missing`, `_drop_index_if_present`, `_has_constraint`. Its docstring confirms `db.create_all()` runs in `create_app` before `flask db upgrade`, so every migration op must be guarded.
- `app/__init__.py` also runs `_run_schema_migrations` (SQLite-only, model-driven `ADD COLUMN` recovery, line 238) — new columns on existing tables may already exist by the time the migration runs; guards are mandatory, not optional.
- Blueprints register at `app/__init__.py:470–489` (`people.bp` last). The hourly background thread is `_start_reminder_scheduler` (line 566): 60 s startup delay, then independent `try` blocks per processor, `time.sleep(3600)`.
- Global `after_request` (line 497) already sends `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin` on **every** response — file endpoints inherit these for free; we add only what's missing (CSP sandbox on file bytes, noindex/no-store on share pages).
- `docker-entrypoint.sh` runs under `set -e` and conditionally `chown -R may:may /app/data` (lines 31–33). A read-only bind mount nested under `/app/data` would abort startup when that chown fires — hence the library mounts at **`/library`**, outside the chown path.
- `config.py`: `UPLOAD_FOLDER` defaults to `data/uploads` (env-overridable), `MAX_CONTENT_LENGTH = 300MB` (line 110). Multi-DB URL support (lines 30–79) means **no partial/filtered indexes** anywhere in this design.
- `app/routes/people.py` permission idiom: read = `person in current_user.get_all_people()` (owned + `is_shared`); write = `person.owner_id == current_user.id or current_user.is_admin` (lines 263, 310, 333…). The media model mirrors this exactly, including admin write-anywhere.
- `app/routes/documents.py`: extension allowlist, `doc_<uuid>_<name>` flat naming, `send_from_directory` — the pattern we improve on (no original filenames on disk, sharded dirs).
- `app/routes/api.py`: `/api/export/csv` (line 2180) zips CSVs only; `/api/export/backup` → `export_full_backup` (line 2803) zips `data.json`, `manifest.json`, and files from `UPLOAD_FOLDER` enumerated in `files_to_backup` (line 2833). Media uploads must be added there or backups silently omit them.
- `AppSettings` is a KV table with `get`/`set`/`get_all_branding` (`app/models.py:1172`) — used for scan telemetry and the library visibility toggle instead of new tables.
- HTMX is bundled (`config.py:14–15`, injected in the context processor) — usable for scan spinners and grid actions.

## 1. Trust boundaries and threat model

| Principal | Authenticates via | May touch |
|---|---|---|
| **Media owner** (any user) | session login | Full CRUD on their uploads, their collections, their share links |
| **Co-user who can see a shared Person / shared collection / the library** | session login | *Read-only* view/download of that media (mirrors how a shared Person's tasks are visible today) |
| **Admin** | session + `is_admin` | Library scan controls, visibility toggle, edit/delete/share anything, revoke any link — matching people.py's admin-write-anywhere idiom |
| **Anonymous token holder** | possession of an unguessable URL | Exactly the items inside one live share; nothing else — no other routes, no ids, no user info |

Designed-against threats:

1. **Token guessing/enumeration** → 256-bit random tokens; per-IP rate limit on lookups; uniform 404.
2. **DB exfiltration leaking live links** → only `sha256(token)` at rest; a dumped `may.db` cannot reconstruct share URLs.
3. **Path traversal** → files are never addressed by client-supplied paths; every response resolves a DB-stored `rel_path` against a fixed root with a `realpath` containment check.
4. **Stored XSS via uploads** (SVG/HTML inline on the app origin) → strict inline-MIME allowlist; everything else forced to `Content-Disposition: attachment`; `Content-Security-Policy: sandbox` on all file bytes (`nosniff` already global).
5. **Co-user exfiltration by token-wrapping** → share minting requires ownership (or admin); collections may only contain items you own plus library items, so a collection share can never expose another user's private upload.
6. **Library abuse** → the library root is fixed by env var at deploy time (`MEDIA_LIBRARY_FOLDER`), never registered through a web form — no arbitrary-server-path attack surface, no risk of someone indexing `/app/data` (and the SQLite DB) from the UI. Strictly read-only.
7. **Zombie access after revocation** → every `/s` request re-validates the share row; no stateless signed URLs. Revocability beats cacheability at family scale.
8. **Symlink escape in the library** → the scanner realpath-resolves every file and skips anything outside the library root.

## 2. Permission model

Stated once, enforced by two model helpers used in every route:

```python
class MediaItem(db.Model):
    def viewable_by(self, user):
        if not user.is_authenticated:
            return False
        if self.owner_id == user.id:
            return True
        if self.origin == 'library' and (
            user.is_admin or AppSettings.get('media_library_visibility', 'all_users') == 'all_users'
        ):
            return True
        person_ids = {p.id for p in user.get_all_people()}
        if any(l.person_id in person_ids for l in self.person_links):
            return True
        for ci in self.collection_items:
            coll = ci.collection
            if coll.is_shared:
                return True
            if any(cp.person_id in person_ids for cp in coll.person_links):
                return True
        return False

    def editable_by(self, user):
        """Metadata edit, delete, share-link minting. Matches people.py's write idiom."""
        if not user.is_authenticated:
            return False
        if user.is_admin:
            return True
        return self.owner_id == user.id   # library items (owner_id NULL) → admin only
```

Rules:

- **Owner** = uploader. Library items have no owner (`owner_id NULL`); admin manages them.
- **Visibility is derivative, never ambient.** Read access flows only from: the library toggle, a person link, a collection assigned to a visible person, or `MediaCollection.is_shared` (the existing `Vehicle.is_shared`/`Person.is_shared` idiom, extended to albums).
- **Read ≠ write ≠ re-share.** Seeing an item never grants edit, delete, or share-minting.
- **Collections may only contain items the user owns, plus library items.** This single rule is what makes collection shares safe: wrapping someone else's private upload in your collection is structurally impossible.
- **Attach to person** requires: item `viewable_by` you AND person in `current_user.get_all_people()`. Detach allowed for the link's `added_by`, the person's owner, the item's `editable_by` set. Attaching to an `is_shared` person shows an explicit warning: "everyone on this instance who can see Alice will see this file."
- **Share minting**: item share → `editable_by` (owner/admin). Collection share → collection owner or admin. Revoke → creator or admin.
- **Admins** follow the app's existing idiom: write powers everywhere (edit/delete/share/revoke), but the grid does not ambiently list other users' private uploads — same as people.py, where admins can edit any person but listings show only `get_all_people()`.

## 3. Data model

All tables prefixed `media_`. Dialect-safe: plain (non-partial) constraints only, `BigInteger` for file sizes, named FKs where downgrade must drop them. Models in `app/models.py`, existing style.

### `media_items`
| column | type | notes |
|---|---|---|
| id | Integer PK | internal only |
| uuid | String(32) NOT NULL UNIQUE ix | `uuid4().hex` — the **only** id in public URLs |
| owner_id | Integer FK users.id NULL, ix | NULL ⇔ `origin='library'` |
| origin | String(10) NOT NULL default `'upload'` | `upload` \| `library` |
| rel_path | String(1024) NOT NULL | upload: relative to `MEDIA_ROOT/uploads`; library: relative to `MEDIA_LIBRARY_FOLDER` |
| original_filename | String(255) NOT NULL | shown to humans; used for `download_name` only |
| mime_type | String(100) | derived from extension allowlist server-side, never client-supplied, never sniffed |
| kind | String(10) NOT NULL | `image` \| `video` \| `document` \| `other` (derived, drives grid filters) |
| sha256 | String(64) NOT NULL, ix | dedup + moved-file detection + thumbnail cache key |
| size_bytes | BigInteger NOT NULL default 0 | videos exceed 2 GB |
| file_mtime | DateTime | fs mtime at last hash (change detection) |
| status | String(10) NOT NULL default `'active'` | `active` \| `missing` |
| title / description | String(200) / Text | user metadata; title defaults to filename stem |
| created_at / updated_at / last_seen_at | DateTime | `last_seen_at` = last scan that saw this path |

Constraints: `UNIQUE(origin, rel_path)` (plain — upload rel_paths are uuid-based so always unique; library paths indexed once); index on `sha256`; index on `(owner_id, kind)`; named CHECKs `ck_media_origin` and `ck_media_upload_has_owner` (`origin='library' OR owner_id IS NOT NULL`). Upload dedup (`owner_id+sha256`) is enforced by lookup-before-insert in the upload handler and surfaced as an informational "already in your library" hint — never a DB constraint, never auto-merged.

### `media_person_links` — "give media to a person"
Association **object**, not a bare table, because it carries UX state: `id` PK, `media_item_id` FK ix, `person_id` FK ix, `added_by` FK users.id, `caption` String(300), `sort_order` Integer default 0, `created_at`. `UNIQUE(media_item_id, person_id)`. Per-person captions and ordering make each person's media strip independently arrangeable — "organize how the user wants" at the person-page level, independent of any collection.

### `media_collections`
`id`, `owner_id` FK NOT NULL ix, `name` String(120) NOT NULL, `description` Text, `cover_media_item_id` FK media_items.id NULL, `sort_mode` String(20) NOT NULL default `'manual'` (`manual`|`name`|`newest`|`oldest`), `is_shared` Boolean NOT NULL default false (instance-wide read visibility, mirroring `Vehicle.is_shared`), `created_at`, `updated_at`.

### `media_collection_items`
`id` PK, `collection_id` FK ix, `media_item_id` FK ix, `sort_order` Integer default 0, `added_at`. `UNIQUE(collection_id, media_item_id)`.

### `media_collection_people` — assign an album to people
`id` PK, `collection_id` FK ix, `person_id` FK ix, `added_by` FK, `created_at`. `UNIQUE(collection_id, person_id)`. Assignment is live: the album card on the person page grows as the collection grows.

### `media_shares`
| column | type | notes |
|---|---|---|
| id | Integer PK | |
| created_by | Integer FK users.id NOT NULL ix | minted by owner/admin only |
| media_item_id | Integer FK NULL | exactly one target set |
| collection_id | Integer FK NULL | |
| person_id | Integer FK NULL | **dormant in v1** — schema ships now so person-scoped shares need no v2 migration |
| token_hash | String(64) NOT NULL UNIQUE ix | sha256 of the URL token |
| token_prefix | String(10) NOT NULL | display only, in the shares list |
| label | String(120) | "for grandma" |
| expires_at | DateTime NULL | NULL = never |
| max_downloads | Integer NULL | cap; one input in the create form |
| download_count / access_count | Integer NOT NULL default 0 | |
| password_hash | String(256) NULL | **dormant in v1**, unlocked in v2 |
| last_accessed_at / revoked_at / created_at | DateTime | |

Named CHECK `ck_share_one_target`: `(media_item_id IS NOT NULL) + (collection_id IS NOT NULL) + (person_id IS NOT NULL) = 1` — also enforced in app code (SQLite/MySQL<8.0.16 tolerance).

### `media_share_events` — **dormant in v1**, shipped in the same migration
`id`, `share_id` FK ix, `event` String(10) (`view`|`download`|`denied`), `media_item_id` NULL, `ip` String(45), `user_agent` String(255), `created_at`. Powers the v2 owner-facing activity view. Shipping dormant columns/tables now minimizes future migrations — migrations are this fork's riskiest artifact.

### `users` (altered)
`show_menu_media` Boolean default true — same pattern as `show_menu_people` (`app/models.py:98`).

### `AppSettings` keys (no schema change)
| key | values | default | purpose |
|---|---|---|---|
| `media_library_visibility` | `all_users` \| `admin` | `all_users` | who sees library items in the grid |
| `media_library_folder_state` | `ok` \| `absent` \| `unreadable` | set by scanner | admin page banner |
| `media_last_scan_at` / `media_last_scan_stats` | ISO ts / JSON | — | scan telemetry |

## 4. Storage layout on disk

```
/app/data/                                # existing volume — chown-managed by entrypoint
├── may.db
├── uploads/                              # legacy vehicle documents & person images — untouched
└── media/
    ├── uploads/<uuid[:2]>/<uuid>.<ext>   # in-app uploads: uuid-named, sharded (256 dirs),
    │                                     # no user-controlled names on disk — original_filename
    │                                     # lives only in DB + Content-Disposition
    └── derived/<sha[:2]>/<sha256>_t320.webp   # lazy thumbnail cache, keyed by CONTENT hash:
        <sha[:2]>/<sha256>_t1280.webp          # uploads and library share one pipeline, and
                                               # moved/renamed library files keep their thumbs.
                                               # Pure cache — safe to rm -rf entirely.

/library/                                 # the indexed folder — single read-only bind mount
└── <whatever structure the operator likes — May never writes here>
```

Decisions:

- **The library mounts at `/library`, never under `/app/data`.** `docker-entrypoint.sh` runs a conditional `chown -R may:may /app/data` under `set -e`; a nested `:ro` mount would make that chown fail and abort container startup. `/library` sits outside the chown path. When the directory is absent, the feature quietly degrades (admin page shows "no library configured"; nothing else changes).
- Storage is **uuid-sharded, not content-addressed**. Identical bytes uploaded twice produce two files and two rows with a "possible duplicate" hint — no blob refcounting, no GC, no cross-user shared-file deletion logic. Deliberate simplicity for family scale; the sha256 column still gives dedup *visibility* and a v2 duplicate-review tool.
- **Library files are read-only to May, invariantly.** Deleting a library `media_item` removes the index row (+ links + shares), never the file. Deleting an upload removes file, derived thumbs, links, and shares.
- Every file response resolves `full = os.path.realpath(os.path.join(root, item.rel_path))` and requires `os.path.commonpath([full, os.path.realpath(root)]) == os.path.realpath(root)` and existence, else 404. `root` is `MEDIA_ROOT/uploads` or `MEDIA_LIBRARY_FOLDER` — never request data.

Config (`config.py`, mirroring `UPLOAD_FOLDER`):

```python
MEDIA_ROOT = os.environ.get('MEDIA_ROOT') or str(basedir / 'data' / 'media')
MEDIA_LIBRARY_FOLDER = os.environ.get('MEDIA_LIBRARY_FOLDER', '/library')
MEDIA_LIBRARY_SCAN_MINUTES = int(os.environ.get('MEDIA_LIBRARY_SCAN_MINUTES', '360'))  # 0 = manual only
```

`docker-compose.yml` gains a commented example next to the existing volume (matching the DB-profile comment style):

```yaml
    volumes:
      - may_data:/app/data
      # Optional: index an existing media folder (read-only; May never modifies it)
      # - /path/on/host/media:/library:ro
```

`docker-entrypoint.sh`: add `mkdir -p /app/data/media/uploads /app/data/media/derived` beside the existing `mkdir -p /app/data/uploads` (line 30). No other entrypoint change.

**Large video note**: `MAX_CONTENT_LENGTH` is 300 MB (config.py:110). It stays as-is; the library mount is the intended route for big video, and the upload page says so. Route around the limit, don't raise it.

## 5. Library indexing strategy

Implemented as `app/services/media_scanner.py` (sibling of `reminder_processor.py`): `scan_library(commit_batch=200) -> stats`, run inside an app context.

**When it runs**
1. **Manually** — "Scan now" on `/media/library` (admin, POST); synchronous with an HTMX spinner; politely refuses if a scan is already running (process-local `threading.Lock`).
2. **Periodically** — a third `try` block in the existing hourly loop in `_start_reminder_scheduler` (`app/__init__.py:566`), gated on `MEDIA_LIBRARY_SCAN_MINUTES > 0` and elapsed interval per `media_last_scan_at`. No new thread, no APScheduler.
3. **Never on request paths**, and not at container start (bind mounts may be slow network storage; the hourly pass covers it).

**Algorithm (incremental; steady state is a stat-walk, no hashing)**

```
walk MEDIA_LIBRARY_FOLDER with os.scandir, recursively:
  skip hidden (.-prefixed) files/dirs, zero-byte files, non-allowlisted extensions,
  files with mtime < 30s ago (probably still copying),
  anything whose realpath escapes the library root (symlink out of tree)

  row = MediaItem lookup (origin='library', rel_path)
  if row exists:
      unchanged (size, mtime)  -> touch last_seen_at            # stat only
      changed                  -> rehash; update sha/size/mtime; touch
  else:
      sha = stream-hash (1 MiB chunks)
      candidate = library row with same sha whose OWN path is gone from disk
                  (covers both status='missing' rows from prior scans AND
                   moves that happened between scans — checked against the
                   filesystem, not just the status column)
      if candidate: rebind rel_path (keep row id) -> person links, collections,
                    share links, and sha-keyed thumbnails all survive the move
      else:         insert new row (kind/mime/title derived from filename)

after full walk:
  rows with last_seen_at < scan_start -> status='missing'       # soft, never auto-delete
commit every 200 files; record telemetry in AppSettings
```

- The move check tests "old path gone **on disk**", not "row already marked missing" — this detects a move within a single scan pass (the failure mode a status-only lookup has).
- **Missing files** stay `missing` indefinitely: greyed badge in the grid, attachments/collections/shares preserved (an unmounted disk must never cascade-destroy curation; `/s` renders a generic "file unavailable" placeholder for missing members of a live share). A restored file resurrects the row via the sha match. Hard delete is an explicit admin "purge missing" action.
- **Dedup is informational**: identical bytes at two library paths are two rows (both files the operator chose to keep), badged as duplicates via the `sha256` index.
- Extension allowlist = documents.py's set + `heic, avif, mp4, mov, mkv, webm, m4v` (+ `svg`, indexed as `document`, never served inline). Scan errors (e.g. permission) land in `media_last_scan_stats` and the admin page.

## 6. Share-link token design

**Generation**

```python
token = secrets.token_urlsafe(32)                                # 256 bits, ~43 chars
share.token_hash   = hashlib.sha256(token.encode()).hexdigest()  # stored, unique-indexed
share.token_prefix = token[:10]                                  # display only
# full URL shown exactly once, in the creation response, with a copy button
```

URL: `https://may.example.com/s/<token>`. The token never appears in the DB or logs (routes log the prefix). The app's global `Referrer-Policy: strict-origin-when-cross-origin` already prevents the token path leaking cross-origin; all in-page assets use the same `/s/<token>/...` prefix so no cross-origin subresources exist anyway.

*Usability tradeoff, made explicit*: hashing at rest means the owner cannot re-copy a live link later — the shares list shows only prefix + label. Accepted because minting a fresh link is one click and revoking the old one is another; a dumped SQLite file that cannot reconstruct live URLs is worth that friction. (May stores `password_reset_token` and `api_key` plaintext today; public, login-free links warrant the stronger treatment.)

**Validation — single code path `_resolve_share(token)`, every `/s` request**
1. Per-IP fixed-window rate limit on token lookups (e.g. 30/min → 429), process-local dict (single-container app). The key uses the first `X-Forwarded-For` hop when present (the documented deployment is behind Caddy), else `remote_addr`. This is defense-in-depth against log-noise/DoS — the 2^256 keyspace is the real defense, and the miss path is one indexed lookup.
2. `MediaShare.query.filter_by(token_hash=sha256(token))` → miss = **404**.
3. `revoked_at` set, `expires_at` past, or `max_downloads` exhausted → **the same 404 page**. Invalid, expired, and revoked are indistinguishable to a prober; no metadata leaks about whether a token ever existed.
4. Sub-routes verify the requested item **uuid is a member of the share at request time** (item share → the one item; collection share → current membership — shares are live views, stated in the UI). Un-linking media instantly removes it from live shares.
5. Bump `last_accessed_at`/`access_count`; `download_count` only on the download route; counter writes are best-effort and never block the response.

**Lifecycle**: expiry presets at creation (1 / 7 / 30 days / never); optional `max_downloads`; revoke via `POST /media/shares/<id>/revoke` (creator or admin) sets `revoked_at`, row retained for audit; deleting the underlying item/collection cascades revocation. v2 adds password unlock (`POST /s/<token>/unlock`, werkzeug hash, session flag, normal CSRF protection — the public blueprint is **not** CSRF-exempt).

**Response headers** (on top of the global `after_request` set):
- File bytes (`/s/...` **and** authenticated `/media/.../file`): `Content-Security-Policy: sandbox`. Inline rendering only for `image/jpeg, image/png, image/gif, image/webp, video/mp4, video/webm, application/pdf`; everything else — explicitly including `image/svg+xml` and all `text/*` — is `Content-Disposition: attachment`. MIME comes from the DB (extension-derived), never sniffed. Video uses `send_file(..., conditional=True)` for range requests.
- `/s` HTML pages: `X-Robots-Tag: noindex, nofollow`, `Cache-Control: private, no-store`; files may use `private, max-age=3600`.

## 7. Routes / blueprint surface

### Blueprint `media` — `app/routes/media.py`, `url_prefix='/media'`, all `@login_required`

| Route | Methods | Purpose |
|---|---|---|
| `/media/` | GET | Grid. Filters: `?kind=`, `?origin=`, `?person=`, `?collection=`, `?q=` (title/filename), `?status=missing`, `?unorganized=1` (no person links, no collections — the triage view for fresh library indexes). Sort: newest / name / size. |
| `/media/upload` | GET, POST | Multi-file upload; optional immediate person/collection assignment (prefilled from `?person_id=`/`?collection_id=`); sha dedup hint links the existing item instead of erroring. |
| `/media/<int:media_id>` | GET | Detail: preview, metadata, people panel (captions), collections panel, shares panel. |
| `/media/<int:media_id>/file` | GET | Authenticated bytes, inline if MIME-safe, `conditional=True`. |
| `/media/<int:media_id>/thumb` | GET | Lazy thumbnail (`?s=320\|1280`), Pillow, sha-keyed cache; static per-kind SVG placeholder for video/docs in v1. |
| `/media/<int:media_id>/download` | GET | Always attachment. |
| `/media/<int:media_id>/edit` | POST | title/description (`editable_by`). |
| `/media/<int:media_id>/delete` | POST | `editable_by`; upload → file + thumbs + rows; library → index rows only. |
| `/media/<int:media_id>/people` | POST | Attach person(s) with optional captions (item viewable + person in `get_all_people()`). |
| `/media/<int:media_id>/people/<int:person_id>/remove` | POST | Detach (per §2). |
| `/media/collections` | GET, POST | Album cards (cover, count, assigned people, shared badge) / create. |
| `/media/collections/<int:collection_id>` | GET | Album grid; drag-reorder when `sort_mode='manual'` (progressive enhancement over POSTed positions). |
| `/media/collections/<int:collection_id>/edit` | POST | name, description, cover, sort_mode, `is_shared` (owner/admin). |
| `/media/collections/<int:collection_id>/delete` | POST | Deletes collection + memberships + its shares; never the items. |
| `/media/collections/<int:collection_id>/items` | POST | `action=add\|remove\|reorder`; added items must be owned by the user or `origin='library'` (the anti-exfiltration rule). |
| `/media/collections/<int:collection_id>/people` | POST | Assign/unassign people. |
| `/media/shares` | GET | My links: prefix, label, target, expiry, counts, revoke. Admin sees an "all shares" tab. |
| `/media/<int:media_id>/shares/new` | POST | Mint item share (`editable_by`) — full URL displayed once. |
| `/media/collections/<int:collection_id>/shares/new` | POST | Mint collection share (owner/admin). |
| `/media/shares/<int:share_id>/revoke` | POST | Creator or admin. |
| `/media/library` | GET | Admin: folder state, last scan stats, missing list, visibility toggle. |
| `/media/library/scan` | POST | Admin: run scan now. |
| `/media/library/purge-missing` | POST | Admin: hard-delete `missing` rows after confirmation. |

### People integration — extend `app/routes/people.py`

`view()` (renders `people/view.html`, line 245) additionally loads person media links (ordered by `sort_order`) and assigned collections; the template gains a **Media** section. New endpoints, following the existing person-scoped nesting: `POST /people/<int:person_id>/media/attach` (picker modal for existing items, or upload-and-attach in one step), `POST /people/<int:person_id>/media/<int:link_id>/detach`, `POST /people/<int:person_id>/media/reorder`, `POST /people/<int:person_id>/media/<int:link_id>/caption`.

### Blueprint `media_public` — `app/routes/media_public.py`, `url_prefix='/s'`, no `login_required`, **not** CSRF-exempt

| Route | Methods | Purpose |
|---|---|---|
| `/s/<token>` | GET | Landing: single-item preview or collection gallery; branding via `AppSettings.get_all_branding()`; standalone template, no app nav, no user data. |
| `/s/<token>/thumb/<uuid>` | GET | Thumbnail, membership-checked. |
| `/s/<token>/file/<uuid>` | GET | Inline preview, MIME-safe only, membership-checked. |
| `/s/<token>/download/<uuid>` | GET | Attachment; bumps `download_count`. |
| `/s/<token>/download-all` | GET | v2: streamed zip. |
| `/s/<token>/unlock` | POST | v2: password unlock. |

Both blueprints register in `create_app` after `people.bp` (`app/__init__.py:489`).

## 8. Templates / page inventory & organization UX

```
app/templates/media/
  index.html            # grid + filter bar (kind pills, person/collection selects, search,
                        #   unorganized toggle); duplicate/missing badges
  upload.html           # drop-zone + multi-file list; person/collection multi-selects
  view.html             # preview + metadata form + 3 panels (people w/ captions, collections, shares)
  collections.html      # album cards
  collection_view.html  # grid + reorder + assign-people + share actions
  collection_form.html
  shares.html           # my links (+ admin tab)
  library_admin.html    # scan status/controls, visibility toggle (admin)
  _grid.html            # shared thumbnail-grid partial (index, album, person section)
  _picker_modal.html    # reusable "pick existing media" modal (person page, album page)
  _person_media.html    # included by people/view.html
app/templates/share/
  base_public.html      # minimal branded shell: AppSettings branding, no nav, noindex meta
  landing.html          # item or gallery rendering; "file unavailable" placeholder for missing
  not_found.html        # the single uniform 404 for invalid/expired/revoked
base.html               # + "Media" nav entry gated on current_user.show_menu_media
auth/settings.html      # + menu-visibility checkbox (existing show_menu_* pattern)
```

"Organize how the user wants," concretely: the grid is the hub — multi-select → *Add to collection*, *Attach to person*, *Share*. Collections are ordered albums with `sort_mode` presets (manual/name/newest/oldest) and drag-reorder in manual mode. Person pages carry an independently ordered, captioned media strip plus assigned album cards. Filters compose (`?person=3&kind=image`). The `unorganized` filter drives triage of newly indexed library files. v2 adds free-form tags for cross-cutting labels.

## 9. Migration plan

**One migration file**, following the fork's conventions exactly:

- **Random revision id** (fork rule — upstream hand-rolls sequential ids; a collision already happened once). Generate at authoring time, e.g. `python -c "import uuid; print(uuid.uuid4().hex[:12])"`. `down_revision = '7c3e9a1d5b42'` (verified current head).
- **Inspector-guarded everything**: `db.create_all()` runs in `create_app` before `flask db upgrade`, and `_run_schema_migrations` may have already added columns on SQLite — copy `_index_names` / `_create_index_if_missing` / `_drop_index_if_present` / `_has_constraint` verbatim from `7c3e9a1d5b42_add_people_and_person_tasks.py` and guard every `create_table`, index, and column add.
- Create order: `media_items` → `media_person_links` → `media_collections` → `media_collection_items` → `media_collection_people` → `media_shares` → `media_share_events`; downgrade reverses with guards.
- `users.show_menu_media` via `batch_alter_table` with `server_default=sa.true()` (SQLite-safe).
- **Dialect-safe by construction**: no partial indexes anywhere (the app supports Postgres/MySQL/MariaDB); named FKs and CHECKs so downgrade can drop them; CHECK constraints also mirrored in app code.
- Dormant v2 schema (`media_shares.password_hash`, `media_shares.person_id`, `media_share_events`) ships in this same migration — one schema change, not three.
- Migrations run automatically on container start via the entrypoint's `flask db upgrade`; no operator action.

App-code steps landing together on `dev`: models in `app/models.py`; blueprints registered in `create_app`; `MEDIA_ROOT` / `MEDIA_LIBRARY_FOLDER` / `MEDIA_LIBRARY_SCAN_MINUTES` in `config.py`; `mkdir -p` in `docker-entrypoint.sh`; compose comment for the `:ro` mount; scanner service + scheduler hook.

## 10. Backup/export integration

`export_full_backup` (`app/routes/api.py:2803`) currently zips `data.json` + `manifest.json` + files from `UPLOAD_FOLDER` enumerated in `files_to_backup` (line 2833: vehicle images, attachments, documents, person images). Extend it: add media tables to `data.json`, and add **upload-origin** media files to the zip under a `media/` prefix with manifest entries (path resolution via `MEDIA_ROOT`, since they don't live in `UPLOAD_FOLDER`). Library files are deliberately excluded — potentially huge, and the operator already owns the source directory; the index rows in `data.json` (with sha256) are enough to re-link after restore. `/api/export/csv` gains `media_items.csv` / `media_collections.csv` rows in the same style as `people.csv`.

## 11. Phased rollout

### v1 — `0.28.0` on `dev` (minimal but sharing-complete)
- Full schema in one migration (including dormant v2 columns/tables).
- Multi-file upload; sharded uuid storage; sha256 with duplicate hint.
- Library indexing: `/library` convention, manual + hourly incremental scan, single-pass move detection, soft `missing`, symlink containment, scan telemetry in AppSettings.
- Person links with captions + ordering; Media section on the person page with the shared-person warning.
- Collections: CRUD, sort modes, drag-reorder, assign to people, `is_shared`.
- Share links: item + collection; hashed tokens shown once; expiry presets; download cap; revoke; counts; uniform-404 public landing/preview/download with the header/MIME hardening; per-IP invalid-token rate limit.
- Lazy image thumbnails (Pillow, already pinned); per-kind SVG placeholders for video/docs.
- Nav entry + `show_menu_media`; shares management page; admin library page.
- Backup endpoint extension.

### v2 — follow-up releases
- Password-protected shares (`/s/<token>/unlock`) + per-share activity view (`media_share_events`).
- Person-scoped share links (column already present) — public page renders media only, never contact fields (template contract stated now so v2 doesn't improvise).
- Streamed zip `download-all` for collection/person shares.
- Tags (`media_tags`/`media_item_tags`) + saved filters.
- EXIF capture date + orientation; "sort by taken date"; HEIC decode via optional `pillow-heif`.
- Video poster frames via optional ffmpeg (feature-detect; out of v1 to keep the image slim).
- Duplicate-review tool (group by sha256); quick-hash optimization for very large libraries if telemetry shows hashing pain.
- REST endpoints under the existing `api.bp` key-auth pattern; "promote vehicle Document to media library" action.
- Optional AppSettings toggle letting non-admin users mint shares for library items.

### Explicit non-goals
- No anonymous *upload* into shares (receiving files is a different threat model).
- No writing into the library folder, ever.
- No stateless signed URLs — revocability beats cacheability at self-hosted family scale.
- No web-form registration of arbitrary server paths as library roots.

## 12. v1 scope cut — what to build first, in one session

Build in this order; each step leaves the app shippable:

1. **Migration + models + config + entrypoint mkdir** (`media_items`, `media_person_links`, `media_collections`, `media_collection_items`, `media_collection_people`, `media_shares`, `media_share_events`, `users.show_menu_media`) — full schema so no second migration is ever needed for this feature.
2. **Upload + grid + detail + authenticated file/thumb/download** with the containment check, MIME allowlist, and CSP-sandbox headers.
3. **Person attachment** (links with captions) + the Media section on `people/view.html`.
4. **Item share links** end-to-end: mint (hashed, shown once), `/s/<token>` landing, preview/download, revoke, uniform 404, rate limit. *This completes the headline "give files to people outside the app" story.*
5. **Collections** (CRUD, membership rule, assign-to-people) + collection shares.
6. **Library scanner** (manual scan button first; the hourly hook is three lines once `scan_library()` works) + admin page.

If the session runs short, cut from the bottom: the library scanner is the most separable chunk (uploads + sharing work without it); collections can trail person-attachment. Do **not** cut the security hardening in steps 2 and 4 — it is the point of the design.

## 13. Open questions for the owner

1. **Library visibility default** — proposal defaults `media_library_visibility` to `all_users` (household assumption). Should a fresh instance default to `admin`-only instead?
2. **Who may share library items?** v1 says admin-only (they're unowned). Is that acceptable for your household, or should any user who can see the library be able to mint links for library items (v2 toggle)?
3. **Share links that never expire** — allowed in v1 ("never" preset). Prefer a forced maximum (e.g. 90 days) on a self-hosted instance exposed to the internet?
4. **Backup size** — media uploads go into the full backup zip; a video-heavy library of *uploads* could make backups very large. Cap or flag uploads over a size threshold in the backup, or accept as-is?
5. **Person images** (`people.image_filename`) stay a separate mechanism in v1. Worth migrating person avatars onto media items in v2, or leave them alone?
6. **HEIC**: iPhone photos index fine but won't thumbnail without `pillow-heif`. Add the dependency in v1, or ship placeholder thumbs and defer?
7. **Retention of revoked shares** — rows are kept for audit with a manual "purge revoked" action. Want automatic purging after N days instead?