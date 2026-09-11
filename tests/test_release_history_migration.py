"""Upgrade real old-shaped tables without losing readings, services or fitments."""
import importlib.util
from datetime import date
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app import db, _run_schema_migrations
from app.models import FuelLog, MaintenanceSchedule, MaintenanceEvent, TireSet, TireFitment


@pytest.mark.parametrize('method', ['alembic', 'startup_recovery'])
def test_upgrade_preserves_legacy_history(app, test_user, sample_vehicle, method):
    vehicle_id = sample_vehicle.id
    schedule = MaintenanceSchedule(vehicle_id=vehicle_id, user_id=test_user.id,
                                   name='Old service', maintenance_type='custom',
                                   last_performed_date=date(2025, 1, 1), last_performed_odometer=10000)
    tire = TireSet(vehicle_id=vehicle_id, user_id=test_user.id, name='Legacy set')
    db.session.add_all([schedule, tire])
    db.session.flush()
    db.session.add_all([
        FuelLog(vehicle_id=vehicle_id, user_id=test_user.id, date=date(2024, 1, 1), odometer=0, volume=40),
        FuelLog(vehicle_id=vehicle_id, user_id=test_user.id, date=date(2025, 1, 1), odometer=10000, volume=40),
        TireFitment(tire_set_id=tire.id, fitted_date=date(2024, 1, 1), fitted_odometer=1000),
    ])
    db.session.commit()
    db.session.remove()
    with db.engine.begin() as connection:
        connection.execute(text('DROP TABLE maintenance_events'))
        connection.execute(text('ALTER TABLE fuel_logs DROP COLUMN odometer_confirmed'))
        connection.execute(text('ALTER TABLE tire_fitments DROP COLUMN axle'))
    if method == 'startup_recovery':
        db.create_all()
        _run_schema_migrations(app)
        _run_schema_migrations(app)
    else:
        path = Path(__file__).resolve().parents[1] / 'migrations/versions/e1f2a3b4c5d6_add_history_axles_and_confirmed_readings.py'
        spec = importlib.util.spec_from_file_location('history_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with db.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
    logs = FuelLog.query.order_by(FuelLog.odometer).all()
    assert [log.odometer for log in logs] == [0, 10000]
    assert not logs[0].has_recorded_odometer
    assert logs[1].has_recorded_odometer
    assert TireFitment.query.one().axle == 'all'
    event = MaintenanceEvent.query.one()
    assert event.name == 'Old service'
    assert event.odometer == 10000
    assert event.performed_date == date(2025, 1, 1)
