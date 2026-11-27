"""Move the tread display unit into account preferences."""
from alembic import op
import sqlalchemy as sa

revision = 'ca82d2410ff3'
down_revision = 'd7607b3e02d1'
branch_labels = None
depends_on = None


def upgrade():
    # The migration CLI may start May's model-based schema recovery first.
    columns = sa.inspect(op.get_bind()).get_columns('users')
    if not any(column['name'] == 'tread_unit' for column in columns):
        op.add_column('users', sa.Column('tread_unit', sa.String(8),
                                        nullable=False, server_default='mm'))


def downgrade():
    op.drop_column('users', 'tread_unit')
