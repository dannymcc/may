# Project Rules

## Git Commits

- Never include "Co-Authored-By: Claude" or similar AI attribution lines in commits
- Use conventional commit format for organized commit history:
  - `feat: description` - New features
  - `fix: description` - Bug fixes
  - `perf: description` - Performance improvements
  - `deps: description` - Dependency updates
  - `docs: description` - Documentation changes
  - `ci: description` - CI/CD changes
  - `chore: description` - Other changes

---

# Project Overview

Willman is a self-hosted vehicle management application built with Flask (a fork of `dannymcc/may`, now developed at `austincnunn/Willman`). It tracks fuel consumption, expenses, maintenance, trips, EV charging, documents, reminders, and more.

## Tech Stack

- **Backend**: Flask (Python 3.12)
- **Database**: SQLite with SQLAlchemy ORM, Flask-Migrate (Alembic) for migrations
- **Frontend**: Jinja2 templates with Tailwind CSS, htmx, Flatpickr
- **i18n**: Flask-Babel (`app/translations/`, `babel.cfg`) — English, German, Spanish, French, and others
- **Charts**: Chart.js
- **PDF Generation**: WeasyPrint
- **Production Server**: Gunicorn
- **Tests**: pytest / pytest-cov (`tests/`, `pytest.ini`)

## Project Structure

```
├── app/
│   ├── __init__.py          # App factory, blueprint registration, default admin creation
│   ├── models.py             # SQLAlchemy models
│   ├── security.py           # Security helpers
│   ├── routes/                # Blueprint route handlers
│   │   ├── main.py            # Dashboard, timeline
│   │   ├── auth.py            # Login, register, settings
│   │   ├── admin.py           # Admin panel
│   │   ├── api.py             # REST API
│   │   ├── vehicles.py        # Vehicle CRUD
│   │   ├── fuel.py            # Fuel logging
│   │   ├── expenses.py        # Expense tracking
│   │   ├── recurring.py       # Recurring expenses
│   │   ├── trips.py           # Trip logging
│   │   ├── charging.py        # EV charging sessions
│   │   ├── stations.py        # Fuel stations, price tracking
│   │   ├── maintenance.py     # Maintenance schedules
│   │   ├── reminders.py       # Reminders
│   │   ├── calendar.py        # Calendar subscription feeds
│   │   ├── documents.py       # Document storage
│   │   ├── notes.py           # Vehicle notes
│   │   ├── supplies.py        # Supplies tracking
│   │   └── homeassistant.py   # Home Assistant integration
│   ├── services/               # DVLA lookup, Tessie, notifications, backups, reminder processing
│   ├── templates/              # Jinja2 templates
│   ├── translations/           # Flask-Babel locale files
│   └── static/                 # CSS, JS, images
├── migrations/                # Alembic migration scripts (already committed)
├── tests/                     # pytest suite
├── config.py                  # App configuration, APP_VERSION
├── run.py                     # App entry point
├── Dockerfile                 # Container build (non-root `willman` user)
├── docker-compose.yml         # Docker deployment
└── docker-entrypoint.sh       # Handles bind mount permissions, runs migrations
```

## Key Models

(`app/models.py`)

- **User**: Authentication, preferences, menu visibility settings
- **Vehicle**: Cars, motorcycles, etc. with fuel type support
- **FuelLog**: Fuel fill-ups with consumption calculation
- **FuelStation** / **FuelPriceHistory**: Favorite stations and price tracking
- **Expense**: Maintenance, insurance, tax, etc.
- **RecurringExpense**: Regular payments (insurance, tax, subscriptions)
- **MaintenanceSchedule**: Mileage/date-based maintenance planning
- **Trip**: Business/personal trip logging for tax purposes
- **ChargingSession**: EV charging with kWh, SOC%, cost
- **Reminder**: MOT/service/insurance/tax renewal reminders
- **Document**: Per-vehicle document storage
- **VehicleNote**: Free-form notes per vehicle
- **VehiclePart** / **Supply**: Parts and consumable supplies tracking
- **VehicleSpec**: Vehicle specification data
- **Attachment**: Receipts/files attached to fuel logs and expenses
- **AppSettings**: Key-value store for app-wide settings (branding, registration toggle)

## Database

SQLite database stored at `data/willman.db` (path configurable via `DATABASE_URL`). The project uses Flask-Migrate (Alembic); the `migrations/` folder is already committed.

### Setup

```bash
flask db upgrade
```

### Creating New Migrations

When you change models:

```bash
flask db migrate -m "Description of changes"
flask db upgrade
```

Migrations run automatically on container startup via `docker-entrypoint.sh`.

## Deployment

### GitHub Actions Workflows

Two workflows in `.github/workflows/`:

- **`docker-publish.yml`** — on push to `main`: builds a single-platform image and pushes `ghcr.io/austincnunn/willman:latest` and `:<sha>` (no test gate).
- **`docker.yml`** — on push to `dev` or a `v*` tag: runs `pytest tests/`, then builds a multi-platform image (linux/amd64, linux/arm64) and pushes to `ghcr.io/austincnunn/willman` tagged `dev` (dev branch), semver tags, and `latest` (only when triggered by a version tag).

### Creating a Release

1. Update `APP_VERSION` in `config.py`
2. Commit the version bump to `dev`
3. Create a pull request from `dev` to `main` with comprehensive changelog
4. Merge the PR to `main`
5. Create and push a version tag:
   ```bash
   git checkout main
   git pull origin main
   git tag v0.X.0
   git push origin v0.X.0
   ```
6. Create the GitHub release with changelog:
   ```bash
   gh release create v0.X.0 --title "v0.X.0" --notes "## What's Changed

   ### New Features
   - Feature description

   ### Bug Fixes
   - Fix description

   ### Other Changes
   - Change description"
   ```
7. GitHub Actions automatically builds and pushes the Docker image with the version tag
8. Sync `dev` with `main` after release:
   ```bash
   git checkout dev
   git reset --hard origin/main
   git push origin dev --force
   ```

### Docker Deployment

The container:
- Exposes port **5151** (not 5000)
- Runs as non-root user `willman` via `docker-entrypoint.sh`
- Handles bind mount permissions automatically
- Health check endpoint: `/health`

Example docker-compose.yml for deployment:
```yaml
services:
  willman:
    image: ghcr.io/austincnunn/willman:latest
    container_name: willman
    restart: unless-stopped
    ports:
      - "5151:5151"
    volumes:
      - ./data:/app/data
    environment:
      - SECRET_KEY=your-secret-key
```

Relevant environment variables: `SECRET_KEY`, `DATABASE_URL`, `UPLOAD_FOLDER`, `INTERNAL_API_KEY`, `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `RELEASE_CHANNEL`.

### Reverse Proxy (Caddy)

When using Caddy as a reverse proxy with Willman running in Docker:
- Connect both containers to the same Docker network
- Use the container name and internal port: `reverse_proxy willman:5151`

## Testing Locally

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run development server
python run.py

# Run tests
pytest tests/
```

**First-time login**: username `admin`. No fixed default password — on first startup, if no users exist, a random password is generated and printed to the container/app logs (or set `ADMIN_PASSWORD` to choose one).
