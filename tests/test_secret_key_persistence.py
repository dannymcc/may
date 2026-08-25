"""Repro for #317: with no SECRET_KEY set, gunicorn's multiple worker
processes each generate their own random key, so a session cookie signed by
one worker fails to validate on another and the user is bounced back to the
login page on the very next request.

config.py generates SECRET_KEY at import time (see tests/test_config_dotenv.py
for why these tests spawn a child interpreter rather than importing directly).
Each `run_config()` call below is a fresh Python process reading the same
config.py in the same directory with no SECRET_KEY / .env present -- exactly
what happens when two gunicorn workers fork and separately import the app
without SECRET_KEY configured. Today each process invents its own key, so the
two calls disagree; once the generated key is persisted to disk on first boot
and reused, they must agree.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_PY = Path(__file__).resolve().parent.parent / 'config.py'

PROBE = 'import json, config; print(json.dumps({"SECRET_KEY": config.Config.SECRET_KEY}))'


def run_config(tmp_path, env=None):
    """Import a fresh copy of config.py in a brand new child process and
    return its settings, simulating one gunicorn worker's boot-time import."""
    shutil.copy(CONFIG_PY, tmp_path / 'config.py')
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


def run_config_raw(tmp_path, env=None):
    """As run_config, but return the CompletedProcess so a test can inspect
    warnings on stderr."""
    shutil.copy(CONFIG_PY, tmp_path / 'config.py')
    child_env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(tmp_path)}
    child_env.update(env or {})
    return subprocess.run(
        [sys.executable, '-c', PROBE],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        text=True,
    )


class TestSecretKeyPersistsAcrossProcesses:
    def test_generated_secret_key_is_shared_across_worker_processes(self, tmp_path):
        """Two 'workers' (fresh processes, no SECRET_KEY/.env) booting against
        the same data directory must end up with the same session-signing
        key, or sessions break every time a request lands on the other
        worker (#317)."""
        first_worker = run_config(tmp_path)['SECRET_KEY']
        second_worker = run_config(tmp_path)['SECRET_KEY']

        assert first_worker == second_worker, (
            "SECRET_KEY differs between two process boots with no explicit "
            "SECRET_KEY set -- session cookies signed by one gunicorn worker "
            "will be rejected by the other, forcing users back to the login "
            "page on the next request."
        )

    def test_generated_key_is_saved_to_the_data_directory(self, tmp_path):
        """The generated key is written to data/.secret_key, so it also
        survives a restart."""
        key = run_config(tmp_path)['SECRET_KEY']

        key_file = tmp_path / 'data' / '.secret_key'
        assert key_file.read_text().strip() == key

    def test_existing_key_file_is_reused(self, tmp_path):
        """A key already on disk is used as-is rather than replaced."""
        key_file = tmp_path / 'data' / '.secret_key'
        key_file.parent.mkdir()
        key_file.write_text('previously-generated-key\n')

        assert run_config(tmp_path)['SECRET_KEY'] == 'previously-generated-key'

    def test_explicit_secret_key_is_not_persisted(self, tmp_path):
        """A key set in the environment wins and nothing is written to disk."""
        settings = run_config(tmp_path, env={'SECRET_KEY': 'from-real-env'})

        assert settings['SECRET_KEY'] == 'from-real-env'
        assert not (tmp_path / 'data' / '.secret_key').exists()

    def test_empty_key_file_is_claimed_rather_than_left_alone(self, tmp_path):
        """A key file that exists but holds nothing is filled in.

        A container killed between creating the file and writing to it, a full
        disk, or someone making the file by hand meaning to fill it in later
        all leave an empty data/.secret_key. Nothing repairs it on a later
        boot, so every worker would keep falling back to a key of its own and
        forms would keep being refused with "The CSRF session token is
        missing" (#315).
        """
        key_file = tmp_path / 'data' / '.secret_key'
        key_file.parent.mkdir()
        key_file.write_text('')

        first_worker = run_config(tmp_path)['SECRET_KEY']
        second_worker = run_config(tmp_path)['SECRET_KEY']

        assert first_worker == second_worker, (
            "SECRET_KEY differs between two process boots against an empty "
            "key file -- sessions and CSRF tokens break whenever a request "
            "lands on the other gunicorn worker."
        )
        assert key_file.read_text().strip() == first_worker

    def test_whitespace_only_key_file_is_claimed(self, tmp_path):
        """A file holding only whitespace is no more a key than an empty one."""
        key_file = tmp_path / 'data' / '.secret_key'
        key_file.parent.mkdir()
        key_file.write_text('   \n')

        first_worker = run_config(tmp_path)['SECRET_KEY']

        assert key_file.read_text().strip() == first_worker
        assert run_config(tmp_path)['SECRET_KEY'] == first_worker

    def test_unreadable_key_file_is_left_alone(self, tmp_path):
        """Only a file that positively reads as empty is claimed.

        A key file there is no reading — one belonging to another user, or a
        directory, as Docker leaves behind when a bind mount names a path that
        does not exist — may hold the very key the other workers are signing
        with, so May warns and starts on an in-memory key rather than writing
        over it.
        """
        key_dir = tmp_path / 'data' / '.secret_key'
        key_dir.mkdir(parents=True)

        result = run_config_raw(tmp_path)

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['SECRET_KEY']
        assert 'RuntimeWarning' in result.stderr
        assert 'Set SECRET_KEY for production' in result.stderr
        assert key_dir.is_dir() and not list(key_dir.iterdir())
        assert sorted(p.name for p in (tmp_path / 'data').iterdir()) == ['.secret_key']

    def test_unwritable_data_directory_falls_back_with_a_warning(self, tmp_path):
        """If the key cannot be saved (read-only filesystem, say) May still
        starts with an in-memory key and says so."""
        # A plain file where the data directory should be makes every attempt
        # to create data/.secret_key fail, whatever the process's privileges.
        (tmp_path / 'data').write_text('not a directory')

        result = run_config_raw(tmp_path)

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['SECRET_KEY']
        assert 'RuntimeWarning' in result.stderr
        assert 'Set SECRET_KEY for production' in result.stderr
