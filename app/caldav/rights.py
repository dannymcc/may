"""Radicale rights plugin: a user owns exactly their own principal.

Loaded via ``[rights] type = app.caldav.rights``; the class must be named
``Rights``.

Radicale's permission letters (see ``radicale.rights``):

* ``R`` read plain collections        * ``W`` write plain collections
* ``r`` read calendars/address books  * ``w`` write calendars/address books
* ``i`` GET-only subset of ``r``

May has no sharing model for calendars yet, so this is deliberately the
strictest useful policy: authenticated users get read on the root (needed for
principal discovery) and full access to their own tree, nothing else. When
May's existing vehicle-sharing model grows a calendar dimension, this is the
one function that needs to change.
"""

from radicale.rights import BaseRights

from app.caldav.runtime import app_context

FULL = 'RrWw'
READ_ONLY = 'Rr'


class Rights(BaseRights):

    def authorization(self, user, path):
        if not user:
            return ''

        sane = path.strip('/')

        # Root: needed so clients can walk to current-user-principal.
        if not sane:
            return 'R'

        owner = sane.split('/', 1)[0]
        if owner == user:
            return FULL

        if self._is_admin(user):
            # Admins can read other principals for support purposes but not
            # write them -- an admin fat-fingering someone else's calendar in
            # a CalDAV client is not a recoverable situation.
            return READ_ONLY

        return ''

    @staticmethod
    def _is_admin(username):
        from app.models import User

        with app_context():
            user = User.query.filter_by(username=username).first()
            return bool(user and user.is_admin)
