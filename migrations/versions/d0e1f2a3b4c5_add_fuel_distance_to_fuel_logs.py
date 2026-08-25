"""add fuel_distance to fuel_logs

Revision ID: d0e1f2a3b4c5
Revises: f2a3b4c5d6e7
Create Date: 2026-08-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd0e1f2a3b4c5'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = [c['name'] for c in inspector.get_columns('fuel_logs')]
    if 'fuel_distance' not in columns:
        with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
            batch_op.add_column(sa.Column('fuel_distance', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('fuel_logs', schema=None) as batch_op:
        batch_op.drop_column('fuel_distance')
