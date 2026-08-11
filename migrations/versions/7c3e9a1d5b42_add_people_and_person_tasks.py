"""add people and person_tasks tables, link reminders and calendar events

Introduces PEOPLE as a first-class entity alongside vehicles. A reminder or
calendar event now belongs to either a vehicle or a person, so reminders.
vehicle_id becomes nullable and both tables gain a nullable person_id.

Revision ID: 7c3e9a1d5b42
Revises: 3d5ffcb447c9
Create Date: 2026-08-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '7c3e9a1d5b42'
down_revision = '3d5ffcb447c9'
branch_labels = None
depends_on = None


def _index_names(bind, table_name):
    """Names of the indexes currently on a table, or None if the table is absent."""
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return None
    return {index['name'] for index in inspector.get_indexes(table_name)}


def _create_index_if_missing(bind, index_name, table_name, columns):
    """Create an index only when it is not already there.

    ``db.create_all()`` in create_app runs before ``flask db upgrade``, so the
    people tables usually exist by the time this migration runs and the
    table-creation branches below are skipped. Index creation therefore has to
    be checked separately or the indexes would never be created at all.
    """
    existing = _index_names(bind, table_name)
    if existing is not None and index_name not in existing:
        op.create_index(index_name, table_name, columns)


def _drop_index_if_present(bind, index_name, table_name):
    """Drop an index only when it exists, so downgrade is not order-dependent."""
    existing = _index_names(bind, table_name)
    if existing is not None and index_name in existing:
        op.drop_index(index_name, table_name=table_name)


def _has_constraint(bind, table_name, constraint_name):
    """True when a named foreign key is actually present on the table.

    The project sets no SQLAlchemy naming convention, so a person_id foreign key
    added by ``db.create_all()`` or by the app's own schema recovery is emitted
    unnamed. ``drop_constraint`` on a name that was never assigned raises, so
    only drop what reflection can see.
    """
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(
        fk.get('name') == constraint_name
        for fk in inspector.get_foreign_keys(table_name)
    )


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = inspector.get_table_names()

    if 'people' not in table_names:
        op.create_table(
            'people',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('owner_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('relationship_type', sa.String(length=20), nullable=False, server_default='coworker'),
            sa.Column('email', sa.String(length=120), nullable=True),
            sa.Column('phone', sa.String(length=40), nullable=True),
            sa.Column('organization', sa.String(length=120), nullable=True),
            sa.Column('role_title', sa.String(length=120), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('image_filename', sa.String(length=255), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
            sa.Column('is_shared', sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    _create_index_if_missing(bind, 'ix_people_owner_id', 'people', ['owner_id'])

    table_names = inspect(bind).get_table_names()
    if 'person_tasks' not in table_names:
        op.create_table(
            'person_tasks',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('person_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='todo'),
            sa.Column('priority', sa.String(length=20), nullable=True, server_default='normal'),
            sa.Column('due_date', sa.Date(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['person_id'], ['people.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    _create_index_if_missing(bind, 'ix_person_tasks_person_id', 'person_tasks', ['person_id'])
    _create_index_if_missing(bind, 'ix_person_tasks_user_id', 'person_tasks', ['user_id'])

    if 'users' in table_names:
        user_cols = [col['name'] for col in inspector.get_columns('users')]
        if 'show_menu_people' not in user_cols:
            with op.batch_alter_table('users', schema=None) as batch_op:
                batch_op.add_column(sa.Column('show_menu_people', sa.Boolean(), nullable=True, server_default=sa.true()))

    if 'reminders' in table_names:
        reminder_cols = {col['name']: col for col in inspector.get_columns('reminders')}
        add_person = 'person_id' not in reminder_cols
        vehicle_col = reminder_cols.get('vehicle_id')
        relax_vehicle = vehicle_col is not None and vehicle_col.get('nullable') is not True
        if add_person or relax_vehicle:
            with op.batch_alter_table('reminders', schema=None) as batch_op:
                if add_person:
                    batch_op.add_column(sa.Column('person_id', sa.Integer(), nullable=True))
                    batch_op.create_foreign_key('fk_reminders_person', 'people', ['person_id'], ['id'])
                if relax_vehicle:
                    batch_op.alter_column('vehicle_id', existing_type=sa.Integer(), nullable=True)

    if 'calendar_events' in table_names:
        event_cols = [col['name'] for col in inspector.get_columns('calendar_events')]
        if 'person_id' not in event_cols:
            with op.batch_alter_table('calendar_events', schema=None) as batch_op:
                batch_op.add_column(sa.Column('person_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_calendar_events_person', 'people', ['person_id'], ['id'])
        _create_index_if_missing(bind, 'ix_calendar_events_person_id', 'calendar_events', ['person_id'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = inspector.get_table_names()

    if 'calendar_events' in table_names:
        event_cols = [col['name'] for col in inspector.get_columns('calendar_events')]
        if 'person_id' in event_cols:
            _drop_index_if_present(bind, 'ix_calendar_events_person_id', 'calendar_events')
            drop_event_fk = _has_constraint(bind, 'calendar_events', 'fk_calendar_events_person')
            with op.batch_alter_table('calendar_events', schema=None) as batch_op:
                if drop_event_fk:
                    batch_op.drop_constraint('fk_calendar_events_person', type_='foreignkey')
                batch_op.drop_column('person_id')

    if 'reminders' in table_names:
        # Person reminders have no vehicle and cannot survive vehicle_id going
        # back to NOT NULL — drop them rather than fail on the constraint.
        bind.execute(sa.text('DELETE FROM reminders WHERE vehicle_id IS NULL'))
        reminder_cols = [col['name'] for col in inspector.get_columns('reminders')]
        drop_reminder_fk = _has_constraint(bind, 'reminders', 'fk_reminders_person')
        with op.batch_alter_table('reminders', schema=None) as batch_op:
            if 'person_id' in reminder_cols:
                if drop_reminder_fk:
                    batch_op.drop_constraint('fk_reminders_person', type_='foreignkey')
                batch_op.drop_column('person_id')
            batch_op.alter_column('vehicle_id', existing_type=sa.Integer(), nullable=False)

    if 'users' in table_names:
        user_cols = [col['name'] for col in inspector.get_columns('users')]
        if 'show_menu_people' in user_cols:
            with op.batch_alter_table('users', schema=None) as batch_op:
                batch_op.drop_column('show_menu_people')

    if 'person_tasks' in table_names:
        _drop_index_if_present(bind, 'ix_person_tasks_user_id', 'person_tasks')
        _drop_index_if_present(bind, 'ix_person_tasks_person_id', 'person_tasks')
        op.drop_table('person_tasks')

    if 'people' in table_names:
        _drop_index_if_present(bind, 'ix_people_owner_id', 'people')
        op.drop_table('people')
