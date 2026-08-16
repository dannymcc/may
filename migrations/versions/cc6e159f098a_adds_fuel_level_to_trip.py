"""adds fuel level to trip and fuel logs

Revision ID: cc6e159f098a
Revises: e5f6a7b8c9d0
Create Date: 2026-08-03 21:46:57.015964

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cc6e159f098a'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.add_column(sa.Column('start_fuel_level', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('end_fuel_level', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.drop_column('start_fuel_level')
        batch_op.drop_column('end_fuel_level')
