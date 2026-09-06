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
- **⛽ Fuel Logging**: Record fill-ups with automatic consumption calculations (L/100km, MPG) and optional sales tax totals by year
- **⚡ Quick Entry Mode**: Rapid fuel logging with a streamlined interface
- **💰 Expense Tracking**: Monitor maintenance, insurance, repairs, tax, and other costs by category
- **🔄 Recurring Expenses**: Track regular payments like insurance, tax, and subscriptions
- **🧭 Trip Logging**: Log journeys for mileage and tax records, with optional fuel gauge readings for a per-trip view of consumption
- **🔧 Maintenance Schedules**: Plan and track scheduled maintenance with mileage, engine-hour or date intervals
- **🛞 Tire Sets**: Record each set of tires going on and off the vehicle, with the distance covered per set worked out for you
- **📅 Reminders**: Set up recurring reminders for MOT, service, insurance, and tax renewals
- **🔔 Multi-Channel Notifications**: Get reminded via Email, ntfy, Pushover, or Webhooks
- **📁 Document Storage**: Store important documents (insurance, registration, manuals) per vehicle
- **⛽ Favorite Stations**: Save and quickly select your preferred fuel stations
- **👥 Multi-User**: Share vehicles between family members or team members
- **🔐 User Roles**: Give each account full access, fuel-and-charging only, or read-only
- **📊 Analytics Dashboard**: View spending trends and consumption statistics with interactive charts
- **📎 Attachment Support**: Upload receipts and documents to fuel logs and expenses
- **📄 PDF Reports**: Generate comprehensive vehicle reports for record-keeping, optionally with receipt images attached
- **🔧 Customizable Units**: Support for metric/imperial, multiple currencies
- **🎛️ Menu Customization**: Show/hide menu items and set your preferred start page
- **🌍 Internationalization**: Available in multiple languages (English, German, Spanish, French, and more)
- **🎨 Custom Branding**: Personalize with your own logo, colors, and app name
- **🌙 Dark Mode**: Toggle between light and dark themes
- **📥 Import/Export**: Restore a May backup (JSON export or full ZIP) into another instance, import from Fuelly CSV, export all data as JSON or CSV
- **🇬🇧 DVLA Integration**: Look up UK vehicle MOT and tax status automatically
- **⛽ UK Fuel Prices**: Pull live forecourt prices for your saved UK stations from the government fuel price feeds, no API key needed
- **📱 PWA Support**: Install as a mobile app with offline capabilities
- **🔌 REST API**: Full API access for integrations and automation
- **🏠 Home Assistant Integration**: Create sensors and automations for your vehicles
- **📆 Calendar Subscription**: Subscribe to reminders in Apple Calendar, Google Calendar, Outlook
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
  -e PUID=1000 \
  -e PGID=1000 \
  ghcr.io/dannymcc/may:latest
```

> **Running as a specific user (PUID/PGID):** May follows the [linuxserver.io](https://docs.linuxserver.io/general/understanding-puid-and-pgid/) convention. Set the optional `PUID` and `PGID` environment variables to make the container run as a specific host user/group so bind-mounted data is owned correctly. They default to `1000:1000`. On Unraid, set `PUID=99` and `PGID=100`.

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
# Secret key for session encryption (optional)
SECRET_KEY=your-secure-random-string

# Database location (optional, defaults to SQLite in the app's data folder)
# Note the slashes: sqlite:///path is relative, sqlite:////path is absolute.
DATABASE_URL=sqlite:////srv/may/data/may.db
# PostgreSQL is also supported:
# DATABASE_URL=postgresql://user:password@host:5432/may

# Upload folder for attachments (optional)
UPLOAD_FOLDER=/srv/may/data/uploads
```

If you don't set `SECRET_KEY`, May generates one on first start and saves it to
`.secret_key` in its data folder, so logins survive restarts. Set it yourself if
you'd rather manage the key, or if you run more than one instance behind a load
balancer and want them to share sessions.

