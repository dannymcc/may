"""add tire_sets and tire_fitments tables and show_menu_tires preference

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-23 21:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = inspector.get_table_names()

    if 'tire_sets' not in table_names:
        op.create_table(
            'tire_sets',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('vehicle_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('tire_type', sa.String(length=20), nullable=False),
            sa.Column('size', sa.String(length=50), nullable=True),
            sa.Column('purchase_date', sa.Date(), nullable=True),
            sa.Column('purchase_odometer', sa.Float(), nullable=True),
            sa.Column('cost', sa.Float(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('is_retired', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'tire_fitments' not in table_names:
        op.create_table(
            'tire_fitments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('tire_set_id', sa.Integer(), nullable=False),
            sa.Column('fitted_date', sa.Date(), nullable=False),
            sa.Column('fitted_odometer', sa.Float(), nullable=False),
            sa.Column('removed_date', sa.Date(), nullable=True),
            sa.Column('removed_odometer', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['tire_set_id'], ['tire_sets.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'users' in table_names:
        user_cols = [col['name'] for col in inspector.get_columns('users')]
        if 'show_menu_tires' not in user_cols:
            with op.batch_alter_table('users', schema=None) as batch_op:
                batch_op.add_column(sa.Column('show_menu_tires', sa.Boolean(), nullable=True, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('show_menu_tires')
    op.drop_table('tire_fitments')
    op.drop_table('tire_sets')
