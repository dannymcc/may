"""Tests for .env loading in config.py (#297).

config.py reads the environment at import time and is already imported by the
time these tests run, so each case runs a fresh child interpreter against a
copy of config.py in a temporary directory. config.py only needs stdlib plus
python-dotenv, so the child does not need the rest of the app.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CONFIG_PY = Path(__file__).resolve().parent.parent / 'config.py'

# Print the three settings a user is most likely to set in .env.
PROBE = (
    'import json, config; '
    'print(json.dumps({'
    '"SECRET_KEY": config.Config.SECRET_KEY, '
    '"SQLALCHEMY_DATABASE_URI": config.Config.SQLALCHEMY_DATABASE_URI, '
    '"UPLOAD_FOLDER": config.Config.UPLOAD_FOLDER}))'
)

DOTENV = (
    '# May Configuration\n'
    'SECRET_KEY=from-dotenv-secret\n'
    'DATABASE_URL=sqlite:////tmp/dotenv/may.db\n'
    'UPLOAD_FOLDER=/tmp/dotenv/uploads\n'
)


def run_config(tmp_path, env=None, dotenv=DOTENV):
    """Import a copy of config.py in a child process and return its settings."""
    shutil.copy(CONFIG_PY, tmp_path / 'config.py')
    if dotenv is not None:
        (tmp_path / '.env').write_text(dotenv)
    child_env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(tmp_path)}
    child_env.update(env or {})
    result = subprocess.run(
        [sys.executable, '-c', PROBE],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestDotenvLoading:
    def test_secret_key_read_from_dotenv(self, tmp_path):
        assert run_config(tmp_path)['SECRET_KEY'] == 'from-dotenv-secret'

    def test_database_url_read_from_dotenv(self, tmp_path):
        settings = run_config(tmp_path)
        assert settings['SQLALCHEMY_DATABASE_URI'] == 'sqlite:////tmp/dotenv/may.db'

    def test_upload_folder_read_from_dotenv(self, tmp_path):
        assert run_config(tmp_path)['UPLOAD_FOLDER'] == '/tmp/dotenv/uploads'

    def test_postgres_scheme_from_dotenv_still_normalised(self, tmp_path):
        # The legacy scheme fixup (#239) must still apply to .env values.
        settings = run_config(
            tmp_path,
            dotenv='DATABASE_URL=postgres://user:pw@host:5432/may\n',
        )
        assert settings['SQLALCHEMY_DATABASE_URI'] == 'postgresql://user:pw@host:5432/may'

    def test_defaults_used_when_no_dotenv(self, tmp_path):
        settings = run_config(tmp_path, dotenv=None)
        assert settings['SQLALCHEMY_DATABASE_URI'] == f'sqlite:///{tmp_path}/data/may.db'
        assert settings['UPLOAD_FOLDER'] == str(tmp_path / 'data' / 'uploads')


class TestEnvironmentPrecedence:
    """Real environment variables must win over .env, or Docker regresses."""

    @pytest.mark.parametrize('key, value, setting', [
        ('SECRET_KEY', 'from-real-env', 'SECRET_KEY'),
        ('DATABASE_URL', 'sqlite:////app/data/may.db', 'SQLALCHEMY_DATABASE_URI'),
        ('UPLOAD_FOLDER', '/app/data/uploads', 'UPLOAD_FOLDER'),
    ])
    def test_environment_overrides_dotenv(self, tmp_path, key, value, setting):
        settings = run_config(tmp_path, env={key: value})
        assert settings[setting] == value