The supplied `docker-compose.yml` passes a placeholder `SECRET_KEY` when you
haven't set one of your own, so under Compose May signs sessions with that
rather than generating a key. Set `SECRET_KEY` in `.env` next to
`docker-compose.yml`, or remove the line from the compose file to let May
generate and keep its own.

The `.env` file must sit next to `config.py` in the application directory, and
it is read when May starts. Variables set in the real environment take
precedence over `.env`.

Under Docker Compose, `.env` is only used for `${VAR}` substitution in
`docker-compose.yml` (for example `SECRET_KEY`). `DATABASE_URL` and
`UPLOAD_FOLDER` are set in the compose `environment:` block, so changing them
in `.env` has no effect — edit `docker-compose.yml` instead.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Session encryption key | Generated on first start and saved to `data/.secret_key` |
| `DATABASE_URL` | Database connection string (SQLite or PostgreSQL) | SQLite at `data/may.db` inside the application directory (`/app/data/may.db` in Docker) |
| `UPLOAD_FOLDER` | Path for file uploads | `data/uploads` inside the application directory (`/app/data/uploads` in Docker) |
| `PUID` | User ID the container runs as (linuxserver.io convention) | `1000` |
| `PGID` | Group ID the container runs as (linuxserver.io convention) | `1000` |
| `TAILWIND_ASSET_URL` | Local Tailwind Play CDN JS path | `/static/vendor/tailwindcss.js` |
| `TAILWIND_CDN_URL` | Tailwind CDN fallback URL | `https://cdn.tailwindcss.com` |
| `HTMX_CDN_URL` | HTMX CDN URL | `https://unpkg.com/htmx.org@1.9.10` |

By default, Tailwind loads from `app/static/vendor/tailwindcss.js` and falls back to the CDN URL if the local asset is missing.

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
- **Tracking Unit**: Choose whether a vehicle's odometer counts distance or engine hours — plant and machinery are metered in hours, and their consumption and running costs are worked out per hour rather than per mile. The unit is fixed once anything has been logged against the odometer, since changing it would reinterpret every existing reading. Readings and the figures beside them are labelled in hours throughout ("h", "L / h", "Cost per h"), every form that records a reading calls the field "Engine hours" rather than "Odometer" — including the trip and charging forms — and a maintenance schedule for such a vehicle is set in engine hours instead of kilometres or miles. The CSV exports state each row's own unit, so engine hours are never filed under a distance heading alongside the cars, and the Home Assistant endpoints report the unit the reading is actually in — `unit_distance` (and `distance_unit` on the stats endpoint) is `h` for such a vehicle rather than the account's distance preference. Where a total spans both kinds of vehicle, as the dashboard and the trip summaries can, it says "mixed units" rather than adding engine hours to miles and calling the result a distance. The tracking unit is set on the vehicle page and is still neither exposed nor settable over the REST API; vehicles created there are tracked by distance
- **Photo Gallery**: Upload as many photos per vehicle as you like from the "Photos" section on the vehicle page. Any of them can be set as the main photo — the one shown on the dashboard and vehicle list — and the vehicle page steps through the rest with left/right arrows
- **Vehicle Sharing**: Mark a vehicle as "Shared" to make it visible and loggable by all users on the instance
- **Upcoming Maintenance**: Vehicle detail pages show a live panel of scheduled maintenance tasks, with overdue and due-soon alerts
- **Parts & Consumables**: Collapsible section on the vehicle page remembers your expand/collapse preference per vehicle
- **PDF Report**: The "PDF" button downloads a summary of the vehicle, its specifications, its parts and consumables, its fuel logs and its expenses. "PDF + Receipts" does the same and appends the receipt images attached to those entries, which is the version to hand to an accountant or employer. Non-image attachments (PDF scans, for example) are listed at the end of the report rather than embedded.
- **Service Timeline**: Combined history of fuel, expenses, and charging, including any notes recorded against an entry and links to its attachments
- **Expenses by Category**: A collapsible bar chart on the vehicle page breaking that vehicle's expenses down by category, alongside the dashboard chart covering the whole fleet. Vehicles with no expenses recorded do not show it.

