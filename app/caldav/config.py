"""Assemble the Radicale configuration May runs with.

Radicale normally reads an ini file. Mounted in-process there is no file, so
we build a ``Configuration`` in memory and point the three plugin hooks at
May's own modules.
"""

import logging

logger = logging.getLogger(__name__)

#: Values are strings because ``Configuration.update`` runs each option
#: through its declared parser when handed a string.
DEFAULTS = {
    'auth': {
        'type': 'app.caldav.auth',
        'realm': 'May',
        # BaseAuth's login cache only applies to backends it considers slow.
        # Ours is a single indexed SELECT, so leave it off and keep password
        # changes taking effect immediately.
        'cache_logins': 'False',
        'delay': '1',
    },
    'rights': {
        'type': 'app.caldav.rights',
    },
    'storage': {
        'type': 'app.caldav.storage',
        # Radicale's own filesystem hooks/cache options do not apply to us.
        'max_sync_token_age': '2592000',   # 30 days
    },
    'web': {
        # May has its own UI; Radicale's would be a second, unstyled one.
        'type': 'none',
    },
    'logging': {
        'level': 'warning',
    },
}


def build_configuration(app=None, overrides=None):
    """Return a Radicale ``Configuration`` wired to May's plugins."""
    from radicale import config as radicale_config

    configuration = radicale_config.load()

    settings = {section: dict(options) for section, options in DEFAULTS.items()}

    if app is not None:
        if app.config.get('CALDAV_REALM'):
            settings['auth']['realm'] = str(app.config['CALDAV_REALM'])
        if app.debug:
            settings['logging']['level'] = 'debug'

    for section, options in (overrides or {}).items():
        settings.setdefault(section, {}).update(
            {k: str(v) for k, v in options.items()})

    # privileged=True permits internal (underscore-prefixed) options; harmless
    # for the ones above and needed if you later set server._internal_server.
    configuration.update(settings, 'may', privileged=True)
    return configuration
