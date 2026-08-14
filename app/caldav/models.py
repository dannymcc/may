"""SQLAlchemy models backing May's CalDAV facade.

Four concerns, deliberately separated:

* ``CalDavCollection`` -- a calendar collection owned by a May user.
* ``CalDavObject``     -- authoritative index of every CalDAV resource.
* ``CalDavVersion``    -- append-only history; every write appends a row.
* ``CalDavSidecar``    -- the superset schema: fields iCalendar cannot carry.

Two design decisions worth stating up front, because everything else follows
from them:

1. The sidecar is keyed by ``(user_id, uid, recurrence_id)``, not by object
   id. Calendar clients delete and recreate resources during conflict
   resolution, and some (notably Google) strip unknown ``X-`` properties on
   every edit. Keying on UID means our extra fields survive both.

2. Writes are append-only. ``CalDavObject`` holds the current state,
   ``CalDavVersion`` holds every state it has ever had, including deletions.
   That gives us conflict forensics, slip telemetry, and a correct
   RFC 6578 sync-collection implementation for free.
"""

from datetime import datetime

from sqlalchemy import JSON, UniqueConstraint
from sqlalchemy.ext.mutable import MutableDict, MutableList

from app import db

# Component types we serve. VJOURNAL is parsed but not mapped to a May model.
COMPONENT_TYPES = ('VEVENT', 'VTODO', 'VJOURNAL')

# What a collection is backed by. 'opaque' collections store client .ics
# verbatim and never touch May's own tables -- the Mailpit-style sink.
BACKING_KINDS = ('reminder', 'calendar_event', 'opaque')

ENERGY_LEVELS = ('low', 'medium', 'high')


class CalDavCollection(db.Model):
    """A CalDAV collection (calendar) at /<username>/<name>/."""

    __tablename__ = 'caldav_collections'
    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='uq_caldav_collection_user_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Path segment, e.g. 'reminders'. Must be URL-safe.
    name = db.Column(db.String(64), nullable=False)
    # What May model this collection projects. See BACKING_KINDS.
    backing_kind = db.Column(db.String(32), nullable=False, default='opaque')
    # Component this collection advertises in supported-calendar-component-set.
    component = db.Column(db.String(16), nullable=False, default='VEVENT')

    # WebDAV/CalDAV properties (displayname, calendar-colour, tag, ...).
    props = db.Column(MutableDict.as_mutable(JSON), nullable=False, default=dict)

    # Monotonic counter behind both the CTag and the RFC 6578 sync-token.
    # Bumped on every mutation anywhere in the collection.
    sync_seq = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('caldav_collections', lazy='dynamic'))
    objects = db.relationship('CalDavObject', back_populates='collection',
                              lazy='dynamic', cascade='all, delete-orphan')

    @property
    def path(self):
        return f'{self.user.username}/{self.name}'

    def bump(self):
        """Advance the sync counter. Returns the new value."""
        self.sync_seq = (self.sync_seq or 0) + 1
        self.updated_at = datetime.utcnow()
        return self.sync_seq


class CalDavObject(db.Model):
    """One CalDAV resource -- an .ics file as far as the client is concerned."""

    __tablename__ = 'caldav_objects'
    __table_args__ = (
        UniqueConstraint('collection_id', 'href', name='uq_caldav_object_href'),
        db.Index('ix_caldav_object_changed', 'collection_id', 'changed_seq'),
    )

    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('caldav_collections.id'),
                              nullable=False, index=True)

    href = db.Column(db.String(255), nullable=False)
    uid = db.Column(db.String(255), nullable=False, index=True)
    # Empty string for the master instance; set for RECURRENCE-ID overrides.
    recurrence_id = db.Column(db.String(64), nullable=False, default='')
    component = db.Column(db.String(16), nullable=False, default='VEVENT')

    # Link back to the May row this projects, when there is one.
    backing_kind = db.Column(db.String(32), nullable=False, default='opaque')
    backing_id = db.Column(db.Integer, nullable=True, index=True)

    # Last serialized form. Source of truth for 'opaque'; a cache for mapped
    # objects, kept so ETags stay stable when nothing semantic changed.
    raw_ics = db.Column(db.Text, nullable=True)
    etag = db.Column(db.String(80), nullable=True)

    # Tombstones: kept so sync-collection can report deletions to clients.
    deleted_at = db.Column(db.DateTime, nullable=True)
    changed_seq = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    collection = db.relationship('CalDavCollection', back_populates='objects')
    versions = db.relationship('CalDavVersion', back_populates='obj',
                               lazy='dynamic', cascade='all, delete-orphan',
                               order_by='CalDavVersion.seq')

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class CalDavVersion(db.Model):
    """Append-only history. One row per PUT, MOVE, or DELETE."""

    __tablename__ = 'caldav_versions'
    __table_args__ = (
        UniqueConstraint('object_id', 'seq', name='uq_caldav_version_seq'),
    )

    id = db.Column(db.Integer, primary_key=True)
    object_id = db.Column(db.Integer, db.ForeignKey('caldav_objects.id'),
                          nullable=False, index=True)

    seq = db.Column(db.Integer, nullable=False)
    operation = db.Column(db.String(16), nullable=False)  # create|update|delete|move
    raw_ics = db.Column(db.Text, nullable=True)
    etag = db.Column(db.String(80), nullable=True)

    # Provenance of the change, so you can tell Fantastical from DAVx5 from
    # May's own UI when a conflict needs explaining.
    author = db.Column(db.String(255), nullable=True)      # User-Agent
    author_user_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    obj = db.relationship('CalDavObject', back_populates='versions')


