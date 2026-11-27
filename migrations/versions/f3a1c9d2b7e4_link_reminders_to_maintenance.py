"""Link automatic reminders to the maintenance schedule that created them."""
from alembic import op
import sqlalchemy as sa

revision = 'f3a1c9d2b7e4'
down_revision = 'e88cb12f395d'
branch_labels = None
depends_on = None


def upgrade():
    # The migration CLI may have already started May's schema recovery.
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('reminders')}
    with op.batch_alter_table('reminders') as batch:
        if 'maintenance_schedule_id' not in columns:
            batch.add_column(sa.Column('maintenance_schedule_id', sa.Integer()))
            batch.create_foreign_key('fk_reminders_maintenance_schedule', 'maintenance_schedules',
                                     ['maintenance_schedule_id'], ['id'], ondelete='SET NULL')
        if 'maintenance_due_key' not in columns:
            batch.add_column(sa.Column('maintenance_due_key', sa.String(64)))


def downgrade():
    with op.batch_alter_table('reminders') as batch:
        batch.drop_constraint('fk_reminders_maintenance_schedule', type_='foreignkey')
        batch.drop_column('maintenance_due_key')
        batch.drop_column('maintenance_schedule_id')
