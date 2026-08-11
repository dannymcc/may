"""Add recurrence unit and interval to person_tasks

Completing a repeating task creates the next occurrence, mirroring
reminder recurrence (unit + interval pair).

Revision ID: 7e590907d476
Revises: f768be7719bd
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa

revision = '7e590907d476'
down_revision = 'f768be7719bd'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    cols = [c['name'] for c in sa.inspect(conn).get_columns('person_tasks')]
    if 'recurrence' not in cols:
        op.add_column('person_tasks', sa.Column('recurrence', sa.String(length=20), nullable=True))
        op.execute("UPDATE person_tasks SET recurrence = 'none' WHERE recurrence IS NULL")
    if 'recurrence_interval' not in cols:
        op.add_column('person_tasks', sa.Column('recurrence_interval', sa.Integer(), nullable=True))
        op.execute("UPDATE person_tasks SET recurrence_interval = 1 WHERE recurrence_interval IS NULL")


def downgrade():
    op.drop_column('person_tasks', 'recurrence_interval')
    op.drop_column('person_tasks', 'recurrence')
