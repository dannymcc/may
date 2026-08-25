"""add engine-hour interval to maintenance schedules

Revision ID: f2a3b4c5d6e7
Revises: c9d0e1f2a3b4
Create Date: 2026-08-25 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2a3b4c5d6e7'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'maintenance_schedules' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('maintenance_schedules')]
    if 'interval_hours' in columns:
        return

    with op.batch_alter_table('maintenance_schedules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('interval_hours', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('maintenance_schedules', schema=None) as batch_op:
        batch_op.drop_column('interval_hours')
