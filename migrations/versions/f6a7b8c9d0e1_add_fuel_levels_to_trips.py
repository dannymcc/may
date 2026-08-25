"""Add start_fuel_level and end_fuel_level to trips (#273)

Records the fuel gauge reading at each end of a trip as a percentage of a
full tank, so fuel burnt can be approximated against the vehicle's tank
capacity without waiting for the next fill-up.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d1
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'trips' not in inspector.get_table_names():
        return
    cols = [c['name'] for c in inspector.get_columns('trips')]

    with op.batch_alter_table('trips', schema=None) as batch_op:
        if 'start_fuel_level' not in cols:
            batch_op.add_column(sa.Column('start_fuel_level', sa.Float(), nullable=True))
        if 'end_fuel_level' not in cols:
            batch_op.add_column(sa.Column('end_fuel_level', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.drop_column('end_fuel_level')
        batch_op.drop_column('start_fuel_level')
