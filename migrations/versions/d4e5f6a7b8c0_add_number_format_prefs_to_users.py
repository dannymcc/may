"""Add thousand_separator and round_costs to users (#134)

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c0'
down_revision = 'c3d4e5f6a7b9'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    cols = [c['name'] for c in sa.inspect(conn).get_columns('users')]
    if 'thousand_separator' not in cols:
        op.add_column('users', sa.Column('thousand_separator', sa.String(length=10),
                                         nullable=True, server_default='none'))
    if 'round_costs' not in cols:
        op.add_column('users', sa.Column('round_costs', sa.Boolean(),
                                         nullable=True, server_default='0'))


def downgrade():
    op.drop_column('users', 'round_costs')
    op.drop_column('users', 'thousand_separator')
