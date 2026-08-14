"""CalDAV facade for May.

Mount it from the app factory::

    from app.caldav import mount_caldav
    mount_caldav(app)

after which Apple Calendar, Apple Reminders, Fantastical, Thunderbird and
DAVx5 can two-way sync against ``https://<host>/caldav/`` using a May username
and either the account password or its API key.

Nothing here is imported at module load beyond the models, so a deployment
without ``radicale`` installed still starts -- ``mount_caldav`` degrades to a
warning instead of an ImportError at boot.
"""

import logging

logger = logging.getLogger(__name__)

__all__ = ['mount_caldav', 'is_available']


def is_available():
    """True if the optional CalDAV dependencies are installed."""
    try:
        import radicale  # noqa: F401
        import vobject   # noqa: F401
    except ImportError:
        return False
    return True


class _AgentMiddleware:
    """Stash the User-Agent so the version history can record who wrote what.

    Radicale does not pass request metadata down to storage plugins, and
    knowing whether a change came from Fantastical, DAVx5, or May's own UI is
    most of what makes the append-only history worth keeping.
    """

    def __init__(self, wsgi_app):
        self._wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        from app.caldav.runtime import set_request_agent

        set_request_agent(environ.get('HTTP_USER_AGENT'))
        try:
            return self._wsgi_app(environ, start_response)
        finally:
            set_request_agent(None)


def mount_caldav(app, prefix='/caldav'):
    """Mount the Radicale WSGI app inside the Flask app at ``prefix``."""
    if not app.config.get('CALDAV_ENABLED', True):
        logger.info('CalDAV disabled by config')
        return app

    if not is_available():
        logger.warning(
            'CalDAV not mounted: install `radicale` and `vobject` to enable it')
        return app

    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    from app.caldav.config import build_configuration
    from app.caldav.runtime import bind_app

    bind_app(app)

    from radicale.app import Application

    radicale_app = _AgentMiddleware(Application(build_configuration(app)))
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {prefix: radicale_app})

    _register_well_known(app, prefix)
    logger.info('CalDAV mounted at %s', prefix)
    return app


def _register_well_known(app, prefix):
    """Serve /.well-known/caldav at the site root.

    RFC 6764 discovery hits the *host* root, not our mount point, so Radicale's
    own well-known handling never sees it. Apple clients and Fantastical rely
    on this redirect to turn "may.example.com" into a working account.
    """
    from flask import redirect

    def _well_known():
        return redirect(prefix + '/', code=301)

    for rule in ('/.well-known/caldav', '/.well-known/carddav'):
        app.add_url_rule(rule, f'caldav_well_known_{rule[-7:]}', _well_known)
