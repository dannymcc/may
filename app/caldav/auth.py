"""Radicale auth plugin backed by May's User table.

Loaded via ``[auth] type = app.caldav.auth``; ``radicale.utils.load_plugin``
requires the class to be named ``Auth``.

Two credentials are accepted for the same account:

* the account password, and
* the account's API key, used as an app-specific password.

The second exists because CalDAV clients store the credential in the OS
keychain forever and send it on every poll. Handing Apple Calendar a
revocable API key instead of your login password is the same reasoning behind
app-specific passwords everywhere else -- and May already has the key, the
rotation endpoint, and the revocation endpoint.
"""

import hmac
import logging

from radicale.auth import BaseAuth

from app.caldav.runtime import app_context

logger = logging.getLogger(__name__)


class Auth(BaseAuth):

    def _login(self, login, password):
        if not login or not password:
            return ''

        from app.models import User

        with app_context():
            user = User.query.filter_by(username=login).first()
            if user is None:
                # Constant-ish work on the miss path; the real timing defence
                # is BaseAuth._sleep_for_constant_exec_time, which Radicale
                # applies around this call.
                return ''

            if user.api_key and hmac.compare_digest(str(user.api_key), str(password)):
                return user.username

            try:
                if user.check_password(password):
                    if getattr(user, 'must_change_password', False):
                        logger.warning(
                            'CalDAV login refused for %r: password change required',
                            login)
                        return ''
                    return user.username
            except Exception as exc:  # malformed hash, etc.
                logger.warning('CalDAV password check failed for %r: %s', login, exc)

            return ''
