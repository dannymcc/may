"""Regression tests for the model-driven schema recovery.

Issue #166: a pre-Flask-Migrate database that's missing User columns the
current model defines must be repaired automatically when the container
starts. The previous hardcoded list missed columns added after v0.20.0;
this test pins the recovery to the actual model so future column additions
do not silently regress upgrades.
"""
import sqlite3
import tempfile
from pathlib import Path

from app import (
    _add_column_clause,
    _run_schema_migrations,
    _scalar_default_sql,
    create_app,
    db,
)
from app.models import User


class _TempDBConfig:
    TESTING = True
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SERVER_NAME = 'localhost'
    SECRET_KEY = 'test-secret'
    UPLOAD_FOLDER = '/tmp/may_test_uploads'

    def __init__(self, db_path):
        self.SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'


def _seed_legacy_db(path):
    """Build a stripped-down v0.18-shaped DB that's missing recent columns."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
          id INTEGER PRIMARY KEY,
          username VARCHAR(64) UNIQUE NOT NULL,
          email VARCHAR(120) UNIQUE NOT NULL,
          password_hash VARCHAR(256) NOT NULL,
          is_admin BOOLEAN DEFAULT 0,
          created_at DATETIME,
          language VARCHAR(10) DEFAULT 'en'
        );
        INSERT INTO users(username,email,password_hash) VALUES ('astrmn','a@b.c','x');
        CREATE TABLE vehicles (
          id INTEGER PRIMARY KEY,
          owner_id INTEGER NOT NULL,
          name VARCHAR(100) NOT NULL,
          vehicle_type VARCHAR(20) NOT NULL,
          fuel_type VARCHAR(20) DEFAULT 'petrol',
          is_active BOOLEAN DEFAULT 1,
          created_at DATETIME
        );
        CREATE TABLE fuel_stations (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL,
          name VARCHAR(100) NOT NULL,
          brand VARCHAR(50),
          postcode VARCHAR(20),
          created_at DATETIME
        );
        """
    )
    conn.commit()
    conn.close()


def test_legacy_db_recovers_missing_user_columns(tmp_path):
    """A DB missing default_vehicle_id, show_menu_*, etc. must be repaired
    so User.query stops blowing up on worker boot (issue #166)."""
    import os
    os.makedirs('/tmp/may_test_uploads', exist_ok=True)

    db_path = tmp_path / 'legacy.db'
    _seed_legacy_db(str(db_path))

    app = create_app(_TempDBConfig(str(db_path)))
    with app.app_context():
        # Spot-check the columns that issue #166 surfaced as missing.
        from sqlalchemy import inspect
        cols = {c['name'] for c in inspect(db.engine).get_columns('users')}
        assert 'default_vehicle_id' in cols
        assert 'show_menu_vehicles' in cols
        assert 'show_quick_entry' in cols
        assert 'api_key' in cols
        assert 'start_page' in cols

        # And the actual symptom: User.query no longer blows up.
        u = User.query.first()
        assert u.username == 'astrmn'
        assert u.show_menu_vehicles is True  # boolean default applied
        assert u.start_page == 'dashboard'  # string default applied
        assert u.show_quick_entry is False
        assert u.default_vehicle_id is None


def test_legacy_db_gains_multi_column_indexes(tmp_path):
    """Issue #155: the station price-source columns come with a composite
    unique index, which the per-column recovery pass cannot create."""
    import os
    os.makedirs('/tmp/may_test_uploads', exist_ok=True)

    db_path = tmp_path / 'legacy_stations.db'
    _seed_legacy_db(str(db_path))

    app = create_app(_TempDBConfig(str(db_path)))
    with app.app_context():
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        cols = {c['name'] for c in inspector.get_columns('fuel_stations')}
        assert {'price_source', 'external_id'} <= cols

        indexes = {i['name']: i for i in inspector.get_indexes('fuel_stations')}
        index = indexes.get('ix_fuel_stations_source_external_id')
        assert index is not None
        assert index['unique']

        db.session.remove()
        db.engine.dispose()