class CalDavSidecar(db.Model):
    """Fields iCalendar cannot carry, keyed by UID so they survive the client.

    Precedence rule, enforced in ``app.caldav.enrichment``: a value the user
    set explicitly is never overwritten by a derived one. ``locked_fields``
    records which fields the user has claimed.
    """

    __tablename__ = 'caldav_sidecar'
    __table_args__ = (
        UniqueConstraint('user_id', 'uid', 'recurrence_id',
                         name='uq_caldav_sidecar_uid'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    uid = db.Column(db.String(255), nullable=False, index=True)
    recurrence_id = db.Column(db.String(64), nullable=False, default='')

    # --- Effort -----------------------------------------------------------
    estimate_minutes = db.Column(db.Integer, nullable=True)
    actual_minutes = db.Column(db.Integer, nullable=True)

    # --- Slip telemetry (computed, never user-supplied) --------------------
    reschedule_count = db.Column(db.Integer, nullable=False, default=0)
    slip_days = db.Column(db.Integer, nullable=False, default=0)
    touch_count = db.Column(db.Integer, nullable=False, default=0)
    first_due_at = db.Column(db.DateTime, nullable=True)
    last_due_at = db.Column(db.DateTime, nullable=True)
    last_touched_at = db.Column(db.DateTime, nullable=True)

    # --- Disposition ------------------------------------------------------
    energy = db.Column(db.String(16), nullable=True)          # see ENERGY_LEVELS
    contexts = db.Column(MutableList.as_mutable(JSON), nullable=False, default=list)

    # --- Provenance -------------------------------------------------------
    source_url = db.Column(db.String(1000), nullable=True)
    source_ref = db.Column(db.String(255), nullable=True)     # ticket id, commit, Message-ID
    source_system = db.Column(db.String(64), nullable=True)   # github, gmail, may, ...

    # --- Dependencies (UID lists; resolved into a DAG at read time) --------
    blocked_by = db.Column(MutableList.as_mutable(JSON), nullable=False, default=list)
    blocks = db.Column(MutableList.as_mutable(JSON), nullable=False, default=list)

    # --- Derived fields ---------------------------------------------------
    # {field: {value, source, confidence, model, computed_at, evidence}}
    # Free-form on purpose: enrichers may emit fields that have no column yet.
    derived = db.Column(MutableDict.as_mutable(JSON), nullable=False, default=dict)
    # Fields the user set by hand. Enrichers must not touch these.
    locked_fields = db.Column(MutableList.as_mutable(JSON), nullable=False, default=list)
    # Hash of the text last fed to the enrichment pipeline, so we can skip
    # re-running (and re-paying for) enrichment when nothing relevant changed.
    enriched_digest = db.Column(db.String(64), nullable=True)
    enriched_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('caldav_sidecars', lazy='dynamic'))

    # ------------------------------------------------------------------
    def lock(self, field):
        """Mark ``field`` as user-owned so enrichers leave it alone."""
        if field not in self.locked_fields:
            self.locked_fields = list(self.locked_fields) + [field]

    def is_locked(self, field):
        return field in (self.locked_fields or [])

    def to_dict(self):
        return {
            'uid': self.uid,
            'recurrence_id': self.recurrence_id or None,
            'estimate_minutes': self.estimate_minutes,
            'actual_minutes': self.actual_minutes,
            'reschedule_count': self.reschedule_count,
            'slip_days': self.slip_days,
            'touch_count': self.touch_count,
            'first_due_at': self.first_due_at.isoformat() if self.first_due_at else None,
            'last_due_at': self.last_due_at.isoformat() if self.last_due_at else None,
            'last_touched_at': self.last_touched_at.isoformat() if self.last_touched_at else None,
            'energy': self.energy,
            'contexts': list(self.contexts or []),
            'source_url': self.source_url,
            'source_ref': self.source_ref,
            'source_system': self.source_system,
            'blocked_by': list(self.blocked_by or []),
            'blocks': list(self.blocks or []),
            'derived': dict(self.derived or {}),
            'locked_fields': list(self.locked_fields or []),
            'enriched_at': self.enriched_at.isoformat() if self.enriched_at else None,
        }

    @classmethod
    def get_or_create(cls, user_id, uid, recurrence_id=''):
        row = cls.query.filter_by(user_id=user_id, uid=uid,
                                  recurrence_id=recurrence_id or '').first()
        if row is None:
            row = cls(user_id=user_id, uid=uid, recurrence_id=recurrence_id or '',
                      contexts=[], blocked_by=[], blocks=[], derived={},
                      locked_fields=[])
            db.session.add(row)
        return row
