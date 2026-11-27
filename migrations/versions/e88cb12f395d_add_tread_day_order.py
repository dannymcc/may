"""Preserve the order of tread readings taken on the same date."""
from alembic import op
import sqlalchemy as sa

revision = 'e88cb12f395d'
down_revision = 'ca82d2410ff3'
branch_labels = None
depends_on = None


def upgrade():
    # The migration CLI may have already started May's schema recovery.
    columns = sa.inspect(op.get_bind()).get_columns('tire_measurements')
    if not any(column['name'] == 'day_order' for column in columns):
        op.add_column('tire_measurements', sa.Column('day_order', sa.Integer()))


def downgrade():
    op.drop_column('tire_measurements', 'day_order')
