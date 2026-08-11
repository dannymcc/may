"""Add person_vehicle_links associating people with vehicles by role

Revision ID: 85b42a298ff2
Revises: 7e590907d476
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa

revision = '85b42a298ff2'
down_revision = '7e590907d476'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # db.create_all() in create_app runs before flask db upgrade, so the table
    # usually exists already — only create it when it is actually missing
    if 'person_vehicle_links' not in sa.inspect(conn).get_table_names():
        op.create_table(
            'person_vehicle_links',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('person_id', sa.Integer(), nullable=False),
            sa.Column('vehicle_id', sa.Integer(), nullable=False),
            sa.Column('role', sa.String(length=30), nullable=False),
            sa.Column('notes', sa.String(length=200), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['person_id'], ['people.id']),
            sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('person_id', 'vehicle_id', 'role', name='uq_person_vehicle_role'),
        )


def downgrade():
    op.drop_table('person_vehicle_links')
