"""Add opt-in net cost per distance display preference."""
from alembic import op
import sqlalchemy as sa

revision = 'a7c9e2f4b610'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    if 'show_net_cost_per_distance' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')}:
        with op.batch_alter_table('users') as batch:
            batch.add_column(sa.Column('show_net_cost_per_distance', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('show_net_cost_per_distance')
