"""Add price_source and external_id to fuel_stations (#155)

Gives saved stations a stable identity with a live price provider (the UK
fuel price scheme today, Tankerkönig next), so prices can be pulled by id
rather than re-guessed from postcodes and addresses on every run.

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d1'
down_revision = 'd4e5f6a7b8c0'
branch_labels = None
depends_on = None


INDEX_NAME = 'ix_fuel_stations_source_external_id'


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = [c['name'] for c in inspector.get_columns('fuel_stations')]

    if 'price_source' not in cols:
        op.add_column('fuel_stations',
                      sa.Column('price_source', sa.String(length=30), nullable=True))
    if 'external_id' not in cols:
        op.add_column('fuel_stations',
                      sa.Column('external_id', sa.String(length=64), nullable=True))

    indexes = [i['name'] for i in inspector.get_indexes('fuel_stations')]
    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            'fuel_stations',
            ['user_id', 'price_source', 'external_id'],
            unique=True,
        )


def downgrade():
    op.drop_index(INDEX_NAME, table_name='fuel_stations')
    op.drop_column('fuel_stations', 'external_id')
    op.drop_column('fuel_stations', 'price_source')
