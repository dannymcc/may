from flask import Flask, request, g
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_babel import Babel, gettext as _
from config import Config
from app.utils import first_day_of_week
import os
import secrets

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'
babel = Babel()
csrf = CSRFProtect()

# Supported languages
LANGUAGES = {
    'en': 'English',
    'ar': 'العربية',
    'cs': 'Čeština',
    'de': 'Deutsch',
    'es': 'Español',
    'fr': 'Français',
    'it': 'Italiano',
    'nl': 'Nederlands',
    'pt': 'Português',
    'pl': 'Polski',
    'ru': 'Русский',
    'sv': 'Svenska',
    'da': 'Dansk',
    'no': 'Norsk',
    'fi': 'Suomi',
    'tr': 'Türkçe',
    'ja': '日本語',
    'zh': '中文',
    'ko': '한국어'
}

DATE_FORMATS = {
    'DD/MM/YYYY': {
        'default': '%d/%m/%Y',
        'short': '%d %b',
        'long': '%d %B %Y',
        'datetime': '%d/%m/%Y %H:%M',
        'long_datetime': '%d %B %Y at %H:%M',
    },
    'MM/DD/YYYY': {
        'default': '%m/%d/%Y',
        'short': '%b %d',
        'long': '%B %d, %Y',
        'datetime': '%m/%d/%Y %H:%M',
        'long_datetime': '%B %d, %Y at %H:%M',
    },
    'YYYY-MM-DD': {
        'default': '%Y-%m-%d',
        'short': '%b %d',
        'long': '%Y-%m-%d',
        'datetime': '%Y-%m-%d %H:%M',
        'long_datetime': '%Y-%m-%d %H:%M',
    },
    'DD.MM.YYYY': {
        'default': '%d.%m.%Y',
        'short': '%d %b',
        'long': '%d %B %Y',
        'datetime': '%d.%m.%Y %H:%M',
        'long_datetime': '%d %B %Y at %H:%M',
    },
}


def _bootstrap_alembic_version(app):
    """Stamp alembic_version for databases that predate Flask-Migrate.

    Early versions of May created tables via db.create_all() without
    Flask-Migrate. When those users upgrade, `alembic_version` is either
    missing or empty, so `flask db upgrade` tries to replay migrations
    from scratch and fails on `duplicate column` errors. Columns that
    later migrations add therefore never land, and the app crashes
    at startup (see issues #132, #136).

    If we detect an established schema with no alembic revision recorded,
    stamp the most recent migration whose columns already exist so that
    subsequent `flask db upgrade` runs only apply genuinely new changes.
    """
    from sqlalchemy import text, inspect
    from flask_migrate import stamp

    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    if 'users' not in table_names or 'vehicles' not in table_names:
        return

    with db.engine.begin() as conn:
        if 'alembic_version' in table_names:
            current = conn.execute(
                text('SELECT version_num FROM alembic_version')
            ).scalar()
            if current:
                return

    user_cols = {c['name'] for c in inspector.get_columns('users')}
    vehicle_cols = {c['name'] for c in inspector.get_columns('vehicles')}

    if 'trip_templates' in table_names:
        target = 'b2c3d4e5f6a7'
    elif 'default_vehicle_id' in user_cols:
        target = 'a1b2c3d4e5f6'
    elif 'odometer_unit' in vehicle_cols:
        target = '613be8af4376'
    else:
        target = None

    if target is None:
        return

    try:
        stamp(revision=target)
        app.logger.info(f'Stamped alembic_version to {target} for pre-migration database')
    except Exception as e:
        app.logger.warning(f'Could not stamp alembic_version: {e}')


