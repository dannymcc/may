#!/bin/bash
set -e

# Resolve the desired runtime UID/GID from PUID/PGID (linuxserver.io convention).
# Defaults preserve the historical 1000:1000 behaviour, so existing deployments
# that don't set these variables are unaffected.
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Remap the 'may' group/user to the requested IDs when they differ from the
# baked-in ones. -o (non-unique) avoids failures when the target ID already
# exists in the base image (e.g. Unraid's 99:100 nobody:users, where GID 100
# is already taken by the Debian 'users' group).
current_gid="$(id -g may)"
if [ "$PGID" != "$current_gid" ]; then
    groupmod -o -g "$PGID" may
fi

current_uid="$(id -u may)"
if [ "$PUID" != "$current_uid" ]; then
    usermod -o -u "$PUID" may
fi

echo "[entrypoint] Running as may (PUID: $PUID, PGID: $PGID)"

# Ensure the data + uploads directories exist, then fix ownership for bind
# mounts. The recursive chown only runs when the top-level ownership is wrong,
# so a correctly-owned (and possibly large) uploads directory doesn't slow
# startup on every restart.
mkdir -p /app/data/uploads
if [ "$(stat -c '%u:%g' /app/data)" != "$PUID:$PGID" ]; then
    chown -R may:may /app/data
fi

gosu may python - <<'PY'
import time
from sqlalchemy import create_engine, text
from config import get_database_url

database_url = get_database_url()
if database_url.startswith('sqlite'):
    raise SystemExit(0)

last_error = None
for _ in range(30):
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        raise SystemExit(0)
    except Exception as exc:
        last_error = exc
        time.sleep(2)

print(f"[entrypoint] database connection was not ready: {last_error}", flush=True)
raise SystemExit(1)
PY

# Run database migrations as the may user. Failures are logged rather than
# silently swallowed so upgrade problems are visible in container logs.
if ! gosu may flask db upgrade; then
    echo "[entrypoint] flask db upgrade failed — the app will attempt schema recovery on startup." >&2
fi

# Drop to 'may' user and run the application
exec gosu may "$@"
