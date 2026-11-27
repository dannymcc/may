"""Record the petrol grade (E10 or E5) of each fill-up (#268)."""
from alembic import op
import sqlalchemy as sa

revision = 'a7d4e2c8f913'
down_revision = 'f3a1c9d2b7e4'
branch_labels = None
depends_on = None


def upgrade():
    # The migration CLI may have already started May's schema recovery.
    columns = sa.inspect(op.get_bind()).get_columns('fuel_logs')
    if not any(column['name'] == 'fuel_grade' for column in columns):
        op.add_column('fuel_logs', sa.Column('fuel_grade', sa.String(10)))


def downgrade():
    with op.batch_alter_table('fuel_logs') as batch:
        batch.drop_column('fuel_grade')
