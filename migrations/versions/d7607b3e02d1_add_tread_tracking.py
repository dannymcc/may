"""Add a per-set opt-in for tread measurements."""
from alembic import op
import sqlalchemy as sa

revision = 'd7607b3e02d1'
down_revision = 'c924e78a10bd'
branch_labels = None
depends_on = None


def upgrade():
    # Creating the Flask app for the migration CLI can already add model columns.
    columns = sa.inspect(op.get_bind()).get_columns('tire_sets')
    if not any(column['name'] == 'tread_tracking' for column in columns):
        op.add_column('tire_sets', sa.Column('tread_tracking', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('tire_sets', 'tread_tracking')
