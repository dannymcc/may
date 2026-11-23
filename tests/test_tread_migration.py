"""Upgrade populated installations without inventing individual tire records."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_tread_migration(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/c924e78a10bd_add_tire_tread_history.py'
    spec = importlib.util.spec_from_file_location('tread_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sa.create_engine('sqlite://').begin() as connection:
        connection.execute(sa.text('CREATE TABLE tire_sets (id INTEGER PRIMARY KEY, name TEXT)'))
        connection.execute(sa.text("INSERT INTO tire_sets VALUES (1, 'Winter')"))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.execute(sa.text('SELECT tread_warning_mm FROM tire_sets')).scalar() is None
        assert connection.execute(sa.text('SELECT COUNT(*) FROM tires')).scalar() == 0
        connection.execute(sa.text('UPDATE tire_sets SET tread_warning_mm = 4'))
        connection.execute(sa.text("INSERT INTO tires VALUES (1, 1, 'stable', 'A')"))
        connection.execute(sa.text("INSERT INTO tire_measurements VALUES (1, 1, '2026-10-01', 6.5, NULL, 'front_left')"))
        migration.upgrade()
        assert connection.execute(sa.text('SELECT tread_warning_mm FROM tire_sets')).scalar() == 4
        assert connection.execute(sa.text('SELECT depth_mm FROM tire_measurements')).scalar() == 6.5
        migration.downgrade()
        assert 'tires' not in sa.inspect(connection).get_table_names()
        assert connection.execute(sa.text('SELECT name FROM tire_sets')).scalar() == 'Winter'
