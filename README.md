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
  ghcr.io/dannymcc/may:latest
```

Access the application at `http://localhost:5050`

**Default login:**
- Username: `admin`
- Password: `admin`

⚠️ **Change the default password after first login!**

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
DATABASE_URL=sqlite:///data/may.db

# Upload folder for attachments
UPLOAD_FOLDER=/app/data/uploads
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Session encryption key | Random |
| `DATABASE_URL` | Database connection string | `sqlite:///data/may.db` |
| `UPLOAD_FOLDER` | Path for file uploads | `/app/data/uploads` |

## 🎯 Usage

### Dashboard
The main dashboard shows an overview of all your vehicles with key statistics:
- Total fuel costs and consumption averages
- Recent fuel logs and expenses
- Upcoming reminders and overdue alerts

### Vehicles
Add and manage your vehicles with detailed information:
- Make, model, year, and registration
- Fuel type and tank capacity
- Custom specifications and notes
- Photo upload support

### Fuel Logs
Track every fill-up with:
- Date, odometer reading, and fuel amount
- Total cost and price per unit
- Full tank indicator for accurate consumption calculations
- Automatic MPG/L per 100km calculations

### Expenses
Categorize all vehicle-related costs:
- Maintenance & Repairs
- Insurance
- Tax & Registration
- Parking & Tolls
- Accessories
- Other expenses

### Reminders
Never miss important dates:
- MOT/Inspection due dates
- Service intervals
- Insurance renewals
- Tax payments
- Custom reminders with flexible recurrence

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
- Service manuals
- MOT certificates
- Any file type with expiry date tracking

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

---

**Made with ❤️ by [Danny McClelland](https://github.com/dannymcc)**
