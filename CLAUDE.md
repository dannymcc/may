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

## Development Workflow

- **`main` branch**: Production - only receives changes via pull requests from `dev`
- **`dev` branch**: Testing/development - all new features and changes go here first

### Process

1. All new features and changes are committed and pushed to the `dev` branch
2. Test changes thoroughly on `dev`
3. When ready for production, create a pull request from `dev` to `main`
4. Include a comprehensive changelog in the PR description listing all changes
5. After merge, the GitHub Actions workflow builds and pushes the production Docker image

---

# Project Overview

May is a self-hosted vehicle management application built with Flask. It tracks fuel consumption, expenses, maintenance, trips, EV charging, and more.

## Tech Stack

- **Backend**: Flask (Python 3.12)
- **Database**: SQLite with SQLAlchemy ORM
- **Frontend**: Jinja2 templates with Tailwind CSS
- **Charts**: Chart.js
- **PDF Generation**: WeasyPrint
- **Production Server**: Gunicorn

## Project Structure

```
may/
├── app/
│   ├── __init__.py          # App factory, blueprint registration
│   ├── models.py             # SQLAlchemy models (User, Vehicle, FuelLog, etc.)
│   ├── routes/               # Blueprint route handlers
│   │   ├── main.py           # Dashboard, timeline
│   │   ├── auth.py           # Login, register, settings
│   │   ├── vehicles.py       # Vehicle CRUD
│   │   ├── fuel.py           # Fuel logging
│   │   ├── expenses.py       # Expense tracking
│   │   ├── trips.py          # Trip logging
│   │   ├── charging.py       # EV charging sessions
│   │   ├── stations.py       # Fuel stations, price tracking
│   │   └── ...
│   ├── templates/            # Jinja2 templates
│   └── static/               # CSS, JS, images
├── config.py                 # App configuration, version
├── run.py                    # App entry point
├── Dockerfile                # Container build
├── docker-compose.yml        # Docker deployment
└── docker-entrypoint.sh      # Handles bind mount permissions
```

## Key Models

- **User**: Authentication, preferences, menu visibility settings
- **Vehicle**: Cars, motorcycles, etc. with fuel type support
- **FuelLog**: Fuel fill-ups with consumption calculation
- **Expense**: Maintenance, insurance, tax, etc.
- **Trip**: Business/personal trip logging for tax purposes
- **ChargingSession**: EV charging with kWh, SOC%, cost
- **AppSettings**: Key-value store for app-wide settings (branding, registration toggle)

## Database

SQLite database stored at `/data/may.db`. The project uses Flask-Migrate (Alembic) for database migrations.

### First-Time Setup (after pulling these changes)

```bash
# Initialize migrations folder (only once)
flask db init

# Create initial migration from existing models
flask db migrate -m "Initial migration"

# Apply migrations
flask db upgrade
```

### Creating New Migrations

When you change models:

```bash
flask db migrate -m "Description of changes"
flask db upgrade
```

Migrations run automatically on container startup via the entrypoint script.

## Deployment

### GitHub Actions Workflow

The project uses GitHub Actions (`.github/workflows/docker-build.yml`) to automatically build and push Docker images:

1. On push to `main`, `dev`, or new tags, the workflow triggers
2. Builds a multi-platform Docker image (linux/amd64, linux/arm64)
3. Pushes to GitHub Container Registry: `ghcr.io/dannymcc/may`
4. Tags: `latest` for main branch, `dev` for dev branch, version tags (e.g., `v0.3.0`) for releases

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
7. GitHub Actions automatically builds and pushes the Docker image with version tag
8. Sync `dev` with `main` after release:
   ```bash
   git checkout dev
   git reset --hard origin/main
   git push origin dev --force
   ```

### Docker Deployment

The container:
- Exposes port **5050** (not 5000)
- Runs as non-root user `may` via entrypoint script
- Handles bind mount permissions automatically
- Health check endpoint: `/health`

Example docker-compose.yml for deployment:
```yaml
services:
  may:
    image: ghcr.io/dannymcc/may:latest
    container_name: may
    restart: unless-stopped
    ports:
      - "5050:5050"
    volumes:
      - ./data:/app/data
    environment:
      - SECRET_KEY=your-secret-key
```

### Reverse Proxy (Caddy)

When using Caddy as a reverse proxy with May running in Docker:
- Connect both containers to the same Docker network
- Use the container name and internal port: `reverse_proxy may:5050`

## Testing Locally

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run development server
python run.py
```

Default login: `admin` / `admin`
