"""add sales_tax to fuel_logs

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'fuel_logs' not in inspector.get_table_names():
        return
    existing_cols = [col['name'] for col in inspector.get_columns('fuel_logs')]
    if 'sales_tax' in existing_cols:
        return

    with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sales_tax', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
        batch_op.drop_column('sales_tax')
