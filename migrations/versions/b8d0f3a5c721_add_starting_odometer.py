"""Add an optional vehicle starting odometer without altering existing totals."""
from alembic import op
import sqlalchemy as sa
revision = 'b8d0f3a5c721'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    """Add a nullable baseline, accommodating startup schema bootstrap."""
    if 'starting_odometer' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('vehicles')}:
        with op.batch_alter_table('vehicles') as batch:
            batch.add_column(sa.Column('starting_odometer', sa.Float(), nullable=True))


def downgrade():
    """Remove the baseline while preserving vehicle records."""
    with op.batch_alter_table('vehicles') as batch:
        batch.drop_column('starting_odometer')
