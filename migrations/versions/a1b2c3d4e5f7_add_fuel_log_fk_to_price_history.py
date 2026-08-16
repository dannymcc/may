"""Add fuel_log_id FK to fuel_price_history and backfill (#254)

Price-history rows were matched back to fuel logs heuristically by
(user, date, price_per_unit), which can pick the wrong row when two logs
share a day and price. The FK makes the association exact. Nullable:
legacy rows that cannot be matched unambiguously, and manually recorded
station prices, keep NULL.

Revision ID: a1b2c3d4e5f7
Revises: e5f6a7b8c9d0
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    cols = [c['name'] for c in sa.inspect(conn).get_columns('fuel_price_history')]
    if 'fuel_log_id' not in cols:
        op.add_column(
            'fuel_price_history',
            sa.Column('fuel_log_id', sa.Integer(), sa.ForeignKey('fuel_logs.id'), nullable=True),
        )

    # Best-effort backfill: link each unlinked price-history row to its fuel
    # log only when exactly one log matches on (user, date, price). Ambiguous
    # rows stay NULL rather than risk linking the wrong log.
    conn.execute(sa.text("""
        UPDATE fuel_price_history
        SET fuel_log_id = (
            SELECT fl.id FROM fuel_logs fl
            WHERE fl.user_id = fuel_price_history.user_id
              AND fl.date = fuel_price_history.date
              AND fl.price_per_unit = fuel_price_history.price_per_unit
        )
        WHERE fuel_log_id IS NULL
          AND (
            SELECT COUNT(*) FROM fuel_logs fl
            WHERE fl.user_id = fuel_price_history.user_id
              AND fl.date = fuel_price_history.date
              AND fl.price_per_unit = fuel_price_history.price_per_unit
          ) = 1
    """))


def downgrade():
    op.drop_column('fuel_price_history', 'fuel_log_id')
