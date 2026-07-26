"""Add vehicle_notes table and show_menu_notes preference

Revision ID: dae71d6eccf1
Revises: 613be8af4376
Create Date: 2026-07-26 11:30:59.418074

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dae71d6eccf1'
down_revision = '613be8af4376'
branch_labels = None
depends_on = None


def upgrade():
    # Create vehicle_notes table if it does not exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_notes (
            id INTEGER NOT NULL PRIMARY KEY,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            title VARCHAR(200) NOT NULL,
            content TEXT,
            is_pinned BOOLEAN DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )
    """)

    # Add show_menu_notes column to users if it does not exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    user_columns = [c['name'] for c in inspector.get_columns('users')]
    if 'show_menu_notes' not in user_columns:
        op.add_column('users', sa.Column('show_menu_notes', sa.Boolean(), nullable=True))
        op.execute("UPDATE users SET show_menu_notes = 1 WHERE show_menu_notes IS NULL")
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.alter_column('show_menu_notes', existing_type=sa.Boolean(), nullable=False)


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    tables = inspector.get_table_names()
    if 'vehicle_notes' in tables:
        op.drop_table('vehicle_notes')

    user_columns = [c['name'] for c in inspector.get_columns('users')]
    if 'show_menu_notes' in user_columns:
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('show_menu_notes')