### Fuel Logs
Track every fill-up with:
- Date, odometer reading, and fuel amount
- Total cost and price per unit
- Full tank indicator for accurate consumption calculations
- Automatic MPG/L per 100km calculations
- Fuel type selection for vehicles that take more than one fuel, including hybrids (petrol or diesel), so station price charts stay grouped by the fuel actually bought
- Each fuel is measured on its own: consumption figures, averages and the consumption trend chart count only the logs of that fuel type, so an AdBlue refill on a diesel never lands in the diesel L/100km. Logs recorded before the fuel type selector existed count as the vehicle's own fuel type.
- "AdBlue/DEF" is available as a vehicle's secondary fuel type, for the fluid a diesel tracks alongside its fuel. It is an exhaust additive rather than a fuel, so it is not offered as a vehicle's own fuel type and counts as no tailpipe CO2.
- The fuel log list shows the fuel type of each entry
- Optional sales tax paid on the fill-up (VAT, GST/HST/PST, or whatever applies where you are), entered as the amount shown on the receipt and treated as part of the total cost rather than added to it. Where more than one tax applies, enter the sum. The fuel log list totals it by calendar year, each fill-up's tax is shown under its cost, and the figures appear in the vehicle PDF report, the CSV and JSON exports and the API. Quick entry mode does not ask for it, so a fill-up logged that way records no tax and the yearly total will be short by that amount; edit the log afterwards to add it.

Saving a fuel log returns you to the fuel log list, unless you started from a vehicle page, in which case you go back to that vehicle. Deleting one does the same: from the fuel log list you stay on the list, from a vehicle page you return to that vehicle. Notes behave the same way.

#### Dual-fuel vehicles (petrol + LPG)
Give the vehicle a secondary fuel type and each fill-up gets a **Fuel Type**
selector. May then keeps the two fuels apart: each fuel gets its own average on
the vehicle page, built only from fill-ups of that fuel, because a combined
figure would describe neither.

The odometer cannot say which kilometres were run on LPG and which on petrol,
so a fill-up of a dual-fuel vehicle also asks for **Distance on this fuel** —
how far the car ran on that fuel since your last fill-up of it. This is only
needed where it is genuinely ambiguous: a stretch in which you filled with one
fuel only is worked out from the odometer as usual, so a car converted to LPG
keeps its earlier petrol figures. Where the two fuels are mixed and that
distance is missing, the page says the figure cannot be worked out without it
rather than showing one derived from the wrong distance.

The distance is entered in the vehicle's own unit, the one its odometer reads
in. Both the fuel type and the distance attributed to it appear in the CSV and
JSON exports, in backups and over the REST API, where they can be set on a
fill-up as well as read. The `average_consumption` figure in the API's vehicle
stats covers the vehicle's primary fuel; the per-fuel figures are on the vehicle
page. A diesel tracking AdBlue is not a dual-fuel vehicle for this purpose —
AdBlue propels nothing — so it is never asked for the distance.

### EV Charging
Log charging sessions for electric and plug-in hybrid vehicles:
- Date, optional start and end times, and the odometer reading
- Energy added in kWh, state of charge at each end, and cost — the total is worked out from the price per kWh where you do not enter it yourself
- Charger type, location and network, so home and public charging can be told apart
- The list is ordered by date, most recent first; sessions sharing a date are ordered by their odometer reading, so the most recent charge sits at the top. This matters most on a plug-in hybrid, which may be charged several times in a day

### Expenses
Categorize all vehicle-related costs:
- Maintenance & Repairs
- Inspection (MOT, roadworthy checks)
- Insurance
- Tax & Registration
- Parking & Tolls
- Accessories
- Other expenses

Record odometer readings alongside costs, and expand any expense row to see vendor, notes, and links to any attached receipts inline. An expense can have several receipts — select more than one file when adding or editing it. An odometer recorded against an expense counts towards the vehicle's latest reading, alongside fuel logs, trips and charging sessions. Saving an expense returns you to the expenses list, unless you started from a vehicle page, in which case you go back to that vehicle.

