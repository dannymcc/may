"""add calendar events and alarms

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-08 16:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '3d5ffcb447c9'
down_revision = 'd4e5f6a7b8c0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = inspector.get_table_names()

    if 'calendar_events' not in table_names:
        op.create_table(
            'calendar_events',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('vehicle_id', sa.Integer(), nullable=True),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('event_type', sa.String(length=50), nullable=False, server_default='custom'),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='confirmed'),
            sa.Column('start_at', sa.DateTime(), nullable=False),
            sa.Column('end_at', sa.DateTime(), nullable=True),
            sa.Column('all_day', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('timezone', sa.String(length=64), nullable=True, server_default='UTC'),
            sa.Column('location', sa.String(length=255), nullable=True),
            sa.Column('url', sa.String(length=500), nullable=True),
            sa.Column('recurrence_rule', sa.String(length=500), nullable=True),
            sa.Column('recurrence_until', sa.DateTime(), nullable=True),
            sa.Column('source_type', sa.String(length=50), nullable=True, server_default='manual'),
            sa.Column('source_id', sa.Integer(), nullable=True),
            sa.Column('external_uid', sa.String(length=255), nullable=True),
            sa.Column('external_calendar_url', sa.String(length=500), nullable=True),
            sa.Column('external_etag', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_calendar_events_user_id', 'calendar_events', ['user_id'])
        op.create_index('ix_calendar_events_vehicle_id', 'calendar_events', ['vehicle_id'])
        op.create_index('ix_calendar_events_start_at', 'calendar_events', ['start_at'])
        op.create_index('ix_calendar_events_external_uid', 'calendar_events', ['external_uid'])

    table_names = inspect(bind).get_table_names()
    if 'calendar_alarms' not in table_names:
        op.create_table(
            'calendar_alarms',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('event_id', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(length=20), nullable=False, server_default='display'),
            sa.Column('trigger_minutes_before', sa.Integer(), nullable=False, server_default='15'),
            sa.Column('summary', sa.String(length=200), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('attendee_email', sa.String(length=120), nullable=True),
            sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('notification_sent', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['event_id'], ['calendar_events.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_calendar_alarms_event_id', 'calendar_alarms', ['event_id'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = inspector.get_table_names()

    if 'calendar_alarms' in table_names:
        op.drop_index('ix_calendar_alarms_event_id', table_name='calendar_alarms')
        op.drop_table('calendar_alarms')
    if 'calendar_events' in table_names:
        op.drop_index('ix_calendar_events_external_uid', table_name='calendar_events')
        op.drop_index('ix_calendar_events_start_at', table_name='calendar_events')
        op.drop_index('ix_calendar_events_vehicle_id', table_name='calendar_events')
        op.drop_index('ix_calendar_events_user_id', table_name='calendar_events')
        op.drop_table('calendar_events')