def test_run_schema_migrations_is_idempotent(tmp_path):
    """Running the recovery twice must not log warnings or fail."""
    import os
    os.makedirs('/tmp/may_test_uploads', exist_ok=True)
    db_path = tmp_path / 'idempotent.db'
    _seed_legacy_db(str(db_path))

    app = create_app(_TempDBConfig(str(db_path)))
    with app.app_context():
        # Second run should be a no-op — every column is already present.
        _run_schema_migrations(app)
        from sqlalchemy import inspect
        cols_before = inspect(db.engine).get_columns('users')
        _run_schema_migrations(app)
        cols_after = inspect(db.engine).get_columns('users')
        assert [c['name'] for c in cols_before] == [c['name'] for c in cols_after]


def test_scalar_default_sql_handles_supported_types():
    """Defaults are translated into SQL literals the right way."""
    from sqlalchemy import Column, Integer, String, Boolean

    bool_default = Column('flag', Boolean, default=True)
    bool_default_false = Column('flag', Boolean, default=False)
    str_default = Column('s', String, default="hello 'world'")
    int_default = Column('n', Integer, default=42)
    callable_default = Column('t', String, default=lambda: 'now')
    no_default = Column('n', Integer)

    assert _scalar_default_sql(bool_default) == '1'
    assert _scalar_default_sql(bool_default_false) == '0'
    assert _scalar_default_sql(str_default) == "'hello ''world'''"
    assert _scalar_default_sql(int_default) == '42'
    assert _scalar_default_sql(callable_default) is None
    assert _scalar_default_sql(no_default) is None


def test_add_column_clause_emits_fk_and_default():
    """The synthesised ADD COLUMN clause covers the cases issue #166 needed."""
    from sqlalchemy.dialects import sqlite
    dialect = sqlite.dialect()

    # Mirror the column definition that issue #166 hinged on.
    fk_col = User.__table__.columns['default_vehicle_id']
    clause = _add_column_clause(fk_col, dialect)
    assert 'default_vehicle_id' in clause
    assert 'INTEGER' in clause
    assert 'REFERENCES vehicles(id)' in clause

    # A column with a string default emits DEFAULT '...'.
    start_page = User.__table__.columns['start_page']
    clause = _add_column_clause(start_page, dialect)
    assert "DEFAULT 'dashboard'" in clause


def test_fresh_db_stamps_head_and_replay_survives(tmp_path):
    """Issue #278: fresh installs must not replay migrations over create_all.

    A brand-new database gets the complete current schema from create_all(),
    so it must be stamped at alembic head — replaying historical migrations
    on top used to crash in 42b26bf6d488's batch rebuild once a column
    existed after is_shared. Even a database already stuck in the bad state
    (full schema, stamped at the old checkpoint) must now upgrade cleanly.
    """
    from sqlalchemy import text
    from flask_migrate import upgrade as alembic_upgrade

    db_path = tmp_path / 'fresh.db'
    app = create_app(_TempDBConfig(db_path))
    with app.app_context():
        with db.engine.begin() as conn:
            rev = conn.execute(
                text('SELECT version_num FROM alembic_version')
            ).scalar()
        # Resolve the head from Alembic rather than a filename, so adding a
        # migration does not break this test.
        from alembic.script import ScriptDirectory
        head = ScriptDirectory('migrations').get_current_head()
        assert rev == head, f'fresh db stamped {rev}, expected head {head}'

        # Simulate the pre-fix broken state and prove the replay now survives.
        with db.engine.begin() as conn:
            conn.execute(text('DELETE FROM alembic_version'))
            conn.execute(text("INSERT INTO alembic_version VALUES ('b2c3d4e5f6a7')"))
        alembic_upgrade()
        with db.engine.begin() as conn:
            rev = conn.execute(
                text('SELECT version_num FROM alembic_version')
            ).scalar()
        assert rev == head
        db.session.remove()
        db.engine.dispose()
