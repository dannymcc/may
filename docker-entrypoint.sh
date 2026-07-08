#!/bin/bash
set -e

# Fix ownership of data directory for bind mounts
# This runs as root before dropping to the 'may' user
if [ -d "/app/data" ]; then
    chown -R may:may /app/data
fi

# Create uploads directory if it doesn't exist
mkdir -p /app/data/uploads
chown -R may:may /app/data

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
