"""Add notification_sent to person_tasks so due tasks notify once per due date

Revision ID: f768be7719bd
Revises: 7c3e9a1d5b42
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'f768be7719bd'
down_revision = '7c3e9a1d5b42'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    cols = [c['name'] for c in sa.inspect(conn).get_columns('person_tasks')]
    if 'notification_sent' not in cols:
        # server_default keeps the backfill portable — an integer-literal
        # UPDATE would fail on PostgreSQL's strict boolean typing
        op.add_column('person_tasks', sa.Column('notification_sent', sa.Boolean(),
                                                nullable=True, server_default=sa.false()))


def downgrade():
    op.drop_column('person_tasks', 'notification_sent')
