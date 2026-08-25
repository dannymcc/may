"""Add role to users (#285)

Gives each account a role below the admin flag: editor (full access, the
default and the historic behaviour), contributor (fuel and charging only) or
viewer (read-only).

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'users' not in inspector.get_table_names():
        return
    cols = [c['name'] for c in inspector.get_columns('users')]
    if 'role' in cols:
        return

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=20), nullable=True))

    # Existing accounts keep the access they had.
    op.execute("UPDATE users SET role = 'editor' WHERE role IS NULL")


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('role')
