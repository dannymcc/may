"""Add default_trip_purpose to vehicles (#272)

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a8'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    cols = [c['name'] for c in sa.inspect(conn).get_columns('vehicles')]
    if 'default_trip_purpose' not in cols:
        op.add_column(
            'vehicles',
            sa.Column('default_trip_purpose', sa.String(length=20),
                      nullable=True, server_default='business'),
        )


def downgrade():
    op.drop_column('vehicles', 'default_trip_purpose')