### Trips
Log journeys for mileage and tax records:
- Date, purpose, start and end locations, and the odometer at each end
- Optional fuel gauge readings at the start and end of the trip, entered as a percentage of a full tank
- Where the vehicle has a tank capacity set, the fuel used on the trip is worked out from those readings and shown on the trip list, giving a per-trip view of consumption between fill-ups
- Reusable templates for journeys you make often, and a business/personal summary report per year
- The list is ordered by date, most recent first; trips sharing a date are ordered by their odometer reading, so the journey you drove last sits at the top

### Reminders
Never miss important dates:
- MOT/Inspection due dates
- Service intervals
- Insurance renewals
- Tax payments
- Custom reminders with flexible recurrence
- **Log expense**: record what an outstanding reminder cost. The expense form opens pre-filled with the vehicle, the reminder's title and a matching category; saving it records the expense, ticks the reminder off and schedules its next occurrence. The cost is typed at that point, so reminders for fees that change — registration, for instance — stay accurate.

### Maintenance Schedules
Plan regular maintenance tasks:
- Set intervals by mileage or time (e.g., oil change every 10,000 km or 12 months)
- A vehicle tracked in engine hours takes its interval in hours instead (e.g., every 250 hours). The km and miles boxes are hidden for it, since no distance interval could be compared against an hour reading, and "due soon" means within 25 hours rather than 500
- Track completion history
- Automatic reminder generation
- Link to expenses when completed

### Tire Sets
Track summer, winter and all-season sets separately:
- Record a set with its type, size, purchase date, purchase odometer and cost
- Put a set on or take it off with a date and odometer reading; fitting a set
  automatically takes the set currently on the vehicle off at the same reading
- The distance covered on each set is the sum of every period it spent fitted,
  measured against the vehicle's latest odometer reading while it is still on
