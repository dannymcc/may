"""Preserve service history, tire axles and confirmed fuel readings.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d6'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'odometer_confirmed' not in {c['name'] for c in inspector.get_columns('fuel_logs')}:
        with op.batch_alter_table('fuel_logs') as batch:
            batch.add_column(sa.Column('odometer_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'axle' not in {c['name'] for c in inspector.get_columns('tire_fitments')}:
        with op.batch_alter_table('tire_fitments') as batch:
            batch.add_column(sa.Column('axle', sa.String(5), nullable=False, server_default='all'))
    if 'maintenance_events' not in inspector.get_table_names():
        op.create_table(
            'maintenance_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('schedule_id', sa.Integer(), sa.ForeignKey('maintenance_schedules.id', ondelete='SET NULL')),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('maintenance_type', sa.String(50), nullable=False),
            sa.Column('performed_date', sa.Date()),
            sa.Column('odometer', sa.Float()),
            sa.Column('notes', sa.Text()),
            sa.Column('created_at', sa.DateTime()),
        )
    op.execute(sa.text('''
INSERT INTO maintenance_events
(vehicle_id, user_id, schedule_id, name, maintenance_type, performed_date, odometer, notes, created_at)
SELECT s.vehicle_id, s.user_id, s.id, s.name, s.maintenance_type,
       s.last_performed_date, s.last_performed_odometer, s.description, CURRENT_TIMESTAMP
FROM maintenance_schedules s
WHERE (s.last_performed_date IS NOT NULL OR s.last_performed_odometer IS NOT NULL)
  AND NOT EXISTS (SELECT 1 FROM maintenance_events e WHERE e.schedule_id = s.id)
'''))


def downgrade():
    op.drop_table('maintenance_events')
    with op.batch_alter_table('tire_fitments') as batch:
        batch.drop_column('axle')
    with op.batch_alter_table('fuel_logs') as batch:
        batch.drop_column('odometer_confirmed')
