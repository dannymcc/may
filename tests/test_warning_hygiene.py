"""Guards against the warning noise cleaned up in issue #302.

The suite used to emit thousands of deprecation warnings, which pushed real
FAILED lines off the end of a truncated CI log. Each cause was fixed at
source; these tests keep them fixed.
"""
import re
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db
from app.models import User, Vehicle
from app.utils import utcfromtimestamp, utcnow

REPO_ROOT = Path(__file__).resolve().parent.parent


# app/utils.py defines the replacements and names the deprecated spellings in
# its docstrings; this module quotes them in its assertions. Both would
# otherwise report themselves.
_SELF_REFERENTIAL = {'app/utils.py', 'tests/test_warning_hygiene.py'}


def _python_sources():
    """Every Python file we own: app code, tests, and the top-level modules."""
    paths = []
    for directory in ('app', 'tests'):
        paths.extend(
            path for path in sorted((REPO_ROOT / directory).rglob('*.py'))
            if '__pycache__' not in path.parts
        )
    paths.extend(REPO_ROOT / name for name in ('config.py', 'run.py'))
    return [p for p in paths if str(p.relative_to(REPO_ROOT)) not in _SELF_REFERENTIAL]


class TestUtcNow:
    """app.utils.utcnow replaces the deprecated datetime.utcnow."""

    def test_returns_naive_datetime(self):
        # Every db.DateTime column holds naive UTC. An aware value would give
        # new rows an offset that older rows lack, and comparing the two
        # raises TypeError, so the helper has to stay naive.
        assert utcnow().tzinfo is None

    def test_matches_current_utc_time(self):
        assert abs(utcnow() - datetime.now(timezone.utc).replace(tzinfo=None)) < timedelta(seconds=5)

    def test_utcfromtimestamp_is_naive_utc(self):
        assert utcfromtimestamp(0) == datetime(1970, 1, 1)
        assert utcfromtimestamp(1_700_000_000).tzinfo is None

    def test_column_defaults_use_the_helper(self, app):
        # A regression guard on the substitution itself: the defaults have to
        # keep producing a naive datetime, or new rows differ from old ones.
        assert User.__table__.c.created_at.default.arg is not None
        created = User.__table__.c.created_at.default.arg(None)
        assert created.tzinfo is None


class TestNoDeprecatedCallsInSource:
    """The deprecated spellings should not creep back in."""

    def test_no_datetime_utcnow(self):
        pattern = re.compile(r'\bdatetime\.utcnow\b|\bdatetime\.utcfromtimestamp\b')
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in _python_sources()
            if pattern.search(path.read_text())
        ]
        assert offenders == [], (
            'datetime.utcnow()/utcfromtimestamp() are deprecated in Python 3.12; '
            'use app.utils.utcnow()/utcfromtimestamp() instead'
        )

    def test_no_legacy_query_get(self):
        # Query.get() and Query.get_or_404() both route through the legacy
        # SQLAlchemy 1.x API. db.session.get() and db.get_or_404() do not.
        pattern = re.compile(r'\.query\.get(_or_404)?\(')
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in _python_sources()
            if pattern.search(path.read_text())
        ]
        assert offenders == [], (
            'Model.query.get()/get_or_404() are legacy; use db.session.get(Model, id) '
            'or db.get_or_404(Model, id)'
        )

    def test_no_blanket_warning_filter(self):
        # The acceptance criteria for #302 rule out silencing warnings wholesale.
        config = (REPO_ROOT / 'pytest.ini').read_text()
        assert not re.search(r'^\s*ignore\s*$', config, re.M)
        assert 'filterwarnings' not in config or 'ignore::Warning' not in config


class TestSchemaEmitsNoWarnings:
    """The users/vehicles cycle no longer defeats table sorting."""

    def test_create_and_drop_all_are_quiet(self, app):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            db.drop_all()
            db.create_all()
        messages = [str(w.message) for w in caught]
        assert messages == [], messages

    def test_default_vehicle_fk_is_deferred(self):
        # The cycle is deliberate (a vehicle has an owner; a user pins a
        # default vehicle), so the nullable half is marked use_alter.
        fk = next(iter(User.__table__.c.default_vehicle_id.foreign_keys))
        assert fk.use_alter is True
        assert fk.name == 'fk_users_default_vehicle_id'
        assert any(f.column.table.name == 'users' for f in Vehicle.__table__.c.owner_id.foreign_keys)


class TestQueryHelpersBehaveAsBefore:
    """db.session.get is a like-for-like replacement for Query.get."""

    @pytest.mark.parametrize('missing', ['not-an-id', 999999])
    def test_session_get_returns_none_for_missing_ids(self, app, missing):
        assert db.session.get(Vehicle, missing) is None

    def test_session_get_finds_existing_row(self, app, sample_vehicle):
        assert db.session.get(Vehicle, sample_vehicle.id) is sample_vehicle

    def test_get_or_404_aborts_for_missing_row(self, app):
        from werkzeug.exceptions import NotFound

        with pytest.raises(NotFound):
            db.get_or_404(Vehicle, 999999)