def _log_startup_banner(app):
    """Log version + alembic state once on boot.

    A short banner means a copy-paste of the container logs is enough to
    triage version-related upgrade bugs without having to ask the reporter
    for ``docker exec ... cat config.py``.
    """
    from sqlalchemy import inspect, text
    try:
        from config import Config
        version = getattr(Config, 'DISPLAY_VERSION', None) or getattr(Config, 'APP_VERSION', 'unknown')
    except Exception:
        version = 'unknown'

    alembic_rev = 'unset'
    try:
        inspector = inspect(db.engine)
        if 'alembic_version' in inspector.get_table_names():
            with db.engine.begin() as conn:
                alembic_rev = conn.execute(
                    text('SELECT version_num FROM alembic_version')
                ).scalar() or 'empty'
    except Exception as e:
        alembic_rev = f'error: {e}'

    app.logger.warning(f'May {version} starting (alembic_version={alembic_rev})')


def _scalar_default_sql(column):
    """Render a SQLAlchemy column's Python-side default as a SQL literal.

    Returns None when no scalar default is set, when the default is callable
    (e.g. ``datetime.utcnow``), or when the value is a type we cannot safely
    embed in DDL. Callable defaults are intentionally skipped: ``ALTER TABLE``
    fills existing rows once at column-creation time, so the captured value
    would be misleading anyway.
    """
    default = column.default
    if default is None or not getattr(default, 'is_scalar', False):
        return None
    arg = default.arg
    if isinstance(arg, bool):
        return '1' if arg else '0'
    if isinstance(arg, (int, float)):
        return str(arg)
    if isinstance(arg, str):
        return "'" + arg.replace("'", "''") + "'"
    return None


def _add_column_clause(column, dialect):
    """Build the body of an ``ALTER TABLE ... ADD COLUMN`` from a SQLAlchemy column.

    Drops any UNIQUE flag — SQLite refuses inline UNIQUE on ``ADD COLUMN`` and
    we recreate uniqueness as a separate index. ``NOT NULL`` is only emitted
    when there is also a scalar default; otherwise existing rows would
    instantly violate the constraint.
    """
    parts = [column.name, column.type.compile(dialect=dialect)]
    default_sql = _scalar_default_sql(column)
    if default_sql is not None:
        parts.append(f'DEFAULT {default_sql}')
        if not column.nullable:
            parts.append('NOT NULL')
    for fk in column.foreign_keys:
        ref_table, ref_col = fk.target_fullname.split('.', 1)
        parts.append(f'REFERENCES {ref_table}({ref_col})')
    return ' '.join(parts)


