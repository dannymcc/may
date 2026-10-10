"""Verify starting-odometer upgrades preserve vehicles and blank defaults."""
import importlib.util
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_starting_odometer_migration(monkeypatch):
    """Upgrade twice without losing a baseline, then roll back safely."""
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/b8d0f3a5c721_add_starting_odometer.py'
    spec = importlib.util.spec_from_file_location('starting_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sa.create_engine('sqlite://').begin() as connection:
        connection.execute(sa.text('CREATE TABLE vehicles (id INTEGER PRIMARY KEY, name TEXT)'))
        connection.execute(sa.text("INSERT INTO vehicles VALUES (1, 'Existing vehicle')"))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.execute(sa.text('SELECT starting_odometer FROM vehicles')).scalar() is None
        connection.execute(sa.text('UPDATE vehicles SET starting_odometer = 16'))
        migration.upgrade()
        assert connection.execute(sa.text('SELECT starting_odometer FROM vehicles')).scalar() == 16
        migration.downgrade()
        assert 'starting_odometer' not in {column['name'] for column in sa.inspect(connection).get_columns('vehicles')}
        assert connection.execute(sa.text('SELECT name FROM vehicles')).scalar() == 'Existing vehicle'
