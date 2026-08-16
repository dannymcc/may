"""Add ntfy_token to users for authenticated ntfy servers (#90)

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b9'
down_revision = 'b2c3d4e5f6a8'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    cols = [c['name'] for c in sa.inspect(conn).get_columns('users')]
    if 'ntfy_token' not in cols:
        op.add_column('users', sa.Column('ntfy_token', sa.String(length=200), nullable=True))


def downgrade():
    op.drop_column('users', 'ntfy_token')
