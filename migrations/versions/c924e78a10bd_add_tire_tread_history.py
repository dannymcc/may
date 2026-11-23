"""Add physical tire identities, tread measurements and optional thresholds (#424).

Revision ID: c924e78a10bd
Revises: b8d0f3a5c721
"""
from alembic import op
import sqlalchemy as sa

revision = 'c924e78a10bd'
down_revision = 'b8d0f3a5c721'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c['name'] for c in inspector.get_columns('tire_sets')}
    with op.batch_alter_table('tire_sets') as batch:
        for name in ('tread_warning_mm', 'tread_replace_mm'):
            if name not in columns:
                batch.add_column(sa.Column(name, sa.Float(), nullable=True))
    if 'tires' not in inspector.get_table_names():
        op.create_table('tires',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tire_set_id', sa.Integer(), sa.ForeignKey('tire_sets.id'), nullable=False),
            sa.Column('identity', sa.String(36), nullable=False),
            sa.Column('label', sa.String(100), nullable=False),
            sa.UniqueConstraint('tire_set_id', 'label'),
            sa.UniqueConstraint('tire_set_id', 'identity'))
    if 'tire_measurements' not in inspector.get_table_names():
        op.create_table('tire_measurements',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tire_id', sa.Integer(), sa.ForeignKey('tires.id'), nullable=False),
            sa.Column('measured_date', sa.Date(), nullable=False),
            sa.Column('depth_mm', sa.Float(), nullable=False),
            sa.Column('odometer', sa.Float()),
            sa.Column('position', sa.String(20), nullable=False),
            sa.CheckConstraint('depth_mm >= 0 AND depth_mm <= 100', name='valid_tread_depth'),
            sa.CheckConstraint('odometer IS NULL OR odometer >= 0', name='valid_tread_odometer'))

    if 'ix_tire_measurements_tire_id' not in {i['name'] for i in sa.inspect(op.get_bind()).get_indexes('tire_measurements')}:
        op.create_index('ix_tire_measurements_tire_id', 'tire_measurements', ['tire_id'])


def downgrade():
    op.drop_table('tire_measurements')
    op.drop_table('tires')
    with op.batch_alter_table('tire_sets') as batch:
        batch.drop_column('tread_replace_mm')
        batch.drop_column('tread_warning_mm')