- Retire a set when it is worn out or sold; the history stays

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
- UK stations can pull live prices from the government fuel price feeds
  (see [UK Fuel Prices](#uk-fuel-prices))

### Notifications
Configure your preferred notification method:
- **Email**: SMTP server configuration (admin)
- **ntfy**: Free push notifications via ntfy.sh or self-hosted
- **Pushover**: iOS/Android push notifications
- **Webhook**: HTTP POST for Home Assistant, Discord, Slack, etc.

### Import & Restore
**Settings → Integrations → Import Data** holds the import options, including
**Restore May Backup** for moving data from another May instance:

- It takes either file the export page produces — the JSON export (`.json`) or
  the full backup (`.zip`). A full backup also brings across documents,
  attachments and vehicle images; a JSON export carries the records only.
- The restore merges into the account you are signed in as. Nothing is deleted
  or overwritten, and records already present are skipped rather than
  duplicated, so running the same backup twice is harmless.
- A preview of exactly what will be added is shown before anything is written,
  and nothing is saved until you confirm it.

Imports from Hammond and Fuelly live in the same place.

## 🔧 Admin Settings

Administrators can configure:
- **SMTP Settings**: Email server for notifications
- **Pushover**: Application token for push notifications
- **DVLA API**: API key for UK vehicle lookups ([get one here](https://developer-portal.driver-vehicle-licensing.api.gov.uk/))
- **UK Fuel Prices**: live forecourt prices for saved stations (see below)
- **Branding**: Custom logo, app name, tagline, and primary color
- **User Management**: Create, edit, and manage user accounts, including each account's role

## 🔐 User Roles

Every account has a role, set by an administrator when the account is created
or from Settings → Users → Edit:

| Role | What the account can do |
| --- | --- |
| **Editor** | Full control of the vehicles and data the account can see. This is the default, and matches how May behaved before roles existed. |
| **Contributor** | Record fuel fill-ups and charging sessions. Everything else — expenses, maintenance, trips, reminders, vehicles — is read-only. Suited to drivers. |
| **Viewer** | See everything the account has access to, but change nothing. Suited to a vehicle owner who only wants the figures. |

Administrators always have full access whatever role is stored against them.
Roles decide what an account may *change*; what it can *see* is still governed
by vehicle ownership and sharing, so a driver only sees the vehicles shared
with them.

Roles apply everywhere, not just in the browser: the REST API and the Home
Assistant endpoints refuse writes the account's role does not cover, returning
`403` with a `permission_denied` code. Every account can still manage its own
settings, password, notifications and API key.

## 🔌 API

May includes a REST API for automation and integrations:

```bash
# Generate an API key in Settings > API
curl -H "Authorization: Bearer may_your_api_key" \
  http://localhost:5050/api/v1/vehicles
```

Vehicles, fuel logs, expenses, trips, and charging sessions can all be read and
created through the API. See the API documentation at `/api/docs` when logged in.

## 🔗 Integrations

### UK Fuel Prices

UK retailers publish their forecourt prices as open JSON feeds under the
government [fuel price transparency scheme](https://www.gov.uk/guidance/access-the-latest-fuel-prices-and-forecourt-data-via-api-or-email).
May can read those feeds and record the prices against your saved stations, so
price history and Cheapest Fuel stay current without manual entry. No API key is
needed.

To use it:

1. An admin enables it in **Settings → Integrations → UK Fuel Prices**.
2. Give each saved station its postcode — that is what stations are matched on
   the first time. Where a postcode covers more than one forecourt, coordinates
   (if set) and then brand break the tie.
3. Once a station has been matched, May remembers which forecourt it stands for
   and goes straight to it on later refreshes, so a station keeps reporting the
   same forecourt even if its postcode is edited. A remembered forecourt that
   drops out of the feed is reported as unmatched rather than quietly resolving
   to a different one.
4. Prices refresh in the background every six hours, and on demand with the
   **Update UK Prices** button on the Fuel Stations page or on a single
   station's price history.

Prices are stored one row per station, fuel type and day, so re-running the
refresh updates the day's entry rather than adding duplicates. Premium grades
are recorded separately (E5 as "Petrol Premium", SDV as "Diesel Premium").

The built-in retailer list follows the gov.uk guidance page. Retailers join and
leave the scheme, so the settings panel takes an optional override — one feed
per line, either `Retailer name|https://...` or a bare URL. A feed that is
unreachable is reported and the rest still apply.

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

## 🌍 Supported Languages

May is available in the following languages:

| Language | Code | Language | Code |
|----------|------|----------|------|
| English | `en` | Swedish (Svenska) | `sv` |
| German (Deutsch) | `de` | Danish (Dansk) | `da` |
| Spanish (Español) | `es` | Norwegian (Norsk) | `no` |
| French (Français) | `fr` | Finnish (Suomi) | `fi` |
| Italian (Italiano) | `it` | Japanese (日本語) | `ja` |
| Dutch (Nederlands) | `nl` | Chinese (中文) | `zh` |
| Portuguese (Português) | `pt` | Korean (한국어) | `ko` |
| Polish (Polski) | `pl` | Czech (Čeština) | `cs` |
| Russian (Русский) | `ru` | Turkish (Türkçe) | `tr` |
| Arabic (العربية) | `ar` | Hungarian (Magyar) | `hu` |

You can change your language in **Settings > Units & Values > Language**.

### Improving Translations

Translations were generated with AI assistance and may contain inaccuracies. If you spot an incorrect translation, contributions are very welcome:

1. Translation files are located in `app/translations/<lang>/LC_MESSAGES/messages.po`
2. Edit the `msgstr` value for any incorrect entry
3. Submit a pull request with your fix

### Adding a Language

A new catalogue is not offered until the language is registered:

1. Create `app/translations/<lang>/LC_MESSAGES/messages.po` from
   `app/translations/messages.pot` and translate it
2. Compile it with `pybabel compile -d app/translations` so a `messages.mo`
   sits beside the `.po`
3. Add the code and its native name to `LANGUAGES` in `app/__init__.py` — this
   is what the settings picker and the browser language negotiation read, so a
   catalogue that is not listed there can never be selected
4. Add the language to the table above

## 🛠️ Tech Stack

- **Backend**: Python / Flask
- **Database**: SQLite (easily swappable)
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
- Ensure the directory exists and is writable
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