def _run_schema_migrations(app):
    """Add columns defined on the SQLAlchemy models but missing from existing tables.

    ``db.create_all()`` only creates missing tables — never alters existing
    ones — so when a model gains a new column the database it is pointed at
    keeps the old shape. This routine walks every table+column in
    ``db.metadata`` and issues an ``ALTER TABLE ... ADD COLUMN`` for each
    column the live database is missing. Unique constraints are added via a
    separate ``CREATE UNIQUE INDEX`` because SQLite rejects inline ``UNIQUE``
    on ``ALTER TABLE ADD COLUMN``.

    Failures are logged rather than raised: a single column we cannot apply
    cleanly (for example ``NOT NULL`` without a default on a populated table)
    must not block the rest of the schema from catching up. Issue #166 was a
    direct consequence of the previous hardcoded list missing newly-added
    User columns; the model-driven walk keeps recovery in lockstep with the
    models automatically.
    """
    from sqlalchemy import text, inspect

    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    dialect = db.engine.dialect

    with db.engine.begin() as conn:
        for table in db.metadata.tables.values():
            if table.name not in existing_tables:
                continue
            existing_cols = {col['name'] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                clause = _add_column_clause(column, dialect)
                try:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {clause}'))
                    app.logger.info(f'Added column {column.name} to {table.name}')
                except Exception as e:
                    app.logger.warning(
                        f'Could not add column {column.name} to {table.name}: {e}'
                    )

        # Re-inspect so we see indexes on freshly-added columns.
        inspector = inspect(db.engine)
        for table in db.metadata.tables.values():
            if table.name not in existing_tables:
                continue
            existing_indexes = {idx['name'] for idx in inspector.get_indexes(table.name)}
            for column in table.columns:
                if not (column.unique or column.index):
                    continue
                index_name = f'ix_{table.name}_{column.name}'
                if index_name in existing_indexes:
                    continue
                kind = 'UNIQUE INDEX' if column.unique else 'INDEX'
                try:
                    conn.execute(text(
                        f'CREATE {kind} {index_name} ON {table.name} ({column.name})'
                    ))
                    app.logger.info(f'Created {kind.lower()} {index_name}')
                except Exception as e:
                    app.logger.warning(
                        f'Could not create {kind.lower()} {index_name}: {e}'
                    )


def get_locale():
    """Select the best language for the user"""
    # If user is logged in and has a language preference, use it
    if current_user.is_authenticated and current_user.language:
        return current_user.language

    # Otherwise, try to match browser language
    return request.accept_languages.best_match(LANGUAGES.keys(), default='en')


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Render None as an empty string in all templates. Nullable model fields
    # (tank capacity, odometer, notes, ...) otherwise stringify to the literal
    # text "None" in value="" attributes, which then blocks form validation on
    # save (issues #217, #241).
    app.jinja_env.finalize = lambda value: '' if value is None else value

    # Babel configuration
    app.config['BABEL_DEFAULT_LOCALE'] = 'en'
    app.config['BABEL_SUPPORTED_LOCALES'] = list(LANGUAGES.keys())

    # Ensure data directories exist (the DB directory only applies to SQLite;
    # a server-based DATABASE_URL like postgresql:// has no local path, #239)
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///'):
        db_dir = os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '', 1))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    babel.init_app(app, locale_selector=get_locale)

    # Exempt API endpoints from CSRF (they use API key auth)
    from app.routes import api
    csrf.exempt(api.bp)

    from app.models import User, AppSettings

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Make languages and branding available in templates
    @app.context_processor
    def inject_globals():
        branding = AppSettings.get_all_branding()
        current_locale = str(get_locale() or 'en')
        return {
            'LANGUAGES': LANGUAGES,
            'CURRENT_LOCALE': current_locale,
            'FIRST_DAY_OF_WEEK': first_day_of_week(current_locale),
            'APP_NAME': branding.get('app_name', 'May'),
            'APP_TAGLINE': branding.get('app_tagline', 'Vehicle Management'),
            'APP_LOGO': branding.get('logo_filename'),
            'PRIMARY_COLOR': branding.get('primary_color', '#0284c7'),
            'TAILWIND_ASSET_URL': app.config.get('TAILWIND_ASSET_URL', '/static/vendor/tailwindcss.js'),
            'TAILWIND_CDN_URL': app.config.get('TAILWIND_CDN_URL', 'https://cdn.tailwindcss.com'),
            'HTMX_ASSET_URL': app.config.get('HTMX_ASSET_URL', '/static/vendor/htmx.min.js'),
            'HTMX_CDN_URL': app.config.get('HTMX_CDN_URL', 'https://unpkg.com/htmx.org@1.9.10'),
            'FLATPICKR_JS_ASSET_URL': app.config.get('FLATPICKR_JS_ASSET_URL', '/static/vendor/flatpickr.min.js'),
            'FLATPICKR_JS_CDN_URL': app.config.get('FLATPICKR_JS_CDN_URL', 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js'),
            'FLATPICKR_CSS_ASSET_URL': app.config.get('FLATPICKR_CSS_ASSET_URL', '/static/vendor/flatpickr.min.css'),
            'FLATPICKR_CSS_CDN_URL': app.config.get('FLATPICKR_CSS_CDN_URL', 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.css'),
        }

    # Map stored slugs (e.g. 'maintenance', 'petrol') to their translated
    # display labels. Templates previously rendered the raw slug with CSS
    # capitalisation, which bypassed translation entirely (#266).
    @app.template_filter('category_label')
    def category_label_filter(value):
        from app.models import EXPENSE_CATEGORIES
        return dict(EXPENSE_CATEGORIES).get(value) or (value or '').replace('_', ' ').title()

    @app.template_filter('fuel_type_label')
    def fuel_type_label_filter(value):
        from app.models import FUEL_TYPES
        return dict(FUEL_TYPES).get(value) or (value or '').replace('_', ' ').title()

    @app.template_filter('spec_label')
    def spec_label_filter(spec):
        # Predefined spec labels were stamped into the DB in the locale active
        # at save time; re-resolve them from spec_type so they follow the
        # user's current language. Custom specs keep their stored label.
        from app.models import VEHICLE_SPEC_TYPES
        if spec.spec_type and spec.spec_type != 'custom':
            label = dict(VEHICLE_SPEC_TYPES).get(spec.spec_type)
            if label:
                return label
        return spec.label

    @app.template_filter('money')
    def money_filter(value):
        """Format a money amount per the user's separator/rounding prefs (#134).

        'period' grouping implies the European convention, so the decimal
        separator becomes a comma.
        """
        if value is None:
            value = 0
        sep = 'none'
        decimals = 2
        if current_user and current_user.is_authenticated:
            sep = getattr(current_user, 'thousand_separator', None) or 'none'
            if getattr(current_user, 'round_costs', False):
                decimals = 0
        s = f"{value:,.{decimals}f}"
        if sep == 'none':
            return s.replace(',', '')
        if sep == 'space':
            return s.replace(',', '\u202f')
        if sep == 'period':
            return s.replace('.', '\x00').replace(',', '.').replace('\x00', ',')
        return s

    @app.template_filter('groupnum')
    def groupnum_filter(value, decimals=0):
        """Group a non-currency number per the user's separator pref (#134)."""
        if value is None:
            value = 0
        sep = 'none'
        if current_user and current_user.is_authenticated:
            sep = getattr(current_user, 'thousand_separator', None) or 'none'
        s = f"{value:,.{decimals}f}"
        if sep == 'none':
            return s.replace(',', '')
        if sep == 'space':
            return s.replace(',', '\u202f')
        if sep == 'period':
            return s.replace('.', '\x00').replace(',', '.').replace('\x00', ',')
        return s

    @app.template_filter('format_date')
    def format_date_filter(value, style='default'):
        if value is None:
            return ''
        user_format = 'DD/MM/YYYY'
        if current_user and current_user.is_authenticated:
            user_format = getattr(current_user, 'date_format', None) or 'DD/MM/YYYY'
        formats = DATE_FORMATS.get(user_format, DATE_FORMATS['DD/MM/YYYY'])
        fmt = formats.get(style, formats['default'])
        return value.strftime(fmt)

    from app.routes import main, auth, vehicles, fuel, expenses, api, reminders, maintenance, documents, stations, recurring, homeassistant, calendar, trips, charging, notes, allowance, search
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(vehicles.bp)
    app.register_blueprint(fuel.bp)
    app.register_blueprint(expenses.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(reminders.bp)
    app.register_blueprint(maintenance.bp)
    app.register_blueprint(documents.bp)
    app.register_blueprint(stations.bp)
    app.register_blueprint(recurring.bp)
    app.register_blueprint(homeassistant.bp)
    app.register_blueprint(calendar.bp)
    app.register_blueprint(trips.bp)
    app.register_blueprint(charging.bp)
    app.register_blueprint(notes.bp)
    app.register_blueprint(allowance.bp)
    app.register_blueprint(search.bp)

    # Health check endpoint for container orchestration
    @app.route('/health')
    def health_check():
        return {'status': 'healthy'}, 200

    # Security headers
    @app.after_request
    def add_security_headers(response):
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Enable XSS filter in browsers
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Referrer policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Permissions policy (formerly feature policy)
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        return response

    with app.app_context():
        # Surface the running version up front so anyone reading the logs
        # for a startup failure can immediately tell what they're looking
        # at — issue #166 stalled on triage because nothing in the worker
        # boot trace identified the image version.
        _log_startup_banner(app)
        from sqlalchemy import inspect as _sa_inspect
        _fresh_db = 'users' not in _sa_inspect(db.engine).get_table_names()
        db.create_all()
        if _fresh_db:
            # A fresh database just received the complete current schema from
            # create_all(), so stamp head: replaying historical migrations on
            # top of it re-adds existing columns, and the batch rebuild in
            # 42b26bf6d488 crashes with a CircularDependencyError (#278).
            from flask_migrate import stamp
            try:
                stamp()
                app.logger.info('Stamped alembic head for fresh database')
            except Exception as e:
                app.logger.warning(f'Could not stamp alembic head: {e}')
        else:
            # Stamp alembic_version for pre-Flask-Migrate databases so future
            # `flask db upgrade` runs apply only pending migrations.
            _bootstrap_alembic_version(app)
        # Run schema migrations for new columns on existing tables
        _run_schema_migrations(app)
        # Create default admin user if no users exist
        if User.query.count() == 0:
            admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
            admin_email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
            admin_password = os.environ.get('ADMIN_PASSWORD')

            if not admin_password:
                # Generate a secure random password
                admin_password = secrets.token_urlsafe(16)
                print("=" * 60)
                print("SECURITY NOTICE: Default admin account created")
                print(f"Username: {admin_username}")
                print(f"Password: {admin_password}")
                print("Please change this password immediately after first login!")
                print("Set ADMIN_PASSWORD environment variable to avoid this message.")
                print("=" * 60)

            admin = User(username=admin_username, email=admin_email, is_admin=True)
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()

    # Start background reminder scheduler (only in the main process, not reloader)
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        _start_reminder_scheduler(app)

    return app


def _start_reminder_scheduler(app):
    """Start a background thread that processes reminders daily."""
    import threading
    import time
    import logging

    logger = logging.getLogger(__name__)

    def reminder_loop():
        """Check reminders every hour."""
        # Wait 60 seconds after startup before first check
        time.sleep(60)

        while True:
            try:
                with app.app_context():
                    from app.services.reminder_processor import process_due_reminders
                    stats = process_due_reminders()
                    if stats['sent'] > 0 or stats['failed'] > 0:
                        logger.info(
                            f"Reminder check: {stats['sent']} sent, "
                            f"{stats['failed']} failed, {stats['skipped']} skipped"
                        )
            except Exception as e:
                logger.error(f"Error in reminder scheduler: {e}")

            try:
                with app.app_context():
                    from app.services.recurring_processor import (
                        process_due_recurring_expenses,
                    )
                    rec_stats = process_due_recurring_expenses()
                    if rec_stats['generated'] > 0 or rec_stats['errors']:
                        logger.info(
                            f"Recurring expense check: {rec_stats['generated']} "
                            f"generated, {rec_stats['skipped']} skipped, "
                            f"{len(rec_stats['errors'])} errors"
                        )
            except Exception as e:
                logger.error(f"Error in recurring expense scheduler: {e}")

            try:
                with app.app_context():
                    from app.services.uk_fuel_prices import UKFuelPriceService
                    fuel_stats = UKFuelPriceService.refresh_if_due()
                    if fuel_stats:
                        logger.info(
                            f"UK fuel price check: {fuel_stats['prices']} prices "
                            f"from {fuel_stats['matched']} forecourts, "
                            f"{fuel_stats['unmatched']} unmatched, "
                            f"{len(fuel_stats['errors'])} feed errors"
                        )
            except Exception as e:
                logger.error(f"Error in UK fuel price scheduler: {e}")

            # Check every hour
            time.sleep(3600)

    thread = threading.Thread(target=reminder_loop, daemon=True, name='reminder-scheduler')
    thread.start()
    app.logger.info("Started background reminder scheduler (hourly checks)")
