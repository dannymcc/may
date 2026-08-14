"""Add CalDAV facade tables

Creates the four tables behind app/caldav:

* caldav_collections -- calendars owned by a May user
* caldav_objects     -- index of every CalDAV resource (with tombstones)
* caldav_versions    -- append-only history, one row per write
* caldav_sidecar     -- fields iCalendar cannot carry, keyed by UID

Revision ID: a1c0da7b0001
Revises: 85b42a298ff2
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

revision = 'a1c0da7b0001'
down_revision = '85b42a298ff2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'caldav_collections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('backing_kind', sa.String(length=32), nullable=False,
                  server_default='opaque'),
        sa.Column('component', sa.String(length=16), nullable=False,
                  server_default='VEVENT'),
        sa.Column('props', sa.JSON(), nullable=False),
        sa.Column('sync_seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_caldav_collection_user_name'),
    )
    with op.batch_alter_table('caldav_collections') as batch:
        batch.create_index('ix_caldav_collections_user_id', ['user_id'])

    op.create_table(
        'caldav_objects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collection_id', sa.Integer(), nullable=False),
        sa.Column('href', sa.String(length=255), nullable=False),
        sa.Column('uid', sa.String(length=255), nullable=False),
        sa.Column('recurrence_id', sa.String(length=64), nullable=False,
                  server_default=''),
        sa.Column('component', sa.String(length=16), nullable=False,
                  server_default='VEVENT'),
        sa.Column('backing_kind', sa.String(length=32), nullable=False,
                  server_default='opaque'),
        sa.Column('backing_id', sa.Integer(), nullable=True),
        sa.Column('raw_ics', sa.Text(), nullable=True),
        sa.Column('etag', sa.String(length=80), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('changed_seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['collection_id'], ['caldav_collections.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('collection_id', 'href', name='uq_caldav_object_href'),
    )
    with op.batch_alter_table('caldav_objects') as batch:
        batch.create_index('ix_caldav_objects_collection_id', ['collection_id'])
        batch.create_index('ix_caldav_objects_uid', ['uid'])
        batch.create_index('ix_caldav_objects_backing_id', ['backing_id'])
        # Drives sync-collection: "everything changed since token N".
        batch.create_index('ix_caldav_object_changed', ['collection_id', 'changed_seq'])

    op.create_table(
        'caldav_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('object_id', sa.Integer(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('operation', sa.String(length=16), nullable=False),
        sa.Column('raw_ics', sa.Text(), nullable=True),
        sa.Column('etag', sa.String(length=80), nullable=True),
        sa.Column('author', sa.String(length=255), nullable=True),
        sa.Column('author_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['object_id'], ['caldav_objects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('object_id', 'seq', name='uq_caldav_version_seq'),
    )
    with op.batch_alter_table('caldav_versions') as batch:
        batch.create_index('ix_caldav_versions_object_id', ['object_id'])

    op.create_table(
        'caldav_sidecar',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('uid', sa.String(length=255), nullable=False),
        sa.Column('recurrence_id', sa.String(length=64), nullable=False,
                  server_default=''),
        sa.Column('estimate_minutes', sa.Integer(), nullable=True),
        sa.Column('actual_minutes', sa.Integer(), nullable=True),
        sa.Column('reschedule_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('slip_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('touch_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('first_due_at', sa.DateTime(), nullable=True),
        sa.Column('last_due_at', sa.DateTime(), nullable=True),
        sa.Column('last_touched_at', sa.DateTime(), nullable=True),
        sa.Column('energy', sa.String(length=16), nullable=True),
        sa.Column('contexts', sa.JSON(), nullable=False),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('source_ref', sa.String(length=255), nullable=True),
        sa.Column('source_system', sa.String(length=64), nullable=True),
        sa.Column('blocked_by', sa.JSON(), nullable=False),
        sa.Column('blocks', sa.JSON(), nullable=False),
        sa.Column('derived', sa.JSON(), nullable=False),
        sa.Column('locked_fields', sa.JSON(), nullable=False),
        sa.Column('enriched_digest', sa.String(length=64), nullable=True),
        sa.Column('enriched_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'uid', 'recurrence_id',
                            name='uq_caldav_sidecar_uid'),
    )
    with op.batch_alter_table('caldav_sidecar') as batch:
        batch.create_index('ix_caldav_sidecar_user_id', ['user_id'])
        batch.create_index('ix_caldav_sidecar_uid', ['uid'])


def downgrade():
    op.drop_table('caldav_sidecar')
    op.drop_table('caldav_versions')
    op.drop_table('caldav_objects')
    op.drop_table('caldav_collections')
