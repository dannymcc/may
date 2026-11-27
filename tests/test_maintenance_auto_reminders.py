"""'Automatically create reminder when due' on maintenance schedules works (0.46.2)."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import db
from app.models import FuelLog, MaintenanceSchedule, Reminder
from app.services.reminder_processor import create_maintenance_reminders

TODAY = date(2026, 11, 27)


def _schedule(vehicle, user, **fields):
    values = dict(vehicle_id=vehicle.id, user_id=user.id, name='Oil change',
                  maintenance_type='oil_change', auto_remind=True, remind_days_before=14)
    values.update(fields)
    schedule = MaintenanceSchedule(**values)
    db.session.add(schedule)
    db.session.commit()
    return schedule


def _odometer(vehicle, user, reading):
    db.session.add(FuelLog(vehicle_id=vehicle.id, user_id=user.id, date=TODAY,
                           odometer=reading, volume=40, total_cost=60, is_full_tank=True))
    db.session.commit()


def test_date_schedule_gets_one_reminder_inside_its_window(app, sample_vehicle, test_user):
    schedule = _schedule(sample_vehicle, test_user, next_due_date=TODAY + timedelta(days=10))
    assert create_maintenance_reminders(TODAY)['created'] == 1
    reminder = Reminder.query.one()
    assert reminder.title == 'Oil change'
    assert reminder.reminder_type == 'oil_change'
    assert reminder.due_date == TODAY + timedelta(days=10)
    assert reminder.maintenance_schedule_id == schedule.id
    assert reminder.user_id == test_user.id
    # Notified on the next run, not a further lead period later.
    assert reminder.due_date - timedelta(days=reminder.notify_days_before) <= TODAY

    assert create_maintenance_reminders(TODAY)['created'] == 0
    assert Reminder.query.count() == 1


def test_outside_the_window_nothing_is_created(app, sample_vehicle, test_user):
    _schedule(sample_vehicle, test_user, next_due_date=TODAY + timedelta(days=30))
    assert create_maintenance_reminders(TODAY)['created'] == 0


@pytest.mark.parametrize('fields', [
    {'auto_remind': False}, {'is_active': False},
])
def test_unticked_or_inactive_schedules_are_ignored(app, sample_vehicle, test_user, fields):
    _schedule(sample_vehicle, test_user, next_due_date=TODAY, **fields)
    assert create_maintenance_reminders(TODAY)['created'] == 0


def test_archived_vehicle_is_ignored(app, sample_vehicle, test_user):
    sample_vehicle.is_active = False
    _schedule(sample_vehicle, test_user, next_due_date=TODAY)
    assert create_maintenance_reminders(TODAY)['created'] == 0


def test_reading_schedule_reminds_when_close_to_the_next_reading(app, sample_vehicle, test_user):
    _schedule(sample_vehicle, test_user, next_due_odometer=20000, remind_miles_before=500,
              maintenance_type='brake_fluid', name='Brake fluid')
    _odometer(sample_vehicle, test_user, 19000)
    assert create_maintenance_reminders(TODAY)['created'] == 0
    _odometer(sample_vehicle, test_user, 19600)
    assert create_maintenance_reminders(TODAY)['created'] == 1
    reminder = Reminder.query.one()
    assert reminder.due_date == TODAY
    assert reminder.reminder_type == 'service'
    assert reminder.description == 'Due at 20,000 km'
    # A later day must not produce a second reminder for the same cycle.
    assert create_maintenance_reminders(TODAY + timedelta(days=1))['created'] == 0


def test_hours_vehicle_uses_an_hours_sized_lead(app, sample_vehicle, test_user):
    sample_vehicle.tracking_unit = 'hours'
    _schedule(sample_vehicle, test_user, next_due_odometer=1250, interval_hours=250)
    _odometer(sample_vehicle, test_user, 1000)
    assert create_maintenance_reminders(TODAY)['created'] == 0
    _odometer(sample_vehicle, test_user, 1230)
    assert create_maintenance_reminders(TODAY)['created'] == 1


def test_existing_open_reminder_with_the_same_name_is_respected(app, sample_vehicle, test_user):
    db.session.add(Reminder(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                            title='Oil change', reminder_type='service', due_date=TODAY))
    _schedule(sample_vehicle, test_user, next_due_date=TODAY)
    assert create_maintenance_reminders(TODAY)['created'] == 0
    assert Reminder.query.count() == 1


def test_completing_the_schedule_closes_the_reminder_and_starts_a_new_cycle(
        auth_client, sample_vehicle, test_user):
    schedule = _schedule(sample_vehicle, test_user, interval_months=1,
                         next_due_date=date.today() + timedelta(days=3))
    assert create_maintenance_reminders()['created'] == 1
    first = Reminder.query.one()

    response = auth_client.post(f'/maintenance/{schedule.id}/complete',
                                data={'performed_date': date.today().isoformat(),
                                      'odometer': '10000'})
    assert response.status_code == 302
    db.session.refresh(first)
    assert first.is_completed is True

    # The next cycle is a month away, outside the 14-day window...
    assert create_maintenance_reminders()['created'] == 0
    # ...and once inside it, the new cycle gets its own reminder.
    soon = schedule.next_due_date - timedelta(days=5)
    assert create_maintenance_reminders(soon)['created'] == 1
    assert Reminder.query.filter_by(is_completed=False).count() == 1


def test_marking_performed_from_an_expense_closes_the_reminder(
        auth_client, sample_vehicle, test_user):
    schedule = _schedule(sample_vehicle, test_user, interval_months=6,
                         next_due_date=date.today() + timedelta(days=3))
    create_maintenance_reminders()
    auth_client.post('/expenses/new', data={
        'vehicle_id': str(sample_vehicle.id), 'date': date.today().isoformat(),
        'category': 'maintenance', 'description': 'Oil', 'cost': '60',
        'maintenance_schedule_id': str(schedule.id),
    })
    assert Reminder.query.one().is_completed is True


def test_migration_adds_and_removes_the_link_columns(monkeypatch):
    path = (Path(__file__).resolve().parents[1]
            / 'migrations/versions/f3a1c9d2b7e4_link_reminders_to_maintenance.py')
    spec = importlib.util.spec_from_file_location('reminder_link_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sa.create_engine('sqlite://').begin() as connection:
        connection.execute(sa.text('CREATE TABLE maintenance_schedules (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE reminders (id INTEGER PRIMARY KEY, title TEXT)'))
        connection.execute(sa.text("INSERT INTO reminders VALUES (1, 'MOT')"))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()  # idempotent, as startup schema recovery may run first
        columns = {c['name'] for c in sa.inspect(connection).get_columns('reminders')}
        assert {'maintenance_schedule_id', 'maintenance_due_key'} <= columns
        assert connection.execute(sa.text('SELECT title FROM reminders')).scalar() == 'MOT'
        migration.downgrade()
        columns = {c['name'] for c in sa.inspect(connection).get_columns('reminders')}
        assert 'maintenance_schedule_id' not in columns
        assert connection.execute(sa.text('SELECT title FROM reminders')).scalar() == 'MOT'
