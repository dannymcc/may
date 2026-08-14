"""Radicale storage plugin backed by May's database.

Radicale loads this via ``[storage] type = app.caldav.storage``, which is why
the classes are named ``Storage`` and ``Collection`` -- ``radicale.utils.
load_plugin`` looks up those exact names.

Path layout::

    /                        root
    /<username>/             principal
    /<username>/reminders/   VTODO,  projected from May Reminder rows
    /<username>/events/      VEVENT, projected from May CalendarEvent rows
    /<username>/<other>/     opaque, stores client .ics verbatim

Two things worth understanding before changing anything here:

**DTSTAMP is derived from the row's ``updated_at``, never from "now".**
An ETag must not change unless the resource changed. If DTSTAMP were
regenerated on each read, every poll would produce a new ETag and every client
would re-download the entire collection every 15 minutes.

**Reconciliation is a read-time projection.** May rows are the source of
truth for mapped collections; ``CalDavObject`` is an index over them. On read
we walk the May rows, re-project, and only write back (bumping the sync
counter) when the serialized form actually differs.
"""

import contextlib
import logging
from datetime import datetime, timezone
from email.utils import formatdate
from hashlib import sha256

import vobject
from radicale import item as radicale_item
from radicale import pathutils
from radicale.storage import (BaseCollection, BaseStorage,
                              ComponentExistsError, ComponentNotFoundError)

from app import db
from app.caldav import mapping, sidecar as sidecar_mod
from app.caldav.enrichment import apply_to_sidecar, run_pipeline
from app.caldav.models import CalDavCollection, CalDavObject, CalDavSidecar, CalDavVersion
from app.caldav.runtime import (app_context, create_collection_result,
                                get_app, get_request_agent, storage_lock,
                                upload_result)

logger = logging.getLogger(__name__)

SYNC_PREFIX = 'http://radicale.org/ns/sync/'

DEFAULT_COLLECTIONS = (
    {
        'name': 'reminders',
        'backing_kind': 'reminder',
        'component': 'VTODO',
        'displayname': 'May Reminders',
        'description': 'Vehicle and person reminders from May',
        'color': '#0284c7ff',
    },
    {
        'name': 'events',
        'backing_kind': 'calendar_event',
        'component': 'VEVENT',
        'displayname': 'May Calendar',
        'description': 'Service, MOT, tax and custom events from May',
        'color': '#0ea5e9ff',
    },
)


def _props_for(spec):
    return {
        'tag': 'VCALENDAR',
        'D:displayname': spec['displayname'],
        'C:calendar-description': spec['description'],
        'C:supported-calendar-component-set': spec['component'],
        'ICAL:calendar-color': spec['color'],
    }


def _http_date(value):
    value = value or datetime.utcnow()
    return formatdate(value.replace(tzinfo=None).timestamp(), usegmt=True)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

