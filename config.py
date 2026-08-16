import os
from pathlib import Path

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
    _database_url = os.environ.get('DATABASE_URL') or f'sqlite:///{basedir}/data/may.db'
    # SQLAlchemy 2.x dropped the legacy 'postgres://' scheme still emitted by
    # some hosting providers; normalise it so those URLs keep working (#239).
    if _database_url.startswith('postgres://'):
        _database_url = _database_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = _database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or str(basedir / 'data' / 'uploads')
    MAX_CONTENT_LENGTH = 300 * 1024 * 1024  # 300MB max upload
