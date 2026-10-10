"""Existing accounts retain the default-off preference across schema upgrades."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_net_cost_preference_migration(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/a7c9e2f4b610_add_net_cost_preference.py'
    spec = importlib.util.spec_from_file_location('net_cost_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)'))
        connection.execute(sa.text("INSERT INTO users VALUES (1, 'existing')"))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.execute(sa.text('SELECT show_net_cost_per_distance FROM users')).scalar() == 0
        connection.execute(sa.text('UPDATE users SET show_net_cost_per_distance = 1'))
        migration.upgrade()  # Startup schema bootstrap may already have added the column.
        assert connection.execute(sa.text('SELECT show_net_cost_per_distance FROM users')).scalar() == 1
        migration.downgrade()
        assert 'show_net_cost_per_distance' not in {c['name'] for c in sa.inspect(connection).get_columns('users')}
        assert connection.execute(sa.text('SELECT username FROM users')).scalar() == 'existing'
