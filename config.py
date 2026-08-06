import os
from pathlib import Path
from urllib.parse import quote_plus

basedir = Path(__file__).parent.absolute()


APP_VERSION = '0.27.1'
RELEASE_CHANNEL = os.environ.get('RELEASE_CHANNEL', 'stable')
GIT_SHA = os.environ.get('GIT_SHA', '')[:7]  # Short SHA
GITHUB_REPO = 'dannymcc/may'
TAILWIND_ASSET_URL = os.environ.get('TAILWIND_ASSET_URL', '/static/vendor/tailwindcss.js')
TAILWIND_CDN_URL = os.environ.get('TAILWIND_CDN_URL', 'https://cdn.tailwindcss.com')
HTMX_ASSET_URL = os.environ.get('HTMX_ASSET_URL', '/static/vendor/htmx.min.js')
HTMX_CDN_URL = os.environ.get('HTMX_CDN_URL', 'https://unpkg.com/htmx.org@1.9.10')
FLATPICKR_JS_ASSET_URL = os.environ.get('FLATPICKR_JS_ASSET_URL', '/static/vendor/flatpickr.min.js')
FLATPICKR_JS_CDN_URL = os.environ.get('FLATPICKR_JS_CDN_URL', 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js')
FLATPICKR_CSS_ASSET_URL = os.environ.get('FLATPICKR_CSS_ASSET_URL', '/static/vendor/flatpickr.min.css')
FLATPICKR_CSS_CDN_URL = os.environ.get('FLATPICKR_CSS_CDN_URL', 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.css')

# Build display version (e.g., "0.5.0" for stable, "0.5.0-dev+abc1234" for dev)
if RELEASE_CHANNEL == 'dev' and GIT_SHA:
    DISPLAY_VERSION = f"{APP_VERSION}-dev+{GIT_SHA}"
elif RELEASE_CHANNEL == 'dev':
    DISPLAY_VERSION = f"{APP_VERSION}-dev"
else:
    DISPLAY_VERSION = APP_VERSION


def _normalise_database_url(database_url):
    """Return a SQLAlchemy URL with bundled pure-Python drivers when omitted."""
    if not database_url:
        return None

    driver_map = {
        'postgres': 'postgresql+psycopg',
        'postgresql': 'postgresql+psycopg',
        'mysql': 'mysql+pymysql',
        'mariadb': 'mysql+pymysql',
    }
    for scheme, driver in driver_map.items():
        prefix = f'{scheme}://'
        if database_url.startswith(prefix):
            return f'{driver}://{database_url[len(prefix):]}'
    return database_url


def _build_database_url_from_parts():
    """Build DATABASE_URL from DB_* variables for compose deployments."""
    engine = os.environ.get('DB_ENGINE', 'sqlite').strip().lower()
    if engine in ('sqlite', 'sqlite3'):
        sqlite_path = os.environ.get('SQLITE_PATH') or str(basedir / 'data' / 'may.db')
        sqlite_path = Path(sqlite_path)
        if sqlite_path.is_absolute():
            return f'sqlite:///{sqlite_path}'
        return f'sqlite:///{sqlite_path.as_posix()}'

    driver_map = {
        'postgres': ('postgresql+psycopg', '5432'),
        'postgresql': ('postgresql+psycopg', '5432'),
        'mysql': ('mysql+pymysql', '3306'),
        'mariadb': ('mysql+pymysql', '3306'),
    }
    if engine not in driver_map:
        raise RuntimeError(
            "DB_ENGINE must be one of: sqlite, postgresql, postgres, mysql, mariadb"
        )

    driver, default_port = driver_map[engine]
    username = quote_plus(os.environ.get('DB_USER', 'may'))
    password = quote_plus(os.environ.get('DB_PASSWORD', 'may'))
    host = os.environ.get('DB_HOST', engine)
    port = os.environ.get('DB_PORT', default_port)
    name = os.environ.get('DB_NAME', 'may')
    return f'{driver}://{username}:{password}@{host}:{port}/{name}'


def get_database_url():
    return _normalise_database_url(os.environ.get('DATABASE_URL')) or _build_database_url_from_parts()


class Config:
    APP_VERSION = APP_VERSION
    DISPLAY_VERSION = DISPLAY_VERSION
    RELEASE_CHANNEL = RELEASE_CHANNEL
    GIT_SHA = GIT_SHA
    GITHUB_REPO = GITHUB_REPO
    TAILWIND_ASSET_URL = TAILWIND_ASSET_URL
    TAILWIND_CDN_URL = TAILWIND_CDN_URL
    HTMX_ASSET_URL = HTMX_ASSET_URL
    HTMX_CDN_URL = HTMX_CDN_URL
    FLATPICKR_JS_ASSET_URL = FLATPICKR_JS_ASSET_URL
    FLATPICKR_JS_CDN_URL = FLATPICKR_JS_CDN_URL
    FLATPICKR_CSS_ASSET_URL = FLATPICKR_CSS_ASSET_URL
    FLATPICKR_CSS_CDN_URL = FLATPICKR_CSS_CDN_URL
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        import secrets
        # Generate a random key for development, but warn about it
        SECRET_KEY = secrets.token_hex(32)
        import warnings
        warnings.warn(
            "SECRET_KEY environment variable not set. Using randomly generated key. "
            "Sessions will not persist across restarts. Set SECRET_KEY for production.",
            RuntimeWarning
        )
    SQLALCHEMY_DATABASE_URI = get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or str(basedir / 'data' / 'uploads')
    MAX_CONTENT_LENGTH = 300 * 1024 * 1024  # 300MB max upload
