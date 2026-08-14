"""Process-local glue between Radicale and the Flask app.

Radicale instantiates its plugins from dotted-path strings in a config file,
so there is no way to hand it a Flask app object. Instead the app registers
itself here at mount time and the plugins look it up.

Also home to the storage lock and to version shims for the two Radicale
plugin methods whose return shape changed across 3.x.
"""

import contextlib
import inspect
import threading

_FLASK_APP = None
_LOCK = threading.RLock()
_LOCAL = threading.local()


# ---------------------------------------------------------------------------
# Per-request metadata
# ---------------------------------------------------------------------------

def set_request_agent(value):
    """Record the User-Agent of the in-flight CalDAV request."""
    _LOCAL.agent = (value or None)


def get_request_agent():
    return getattr(_LOCAL, 'agent', None)


# ---------------------------------------------------------------------------
# Flask app binding
# ---------------------------------------------------------------------------

def bind_app(app):
    """Register the Flask app the CalDAV plugins should run inside."""
    global _FLASK_APP
    _FLASK_APP = app
    return app


def get_app():
    if _FLASK_APP is None:
        raise RuntimeError(
            'CalDAV plugins used before app.caldav.runtime.bind_app() was called. '
            'Call mount_caldav(app) from create_app().')
    return _FLASK_APP


@contextlib.contextmanager
def app_context():
    """Push a Flask app context unless one is already active.

    Yields ``True`` if we pushed it, ``False`` if we joined an existing one.
    Callers must use that flag before tearing down the SQLAlchemy session:
    under pytest (and anywhere else May pushes its own context) the session is
    not ours to remove, and removing it would detach objects the caller still
    holds.
    """
    from flask import has_app_context

    if has_app_context():
        yield False
        return
    ctx = get_app().app_context()
    ctx.push()
    try:
        yield True
    finally:
        ctx.pop()


# ---------------------------------------------------------------------------
# Storage lock
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def storage_lock(mode='r'):
    """Serialise writes.

    A single reentrant lock rather than a real RW lock: SQLite serialises
    writers anyway, and on Postgres this costs nothing measurable at the
    request rates a personal CalDAV server sees. Swap in a proper RW lock if
    you move to a multi-worker Postgres deployment and profiling says so.
    """
    if mode == 'w':
        with _LOCK:
            yield
    else:
        yield


# ---------------------------------------------------------------------------
# Radicale version shims
# ---------------------------------------------------------------------------

def _returns_tuple(func):
    """True if ``func``'s return annotation mentions a Tuple."""
    try:
        annotation = inspect.signature(func).return_annotation
    except (TypeError, ValueError):  # pragma: no cover
        return True
    return 'Tuple' in str(annotation) or 'tuple' in str(annotation)


def upload_result(new_item, old_item):
    """Return whatever this Radicale expects from ``BaseCollection.upload``.

    3.2 and earlier returned the item; later versions return
    ``(item, replaced_item_or_None)``.
    """
    from radicale.storage import BaseCollection

    if _returns_tuple(BaseCollection.upload):
        return new_item, old_item
    return new_item


def create_collection_result(collection):
    """Same idea for ``BaseStorage.create_collection``.

    Newer Radicale returns ``(collection, {}, [])``.
    """
    from radicale.storage import BaseStorage

    if _returns_tuple(BaseStorage.create_collection):
        return collection, {}, []
    return collection
