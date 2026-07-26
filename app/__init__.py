from flask import Flask, request, g
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_babel import Babel, gettext as _
from config import Config
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
    'de': 'Deutsch',
    'es': 'Español',
    'fr': 'Français',
    'it': 'Italiano',
    'nl': 'Nederlands',
    'pt': 'Português',
    'pl': 'Polski',
    'sv': 'Svenska',
    'da': 'Dansk',
    'no': 'Norsk',
    'fi': 'Suomi',
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


def _run_schema_migrations(app):
    """Add missing columns to existing tables.

    SQLite doesn't support adding columns via db.create_all() for existing tables,
    so we manually add any missing columns here.
    """
    from sqlalchemy import text, inspect

    # Define schema migrations: table -> [(column_name, column_type), ...]
    migrations = {
        'vehicles': [
            ('tessie_vin', 'VARCHAR(20)'),
            ('tessie_enabled', 'BOOLEAN DEFAULT 0'),
            ('tessie_last_odometer', 'FLOAT'),
            ('tessie_battery_level', 'INTEGER'),
            ('tessie_battery_range', 'FLOAT'),
            ('tessie_last_updated', 'DATETIME'),
            ('tracking_unit', "VARCHAR(20) DEFAULT 'mileage'"),
        ],
        'users': [
            ('date_format', "VARCHAR(20) DEFAULT 'DD/MM/YYYY'"),
            ('password_reset_token', 'VARCHAR(100)'),
            ('password_reset_expires', 'DATETIME'),
            ('show_menu_supplies', 'BOOLEAN DEFAULT 1'),
            ('show_menu_notes', 'BOOLEAN DEFAULT 1'),
        ],
        'charging_sessions': [
            ('tessie_charge_id', 'VARCHAR(50)'),
        ],
    }

    # Define unique indexes to create after adding columns
    # SQLite doesn't support adding UNIQUE columns directly via ALTER TABLE
    unique_indexes = [
        ('charging_sessions', 'tessie_charge_id', 'ix_charging_sessions_tessie_charge_id'),
        ('users', 'password_reset_token', 'ix_users_password_reset_token'),
    ]

    with db.engine.connect() as conn:
        inspector = inspect(db.engine)

        for table_name, columns in migrations.items():
            # Check if table exists
            if table_name not in inspector.get_table_names():
                continue

            # Get existing columns
            existing_cols = [col['name'] for col in inspector.get_columns(table_name)]

            # Add missing columns
            for col_name, col_type in columns:
                if col_name not in existing_cols:
                    try:
                        conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}'))
                        app.logger.info(f'Added column {col_name} to {table_name}')
                    except Exception as e:
                        app.logger.warning(f'Could not add column {col_name} to {table_name}: {e}')

        # Create unique indexes
        for table_name, col_name, index_name in unique_indexes:
            if table_name not in inspector.get_table_names():
                continue
            # Check if index already exists
            existing_indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
            if index_name not in existing_indexes:
                try:
                    conn.execute(text(f'CREATE UNIQUE INDEX {index_name} ON {table_name} ({col_name})'))
                    app.logger.info(f'Created unique index {index_name} on {table_name}.{col_name}')
                except Exception as e:
                    app.logger.warning(f'Could not create index {index_name}: {e}')

        conn.commit()


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

    # Babel configuration
    app.config['BABEL_DEFAULT_LOCALE'] = 'en'
    app.config['BABEL_SUPPORTED_LOCALES'] = list(LANGUAGES.keys())

    # Ensure data directories exist
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('sqlite:///') and ':memory:' not in db_uri:
        data_dir = os.path.dirname(db_uri.replace('sqlite:///', ''))
    else:
        data_dir = app.config['UPLOAD_FOLDER']
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'backups'), exist_ok=True)

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
        return {
            'LANGUAGES': LANGUAGES,
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

    from app.routes import main, auth, vehicles, fuel, expenses, api, reminders, maintenance, documents, stations, recurring, homeassistant, calendar, trips, charging, admin, supplies, notes
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
    app.register_blueprint(admin.bp)
    app.register_blueprint(supplies.bp)
    app.register_blueprint(notes.bp)

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
        db.create_all()
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

    # Start background schedulers (only in the main process, not reloader)
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        _start_reminder_scheduler(app)
        _start_backup_scheduler(app)

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

            # Check every hour
            time.sleep(3600)

    thread = threading.Thread(target=reminder_loop, daemon=True, name='reminder-scheduler')
    thread.start()
    app.logger.info("Started background reminder scheduler (hourly checks)")


def _start_backup_scheduler(app):
    """Start a background thread that creates automated backups on schedule."""
    import threading
    import time
    import logging

    logger = logging.getLogger(__name__)

    def backup_loop():
        """Check every hour whether a scheduled backup is due."""
        time.sleep(90)  # short initial delay so DB is fully ready

        while True:
            try:
                with app.app_context():
                    from app.models import AppSettings, User
                    from app.services.backup_service import (
                        get_backup_dir, create_backup_file, cleanup_old_backups
                    )

                    enabled = AppSettings.get('backup_enabled', 'false') == 'true'
                    if not enabled:
                        time.sleep(3600)
                        continue

                    frequency = AppSettings.get('backup_frequency', 'daily')
                    target_hour = int(AppSettings.get('backup_hour', '2'))
                    retention = int(AppSettings.get('backup_retention', '7'))

                    now = __import__('datetime').datetime.utcnow()
                    if now.hour != target_hour:
                        time.sleep(3600)
                        continue

                    # Check frequency gate
                    if frequency == 'weekly' and now.weekday() != 0:   # Monday
                        time.sleep(3600)
                        continue
                    if frequency == 'monthly' and now.day != 1:
                        time.sleep(3600)
                        continue

                    # Check we haven't already run in this hour window
                    last_run_str = AppSettings.get('backup_last_run', '')
                    if last_run_str:
                        try:
                            last_run = __import__('datetime').datetime.fromisoformat(last_run_str)
                            if (now - last_run).total_seconds() < 3600:
                                time.sleep(3600)
                                continue
                        except ValueError:
                            pass

                    backup_dir = get_backup_dir(app)
                    upload_folder = app.config['UPLOAD_FOLDER']

                    # Back up every admin user
                    admins = User.query.filter_by(is_admin=True).all()
                    for admin_user in admins:
                        try:
                            fname = create_backup_file(admin_user, upload_folder, backup_dir)
                            logger.info('Scheduled backup created for %s: %s', admin_user.username, fname)
                        except Exception as e:
                            logger.error('Scheduled backup failed for %s: %s', admin_user.username, e)

                    cleanup_old_backups(backup_dir, retention)
                    AppSettings.set('backup_last_run', now.isoformat())

            except Exception as e:
                logger.error('Error in backup scheduler: %s', e)

            time.sleep(3600)

    thread = threading.Thread(target=backup_loop, daemon=True, name='backup-scheduler')
    thread.start()
    app.logger.info("Started background backup scheduler (hourly checks)")