class Collection(BaseCollection):
    """A root, principal, or calendar collection."""

    def __init__(self, storage, path, row=None, kind='calendar', user=None):
        self._storage = storage
        self._path = path
        self._row = row
        self._kind = kind          # root | principal | calendar
        self._user = user
        self._reconciled = False

    # -- identity ---------------------------------------------------------
    @property
    def path(self):
        return self._path

    @property
    def row(self):
        return self._row

    @property
    def last_modified(self):
        if self._row is not None:
            return _http_date(self._row.updated_at)
        return _http_date(datetime.utcnow())

    @property
    def etag(self):
        """Cheap CTag. Changes iff something in the collection changed."""
        if self._row is None:
            return '"%s"' % sha256(self._path.encode('utf-8')).hexdigest()[:32]
        self._reconcile()
        return '"%d-%d"' % (self._row.id, self._row.sync_seq or 0)

    # -- metadata ---------------------------------------------------------
    def get_meta(self, key=None):
        props = dict(self._row.props or {}) if self._row is not None else {}
        if key is None:
            return props
        return props.get(key)

    def set_meta(self, props):
        if self._row is None:
            raise ValueError('Cannot set properties on %r' % self._path)
        merged = dict(self._row.props or {})
        for key, value in (props or {}).items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        self._row.props = merged
        self._row.bump()
        db.session.commit()

    # -- sync -------------------------------------------------------------
    def sync(self, old_token=''):
        """RFC 6578 sync-collection over a monotonic per-collection counter."""
        if self._row is None:
            return SYNC_PREFIX + '0', iter(())

        self._reconcile()
        current = self._row.sync_seq or 0
        token = SYNC_PREFIX + str(current)

        if not old_token:
            hrefs = [o.href for o in self._live_objects()]
            return token, iter(hrefs)

        if not old_token.startswith(SYNC_PREFIX):
            raise ValueError('Unsupported sync token: %r' % old_token)
        try:
            old_seq = int(old_token[len(SYNC_PREFIX):])
        except ValueError:
            raise ValueError('Malformed sync token: %r' % old_token)
        if old_seq > current:
            raise ValueError('Sync token from the future: %r' % old_token)

        changed = (CalDavObject.query
                   .filter(CalDavObject.collection_id == self._row.id,
                           CalDavObject.changed_seq > old_seq)
                   .all())
        return token, iter([o.href for o in changed])

    # -- reads ------------------------------------------------------------
    def get_all(self):
        if self._row is None:
            return
        self._reconcile()
        for obj in self._live_objects():
            item = self._item_for(obj)
            if item is not None:
                yield item

    def get_multi(self, hrefs):
        hrefs = list(hrefs)
        if self._row is None:
            for href in hrefs:
                yield href, None
            return
        self._reconcile()
        by_href = {o.href: o for o in CalDavObject.query.filter(
            CalDavObject.collection_id == self._row.id,
            CalDavObject.href.in_(hrefs)).all()} if hrefs else {}
        for href in hrefs:
            obj = by_href.get(href)
            yield href, (self._item_for(obj) if obj is not None and not obj.is_deleted else None)

    def has_uid(self, uid):
        if self._row is None:
            return False
        self._reconcile()
        return db.session.query(
            CalDavObject.query.filter(
                CalDavObject.collection_id == self._row.id,
                CalDavObject.uid == uid,
                CalDavObject.deleted_at.is_(None)).exists()).scalar()

    # -- writes -----------------------------------------------------------
    def upload(self, href, item):
        """Create or replace a resource. Returns ``(new_item, old_item)``."""
        if self._row is None:
            raise ValueError('Cannot upload into %r' % self._path)
        if not pathutils.is_safe_path_component(href):
            raise ValueError('Unsafe href: %r' % href)

        component = mapping.primary_component(item.vobject_item)
        if component is None:
            raise ValueError('No VEVENT/VTODO/VJOURNAL in uploaded item')

        obj = self._object_by_href(href)
        old_item = self._item_for(obj) if obj is not None and not obj.is_deleted else None

        uid = radicale_item.get_uid_from_object(item.vobject_item) or mapping._text(component, 'uid')
        if not uid:
            raise ValueError('Uploaded component has no UID')

        user_id = self._owner_user_id()
        backing_kind = self._row.backing_kind
        backing_id = obj.backing_id if obj is not None else None

        # 1. Apply the standard fields onto the May row we own.
        if backing_kind in ('reminder', 'calendar_event'):
            backing_row = self._apply_to_backing(component, backing_kind, backing_id, user_id)
            db.session.flush()
            backing_id = backing_row.id
        else:
            backing_row = None

        # 2. Sidecar: client-supplied values win and get locked.
        card = CalDavSidecar.get_or_create(user_id, uid)
        values, present = sidecar_mod.extract_from_component(component)
        sidecar_mod.apply_client_values(card, values, present)

        due = mapping._val(component, 'due') or mapping._val(component, 'dtstart')
        completed = (mapping._text(component, 'status') or '').upper() == 'COMPLETED'
        sidecar_mod.record_touch(card, due_at=due, completed=completed)

        # 3. Enrichment, skipped when the text an enricher reads is unchanged.
        ctx = mapping.context_from_component(component, uid, user_id,
                                             raw_ics=item.serialize(), sidecar=card)
        digest = sidecar_mod.context_digest(ctx.summary, ctx.description,
                                            ctx.location, ','.join(ctx.categories))
        if digest != card.enriched_digest:
            derived = run_pipeline(ctx, allow_llm=self._storage.allow_llm)
            apply_to_sidecar(card, derived, digest=digest)
            mapping.resolve_dependencies(card, self._find_uid_by_summary)

        db.session.flush()

        # 4. Re-project, so what we store is byte-identical to what the next
        #    GET will serve. Otherwise the client's cached ETag goes stale
        #    immediately and every write triggers a redundant re-read.
        text, etag = self._render(backing_kind, backing_row, component,
                                  item.vobject_item, card)

        seq = self._row.bump()
        if obj is None:
            obj = CalDavObject(collection_id=self._row.id, href=href)
            db.session.add(obj)
            operation = 'create'
        else:
            operation = 'update' if not obj.is_deleted else 'create'

        obj.uid = uid
        obj.component = component.name
        obj.backing_kind = backing_kind
        obj.backing_id = backing_id
        obj.raw_ics = text
        obj.etag = etag
        obj.deleted_at = None
        obj.changed_seq = seq
        obj.updated_at = datetime.utcnow()
        db.session.flush()

        self._append_version(obj, operation, text, etag)
        db.session.commit()

        return upload_result(self._item_for(obj), old_item)

    def delete(self, href=None):
        if self._row is None:
            raise ValueError('Cannot delete %r' % self._path)

        if href is None:
            db.session.delete(self._row)
            db.session.commit()
            return

        obj = self._object_by_href(href)
        if obj is None or obj.is_deleted:
            raise ComponentNotFoundError(href)

        if obj.backing_kind in ('reminder', 'calendar_event'):
            backing_row = self._backing_row(obj.backing_kind, obj.backing_id)
            if backing_row is not None:
                db.session.delete(backing_row)

        seq = self._row.bump()
        obj.deleted_at = datetime.utcnow()
        obj.changed_seq = seq
        obj.raw_ics = None
        obj.etag = None
        self._append_version(obj, 'delete', None, None)
        db.session.commit()

    # -- internals --------------------------------------------------------
    def _owner_user_id(self):
        return self._row.user_id if self._row is not None else None

    def _live_objects(self):
        return (CalDavObject.query
                .filter(CalDavObject.collection_id == self._row.id,
                        CalDavObject.deleted_at.is_(None))
                .order_by(CalDavObject.href)
                .all())

    def _object_by_href(self, href):
        return CalDavObject.query.filter_by(
            collection_id=self._row.id, href=href).first()

    def _item_for(self, obj):
        if obj is None or obj.is_deleted or not obj.raw_ics:
            return None
        return radicale_item.Item(
            collection=self,
            href=obj.href,
            text=obj.raw_ics,
            etag=obj.etag,
            uid=obj.uid,
            component_name=obj.component,
            last_modified=_http_date(obj.updated_at),
        )

    def _append_version(self, obj, operation, text, etag):
        seq = (db.session.query(db.func.coalesce(db.func.max(CalDavVersion.seq), 0))
               .filter(CalDavVersion.object_id == obj.id).scalar() or 0) + 1
        db.session.add(CalDavVersion(
            object_id=obj.id, seq=seq, operation=operation,
            raw_ics=text, etag=etag,
            author=self._storage.request_agent,
            author_user_id=self._owner_user_id(),
        ))

    def _find_uid_by_summary(self, text):
        """Best-effort dependency resolution within this collection."""
        needle = (text or '').strip().lower()
        if not needle:
            return None
        for obj in self._live_objects():
            if not obj.raw_ics:
                continue
            component = mapping.primary_component(vobject.readOne(obj.raw_ics))
            summary = (mapping._text(component, 'summary') or '').lower()
            if summary and (summary == needle or needle in summary):
                return obj.uid
        return None

    # -- projection -------------------------------------------------------
    def _backing_query(self, kind, user_id):
        from app.models import CalendarEvent, Reminder

        if kind == 'reminder':
            return Reminder.query.filter_by(user_id=user_id)
        return CalendarEvent.query.filter_by(user_id=user_id)

    def _backing_row(self, kind, row_id):
        from app.models import CalendarEvent, Reminder

        if row_id is None:
            return None
        model = Reminder if kind == 'reminder' else CalendarEvent
        return db.session.get(model, row_id)

    def _apply_to_backing(self, component, kind, backing_id, user_id):
        from app.models import CalendarEvent, Reminder

        row = self._backing_row(kind, backing_id)
        if kind == 'reminder':
            if row is None:
                row = Reminder(user_id=user_id, title='Untitled',
                               reminder_type='custom', due_date=datetime.utcnow().date())
                db.session.add(row)
            mapping.component_to_reminder(component, row, user_id)
        else:
            if row is None:
                row = CalendarEvent(user_id=user_id, title='Untitled',
                                    start_at=datetime.utcnow())
                db.session.add(row)
            mapping.component_to_event(component, row, user_id)
        return row

    def _project(self, kind, backing_row, card):
        """Build the canonical component for a May row."""
        from app.models import CalendarAlarm

        if kind == 'reminder':
            vehicle = getattr(backing_row, 'vehicle', None)
            label = getattr(vehicle, 'registration', None) or getattr(vehicle, 'name', None)
            cal = mapping.reminder_to_component(backing_row, card, vehicle_label=label)
        else:
            alarms = backing_row.alarms.order_by(
                CalendarAlarm.trigger_minutes_before.desc()).all()
            cal = mapping.event_to_component(backing_row, card, alarms=alarms)

        component = mapping.primary_component(cal)
        # Deterministic DTSTAMP: see the module docstring.
        stamp = backing_row.updated_at or backing_row.created_at or datetime.utcnow()
        component.dtstamp.value = stamp.replace(tzinfo=timezone.utc)
        sidecar_mod.merge_into_component(component, card)
        return cal

    def _render(self, kind, backing_row, inbound_component, inbound_item, card):
        """Serialize what a GET should return, plus its ETag."""
        if kind in ('reminder', 'calendar_event') and backing_row is not None:
            cal = self._project(kind, backing_row, card)
        else:
            # Opaque collection: keep the client's bytes, restamp our fields.
            cal = inbound_item
            sidecar_mod.merge_into_component(
                mapping.primary_component(cal) or cal, card)
        text = cal.serialize()
        return text, radicale_item.get_etag(text)

    def _reconcile(self):
        """Refresh the index from May's tables. Idempotent, once per request."""
        if self._reconciled or self._row is None:
            return
        self._reconciled = True

        kind = self._row.backing_kind
        if kind not in ('reminder', 'calendar_event'):
            return

        user_id = self._row.user_id
        rows = {r.id: r for r in self._backing_query(kind, user_id).all()}
        indexed = {o.backing_id: o for o in CalDavObject.query.filter_by(
            collection_id=self._row.id).all() if o.backing_id is not None}

        dirty = False

        for row_id, backing_row in rows.items():
            obj = indexed.get(row_id)
            uid = (mapping.reminder_uid(backing_row) if kind == 'reminder'
                   else mapping.event_uid(backing_row))
            card = CalDavSidecar.get_or_create(user_id, uid)
            text = self._project(kind, backing_row, card).serialize()
            etag = radicale_item.get_etag(text)

            if obj is None:
                dirty = True
                db.session.add(CalDavObject(
                    collection_id=self._row.id,
                    href=mapping.href_for('reminder' if kind == 'reminder' else 'event', row_id),
                    uid=uid, component=self._row.component,
                    backing_kind=kind, backing_id=row_id,
                    raw_ics=text, etag=etag,
                    changed_seq=self._row.sync_seq + 1,
                ))
            elif obj.etag != etag or obj.is_deleted:
                dirty = True
                obj.raw_ics = text
                obj.etag = etag
                obj.uid = uid
                obj.deleted_at = None
                obj.changed_seq = self._row.sync_seq + 1
                obj.updated_at = datetime.utcnow()

        for row_id, obj in indexed.items():
            if row_id not in rows and not obj.is_deleted:
                dirty = True
                obj.deleted_at = datetime.utcnow()
                obj.changed_seq = self._row.sync_seq + 1
                obj.raw_ics = None
                obj.etag = None

        if dirty:
            self._row.bump()
            db.session.commit()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class Storage(BaseStorage):
    """Radicale storage backed by May's SQLAlchemy models."""

    _collection_class = Collection

    _is_collision_free = False
    _supports_unicode = True
    _supports_trailing_whitespace = False
    _supports_problematic_chars = True

    def __init__(self, configuration):
        super().__init__(configuration)
        self._user = ''

    @property
    def request_agent(self):
        """User-Agent of the in-flight request, if the middleware captured it."""
        return get_request_agent()

    @property
    def allow_llm(self):
        """Read the LLM toggle from Flask, not from Radicale's config.

        Radicale validates unknown options against its own schema, and this is
        a May setting anyway -- it belongs next to May's other feature flags.
        """
        try:
            return bool(get_app().config.get('CALDAV_ALLOW_LLM', False))
        except RuntimeError:
            return False

    # -- lifecycle --------------------------------------------------------
    @contextlib.contextmanager
    def acquire_lock(self, mode, user='', *args, **kwargs):
        """Wrap the whole request in a Flask app context and a storage lock.

        This is the only place Radicale gives us that brackets an entire
        request, which makes it the right place to own the SQLAlchemy session
        lifecycle.
        """
        self._user = user or ''
        with app_context() as owns_context:
            with storage_lock(mode):
                try:
                    yield
                    if mode == 'w':
                        db.session.commit()
                except Exception:
                    db.session.rollback()
                    raise
                finally:
                    # Only tear the session down if we opened the context. If
                    # we joined someone else's (tests, or a May request that
                    # calls into CalDAV), the session belongs to them.
                    if owns_context:
                        db.session.remove()

    def verify(self):
        with app_context():
            broken = 0
            for obj in CalDavObject.query.filter(CalDavObject.deleted_at.is_(None)).all():
                try:
                    vobject.readOne(obj.raw_ics or '')
                except Exception as exc:
                    broken += 1
                    logger.error('Unparseable stored item %s: %s', obj.href, exc)
            return broken == 0

    # -- discovery --------------------------------------------------------
    def discover(self, path, depth='0', child_context_manager=None, user_groups=frozenset()):
        from app.models import User

        if child_context_manager is None:
            def child_context_manager(path, href=None):
                return contextlib.ExitStack()

        sane = pathutils.strip_path(pathutils.sanitize_path(path))
        parts = sane.split('/') if sane else []

        # /
        if not parts:
            root = Collection(self, '', kind='root')
            yield root
            if depth == '0':
                return
            for user in self._principals():
                with child_context_manager(user.username):
                    yield Collection(self, user.username, kind='principal', user=user)
            return

        username = parts[0]
        user = User.query.filter_by(username=username).first()
        if user is None:
            return

        # /<username>/
        if len(parts) == 1:
            self.ensure_user_collections(user)
            principal = Collection(self, username, kind='principal', user=user)
            yield principal
            if depth == '0':
                return
            for row in user.caldav_collections.order_by(CalDavCollection.name).all():
                with child_context_manager(row.path):
                    yield Collection(self, row.path, row=row, user=user)
            return

        row = CalDavCollection.query.filter_by(user_id=user.id, name=parts[1]).first()
        if row is None:
            return
        collection = Collection(self, f'{username}/{parts[1]}', row=row, user=user)

        # /<username>/<collection>/
        if len(parts) == 2:
            yield collection
            if depth == '0':
                return
            for item in collection.get_all():
                with child_context_manager(collection.path, item.href):
                    yield item
            return

        # /<username>/<collection>/<href>
        href = parts[2]
        for _, item in collection.get_multi([href]):
            if item is not None:
                yield item

    def _principals(self):
        from app.models import User

        if self._user:
            user = User.query.filter_by(username=self._user).first()
            return [user] if user else []
        return User.query.order_by(User.username).all()

    # -- mutation ---------------------------------------------------------
    def create_collection(self, href, items=None, props=None):
        from app.models import User

        sane = pathutils.strip_path(pathutils.sanitize_path(href))
        parts = sane.split('/') if sane else []
        if not parts:
            return create_collection_result(Collection(self, '', kind='root'))

        user = User.query.filter_by(username=parts[0]).first()
        if user is None:
            raise ValueError('Unknown principal: %r' % parts[0])

        # Principal collection: nothing to store, but seed the defaults.
        if len(parts) == 1:
            self.ensure_user_collections(user)
            return create_collection_result(
                Collection(self, parts[0], kind='principal', user=user))

        name = parts[1]
        row = CalDavCollection.query.filter_by(user_id=user.id, name=name).first()
        if row is None:
            row = CalDavCollection(user_id=user.id, name=name, backing_kind='opaque',
                                   component='VEVENT', props={'tag': 'VCALENDAR'})
            db.session.add(row)

        if props:
            merged = dict(row.props or {})
            merged.update({k: v for k, v in props.items() if v is not None})
            row.props = merged
            component = merged.get('C:supported-calendar-component-set')
            if component:
                row.component = component.split(',')[0].strip().upper()
        row.bump()
        db.session.flush()

        collection = Collection(self, row.path, row=row, user=user)

        for item in (items or []):
            component = mapping.primary_component(item.vobject_item)
            uid = radicale_item.get_uid_from_object(item.vobject_item)
            href_ = f'{uid or radicale_item.find_available_uid(lambda _: False)}.ics'
            if collection._object_by_href(href_) is not None:
                raise ComponentExistsError(href_)
            collection.upload(href_, item)

        db.session.commit()
        return create_collection_result(collection)

    def move(self, item, to_collection, to_href):
        obj = item.collection._object_by_href(item.href)
        if obj is None:
            raise ComponentNotFoundError(item.href or '')
        if to_collection.row.backing_kind != obj.backing_kind:
            # Moving a projected Reminder into an opaque calendar would orphan
            # the May row. Refuse rather than silently losing the link.
            raise ValueError('Cannot move between collections with different backings')

        source_seq = item.collection.row.bump()
        obj.changed_seq = source_seq
        obj.deleted_at = datetime.utcnow()
        item.collection._append_version(obj, 'move', obj.raw_ics, obj.etag)

        target_seq = to_collection.row.bump()
        db.session.add(CalDavObject(
            collection_id=to_collection.row.id, href=to_href, uid=obj.uid,
            component=obj.component, backing_kind=obj.backing_kind,
            backing_id=obj.backing_id, raw_ics=obj.raw_ics, etag=obj.etag,
            changed_seq=target_seq))
        db.session.commit()

    # -- provisioning -----------------------------------------------------
    def ensure_user_collections(self, user):
        """Create the default reminders/events calendars for a user, once."""
        created = False
        for spec in DEFAULT_COLLECTIONS:
            existing = CalDavCollection.query.filter_by(
                user_id=user.id, name=spec['name']).first()
            if existing is not None:
                continue
            db.session.add(CalDavCollection(
                user_id=user.id, name=spec['name'],
                backing_kind=spec['backing_kind'], component=spec['component'],
                props=_props_for(spec), sync_seq=1))
            created = True
        if created:
            db.session.commit()
