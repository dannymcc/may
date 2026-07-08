# May

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/d3hkz6gwle)

A modern, self-hosted vehicle management application for tracking fuel consumption, expenses, reminders, and maintenance across your entire fleet.

![Flask](https://img.shields.io/badge/Flask-Python-blue) ![GitHub Release](https://img.shields.io/github/v/release/dannymcc/may) ![License](https://img.shields.io/badge/license-MIT-green) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED) ![PWA](https://img.shields.io/badge/PWA-Ready-5A0FC8)

Named after James May, completing the trio of Top Gear presenters (alongside [Clarkson](https://github.com/linuxserver/Clarkson) and [Hammond](https://github.com/AlfHou/hammond)).

## 📸 Screenshots

<p align="center">
  <img src="screenshots/dashboard.png" alt="Dashboard" width="45%">
  <img src="screenshots/vehicles.png" alt="Vehicles" width="45%">
</p>
<p align="center">
  <img src="screenshots/vehicle_details.png" alt="Vehicle Details" width="45%">
  <img src="screenshots/integrations.png" alt="Integrations" width="45%">
</p>
<p align="center">
  <img src="screenshots/import_export.png" alt="Import/Export" width="45%">
</p>

## 🚀 Features

- **🚗 Multi-Vehicle Support**: Track cars, vans, motorbikes, and scooters with custom vehicle types
- **⛽ Fuel Logging**: Record fill-ups with automatic consumption calculations (L/100km, MPG)
- **⚡ Quick Entry Mode**: Rapid fuel logging with a streamlined interface
- **💰 Expense Tracking**: Monitor maintenance, insurance, repairs, tax, and other costs by category
- **🔄 Recurring Expenses**: Track regular payments like insurance, tax, and subscriptions
- **🔧 Maintenance Schedules**: Plan and track scheduled maintenance with mileage/date intervals
- **📅 Reminders**: Set up recurring reminders for MOT, service, insurance, and tax renewals
- **🔔 Multi-Channel Notifications**: Get reminded via Email, ntfy, Pushover, or Webhooks
- **📁 Document Storage**: Store important documents (insurance, registration, manuals) per vehicle
- **⛽ Favorite Stations**: Save and quickly select your preferred fuel stations
- **👥 Multi-User**: Share vehicles between family members or team members
- **📊 Analytics Dashboard**: View spending trends and consumption statistics with interactive charts
- **📎 Attachment Support**: Upload receipts and documents to fuel logs and expenses
- **📄 PDF Reports**: Generate comprehensive vehicle reports for record-keeping
- **🔧 Customizable Units**: Support for metric/imperial, multiple currencies
- **🎛️ Menu Customization**: Show/hide menu items and set your preferred start page
- **🌍 Internationalization**: Available in multiple languages (English, German, Spanish, French, and more)
- **🎨 Custom Branding**: Personalize with your own logo, colors, and app name
- **🌙 Dark Mode**: Toggle between light and dark themes
- **📥 Import/Export**: Import from Fuelly CSV, export all data as JSON or CSV
- **🇬🇧 DVLA Integration**: Look up UK vehicle MOT and tax status automatically
- **📱 PWA Support**: Install as a mobile app with offline capabilities
- **🔌 REST API**: Full API access for integrations and automation
- **🏠 Home Assistant Integration**: Create sensors and automations for your vehicles
- **📆 Calendar Subscription**: Subscribe to reminders/events in Apple Calendar, Google Calendar, Outlook
- **🔁 Portable Calendar Events**: Manage generic events and alarms via API and publish events to CalDAV
- **🐳 Docker Ready**: Easy self-hosting via Docker

## 📦 Installation

### Quick Start with Docker

```bash
# Create a directory for May
mkdir may && cd may

# Download docker-compose.yml
curl -O https://raw.githubusercontent.com/dannymcc/may/main/docker-compose.yml

# Start the container
docker compose up -d
```

Or run directly with Docker:

```bash
docker run -d \
  --name may \
  -p 5050:5050 \
  -v may_data:/app/data \
  -e SECRET_KEY=your-secret-key \
  ghcr.io/dannymcc/may:latest
```

Access the application at `http://localhost:5050`

**First-time login:**
- Username: `admin`
- Password: Check your container logs for the auto-generated password

On first run, if no `ADMIN_PASSWORD` environment variable is set, May generates a secure random password and prints it to the console:

```
============================================================
SECURITY NOTICE: Default admin account created
Username: admin
Password: <randomly-generated-password>
Please change this password immediately after first login!
Set ADMIN_PASSWORD environment variable to avoid this message.
============================================================
```

To view the password, run:
```bash
docker logs may
```

💡 **Tip:** Set `ADMIN_PASSWORD` in your docker-compose.yml or environment to use a fixed password.

### Deploy via Portainer (GitHub Stack)

Use this repository directly as a Portainer stack source with the Portainer-specific compose file:

- Compose file: `docker-compose-port.yaml`
- Env file: `stack.env`

In Portainer, go to **Stacks** -> **Add stack** and choose **Repository**.

Set:

- Repository URL: `https://github.com/dannymcc/may.git`
- Repository reference: your target branch/tag (for example `main` or `dev`)
- Compose path: `docker-compose-port.yaml`

Then configure environment values in one of these ways:

1. Paste the key/value pairs from `stack.env` into Portainer's **Environment variables** section.
2. Or commit your own adjusted `stack.env` in your fork and reference it with Portainer if your setup supports env file loading for Git stacks.

Minimum values you should customize before deploy:

- `SECRET_KEY`
- `ADMIN_PASSWORD`
- `MAY_TAG` (`latest` for stable, `dev` for development)
- `MAY_PORT` (host port to expose)

Production hardening tips:

- Set `MAY_CONTAINER_NAME` to a unique value per environment (for example `may-prod`, `may-staging`) to avoid container name conflicts when running multiple stacks on the same Docker host.
- Use a dedicated persistent volume per stack/environment so data is isolated. If you deploy multiple stacks from this same compose file, keep separate stack names (or adjust volume naming) so each stack gets its own `may_data` volume.

After deployment, open `http://<your-host>:<MAY_PORT>`.

### Manual Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python run.py
```

## ⚙️ Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Secret key for session encryption
SECRET_KEY=your-secure-random-string

# Database location (default: SQLite)
DATABASE_URL=sqlite:////app/data/may.db

# Optional external databases
# DATABASE_URL=postgresql+psycopg://may:may@postgres:5432/may
# DATABASE_URL=mysql+pymysql://may:may@mysql:3306/may
# DATABASE_URL=mysql+pymysql://may:may@mariadb:3306/may

# Upload folder for attachments
UPLOAD_FOLDER=/app/data/uploads
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Session encryption key | Random |
| `DATABASE_URL` | Database connection string | `sqlite:////app/data/may.db` in Docker |
| `DB_ENGINE` | Optional DB builder: `sqlite`, `postgres`, `postgresql`, `mysql`, `mariadb` | `sqlite` |
| `DB_HOST` / `DB_PORT` | Host and port used when `DATABASE_URL` is omitted | Engine defaults |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | Database credentials used when `DATABASE_URL` is omitted | `may` |
| `SQLITE_PATH` | SQLite file used when `DATABASE_URL` is omitted | `data/may.db` |
| `UPLOAD_FOLDER` | Path for file uploads | `/app/data/uploads` |
| `TAILWIND_ASSET_URL` | Local Tailwind Play CDN JS path | `/static/vendor/tailwindcss.js` |
| `TAILWIND_CDN_URL` | Tailwind CDN fallback URL | `https://cdn.tailwindcss.com` |
| `HTMX_CDN_URL` | HTMX CDN URL | `https://unpkg.com/htmx.org@1.9.10` |

By default, Tailwind loads from `app/static/vendor/tailwindcss.js` and falls back to the CDN URL if the local asset is missing.

### Database Options

May defaults to SQLite so existing compose deployments keep working unchanged. For a separate database server, set `DATABASE_URL` and start the matching compose profile:

```bash
# PostgreSQL
DATABASE_URL=postgresql+psycopg://may:may@postgres:5432/may docker compose --profile postgres up -d

# MySQL
DATABASE_URL=mysql+pymysql://may:may@mysql:3306/may docker compose --profile mysql up -d

# MariaDB
DATABASE_URL=mysql+pymysql://may:may@mariadb:3306/may docker compose --profile mariadb up -d
```

`postgres://`, `postgresql://`, `mysql://`, and `mariadb://` URLs are normalized to bundled drivers automatically. Existing SQLite recovery remains SQLite-only; external databases should be kept current with Alembic migrations (`flask db upgrade`, run automatically by the container entrypoint).

## 🎯 Usage

### Dashboard
The main dashboard shows an overview of all your vehicles with key statistics:
- Total fuel costs and consumption averages
- Recent fuel logs and expenses
- Upcoming reminders and overdue alerts
- Vehicle photo cards showing make/model/year and fuel type at a glance

### Vehicles
Add and manage your vehicles with detailed information:
- Make, model, year, and registration
- Fuel type and tank capacity
- Custom specifications and notes
- Photo upload support
- **Vehicle Sharing**: Mark a vehicle as "Shared" to make it visible and loggable by all users on the instance
- **Upcoming Maintenance**: Vehicle detail pages show a live panel of scheduled maintenance tasks, with overdue and due-soon alerts
- **Parts & Consumables**: Collapsible section on the vehicle page remembers your expand/collapse preference per vehicle

### Fuel Logs
Track every fill-up with:
- Date, odometer reading, and fuel amount
- Total cost and price per unit
- Full tank indicator for accurate consumption calculations
- Automatic MPG/L per 100km calculations

### Expenses
Categorize all vehicle-related costs:
- Maintenance & Repairs
- Inspection (MOT, roadworthy checks)
- Insurance
- Tax & Registration
- Parking & Tolls
- Accessories
- Other expenses

Record odometer readings alongside costs, and expand any expense row to see vendor and notes details inline.

### Reminders
Never miss important dates:
- MOT/Inspection due dates
- Service intervals
- Insurance renewals
- Tax payments
- Custom reminders with flexible recurrence
- REST API access for CRUD automation and external sync

### Maintenance Schedules
Plan regular maintenance tasks:
- Set intervals by mileage or time (e.g., oil change every 10,000 km or 12 months)
- Track completion history
- Automatic reminder generation
- Link to expenses when completed

### Recurring Expenses
Track regular payments:
- Insurance premiums
- Road tax
- Subscriptions and memberships
- Custom recurrence patterns (monthly, quarterly, yearly)
- Automatic calendar integration

### Documents
Store important vehicle documents:
- Insurance certificates
- Registration documents
- Service manuals and instruction booklets (up to 300MB)
- MOT certificates
- Any file type (PDF, images, Word, Excel, text, ePub) with expiry date tracking

### Fuel Stations
Save your favorite stations:
- Quick selection during fuel logging
- Track prices at different stations
- Notes and location information

### Notifications
Configure your preferred notification method:
- **Email**: SMTP server configuration (admin)
- **ntfy**: Free push notifications via ntfy.sh or self-hosted
- **Pushover**: iOS/Android push notifications
- **Webhook**: HTTP POST for Home Assistant, Discord, Slack, etc.
- **Calendar event alarms**: Generic event alarms can trigger SMTP/email or webhook delivery

## 🔧 Admin Settings

Administrators can configure:
- **SMTP Settings**: Email server for notifications
- **Pushover**: Application token for push notifications
- **DVLA API**: API key for UK vehicle lookups ([get one here](https://developer-portal.driver-vehicle-licensing.api.gov.uk/))
- **Branding**: Custom logo, app name, tagline, and primary color
- **User Management**: Create, edit, and manage user accounts

## 🔌 API

May includes a REST API for automation and integrations:

```bash
# Generate an API key in Settings > API
curl -H "Authorization: Bearer may_your_api_key" \
  http://localhost:5050/api/v1/vehicles
```

See the API documentation at `/api/docs` when logged in.

Calendar/reminder automation endpoints include:
- `GET/POST /api/v1/reminders`
- `GET/PATCH/DELETE /api/v1/reminders/{id}`
- `GET/POST /api/v1/calendar/events`
- `GET/PATCH/DELETE /api/v1/calendar/events/{id}`
- `POST /api/v1/calendar/events/{id}/sync/caldav`
- `GET /api/v1/calendar/metadata`

## 🔗 Integrations

### Home Assistant
Create vehicle sensors in Home Assistant:

```yaml
sensor:
  - platform: rest
    name: "May Vehicle Stats"
    resource: http://your-may-instance/api/ha/summary
    headers:
      Authorization: Bearer may_your_api_key
    value_template: "{{ value_json.alerts_count }}"
    json_attributes:
      - total_vehicles
      - total_cost
```

Available endpoints: `/api/ha/status`, `/api/ha/vehicles`, `/api/ha/alerts`, `/api/ha/summary`

### Calendar Subscription
Subscribe to reminders in your calendar app:

1. Go to Settings > Integrations > Calendar
2. Copy the webcal URL (for Apple Calendar, Outlook) or HTTPS URL (for Google Calendar)
3. Add as a subscribed calendar in your app

The calendar includes:
- Maintenance schedules
- Recurring expense due dates
- Document expiry dates
- Custom reminders
- Generic calendar events created through the REST API

### CalDAV Publishing

Generic calendar events can be pushed to a CalDAV collection with:

```bash
curl -X POST http://localhost:5050/api/v1/calendar/events/1/sync/caldav \
  -H "Authorization: ******" \
  -H "Content-Type: application/json" \
  -d '{
    "calendar_url": "https://calendar.example.com/user/default/",
    "username": "calendar-user",
    "password": "calendar-password"
  }'
```

Credentials supplied to this endpoint are used for that sync request only; the event stores the remote calendar URL and ETag for later updates.

## 🌍 Supported Languages

May is available in the following languages:

| Language | Code | Language | Code |
|----------|------|----------|------|
| English | `en` | Swedish | `sv` |
| German (Deutsch) | `de` | Danish (Dansk) | `da` |
| Spanish (Español) | `es` | Norwegian (Norsk) | `no` |
| French (Français) | `fr` | Finnish (Suomi) | `fi` |
| Italian (Italiano) | `it` | Japanese (日本語) | `ja` |
| Dutch (Nederlands) | `nl` | Chinese (中文) | `zh` |
| Portuguese (Português) | `pt` | Korean (한국어) | `ko` |
| Polish (Polski) | `pl` | | |

You can change your language in **Settings > Units & Values > Language**.

### Improving Translations

Translations were generated with AI assistance and may contain inaccuracies. If you spot an incorrect translation, contributions are very welcome:

1. Translation files are located in `app/translations/<lang>/LC_MESSAGES/messages.po`
2. Edit the `msgstr` value for any incorrect entry
3. Submit a pull request with your fix

## 🛠️ Tech Stack

- **Backend**: Python / Flask
- **Database**: SQLite by default; PostgreSQL, MySQL, and MariaDB via SQLAlchemy
- **Frontend**: Tailwind CSS, HTMX, Chart.js
- **Server**: Gunicorn
- **Notifications**: SMTP, ntfy, Pushover, Webhooks
- **PDF Generation**: WeasyPrint

## 🐛 Troubleshooting

### Application Won't Start
- Check that all dependencies are installed: `pip install -r requirements.txt`
- Ensure the data directory is writable
- Check logs for specific error messages

### Database Issues
- Default SQLite database is created at `data/may.db`
- Ensure the SQLite directory exists and is writable
- For PostgreSQL/MySQL/MariaDB, verify `DATABASE_URL` uses the correct host, port, database, user, and password
- For schema updates, the app handles migrations automatically

### Notification Issues
- **Email**: Verify SMTP settings and credentials in admin settings
- **ntfy**: Check your topic name is correct
- **Pushover**: Ensure admin has configured the app token
- **Webhook**: Verify the URL is accessible and accepts POST requests

### PDF Generation
- WeasyPrint requires system dependencies on some platforms
- On Ubuntu/Debian: `apt-get install libpango-1.0-0 libpangocairo-1.0-0`
- On macOS: `brew install pango`

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup
1. Clone this repository
2. Create a virtual environment: `python3 -m venv venv`
3. Activate it: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Run in development mode: `python run.py`

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/dannymcc/may/issues)
- **Documentation**: This README and in-app help

## 🙏 Acknowledgments

- App icon design by [@lancetm714](https://github.com/lancetm714)

---

**Made with ❤️ by [Danny McClelland](https://github.com/dannymcc)**
