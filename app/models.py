import secrets
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from flask_babel import lazy_gettext as _l
from app import db

# Currency symbols for display in UI
CURRENCY_SYMBOLS = {
    'USD': '$',
    'EUR': '\u20ac',
    'GBP': '\u00a3',
    'AUD': '$',
    'CAD': '$',
    'INR': '\u20b9',
    'JPY': '\u00a5',
    'CHF': 'Fr',
    'NZD': '$',
    'SEK': 'kr',
    'NOK': 'kr',
    'DKK': 'kr',
    'PLN': 'z\u0142',
    'BRL': 'R$',
    'MXN': '$',
    'ZAR': 'R',
}


def get_currency_symbol(currency_code):
    if not currency_code:
        return ''
    code = currency_code.strip().upper()
    return CURRENCY_SYMBOLS.get(code, currency_code)


# Association table for vehicle sharing
vehicle_users = db.Table('vehicle_users',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('vehicle_id', db.Integer, db.ForeignKey('vehicles.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # User preferences
    language = db.Column(db.String(10), default='en')  # en, de, fr, es, etc.
    distance_unit = db.Column(db.String(10), default='km')  # km, mi
    volume_unit = db.Column(db.String(10), default='L')  # L, gal, us_gal
    consumption_unit = db.Column(db.String(10), default='L/100km')  # L/100km, mpg, mpg_us
    currency = db.Column(db.String(10), default='USD')
    dark_mode = db.Column(db.Boolean, default=False)  # Dark mode preference
    date_format = db.Column(db.String(20), default='DD/MM/YYYY')  # DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD.MM.YYYY

    # Notification preferences
    email_reminders = db.Column(db.Boolean, default=True)
    reminder_days_before = db.Column(db.Integer, default=7)  # Days before due date to notify
    notification_method = db.Column(db.String(20), default='email')  # email, webhook, ntfy, pushover, none
    webhook_url = db.Column(db.String(500))  # URL to POST notifications to
    ntfy_topic = db.Column(db.String(200))  # ntfy.sh topic or custom server URL
    pushover_user_key = db.Column(db.String(50))  # Pushover user key

    # Password reset
    password_reset_token = db.Column(db.String(100), unique=True, index=True)
    password_reset_expires = db.Column(db.DateTime)

    # API access
    api_key = db.Column(db.String(64), unique=True, index=True)
    api_key_created_at = db.Column(db.DateTime)

    # Menu preferences
    start_page = db.Column(db.String(50), default='dashboard')  # dashboard, vehicles, fuel, expenses, etc.
    default_vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=True)
    show_menu_vehicles = db.Column(db.Boolean, default=True)
    show_menu_fuel = db.Column(db.Boolean, default=True)
    show_menu_expenses = db.Column(db.Boolean, default=True)
    show_menu_reminders = db.Column(db.Boolean, default=True)
    show_menu_maintenance = db.Column(db.Boolean, default=True)
    show_menu_recurring = db.Column(db.Boolean, default=True)
    show_menu_documents = db.Column(db.Boolean, default=True)
    show_menu_stations = db.Column(db.Boolean, default=True)
    show_menu_trips = db.Column(db.Boolean, default=True)
    show_menu_charging = db.Column(db.Boolean, default=True)
    show_quick_entry = db.Column(db.Boolean, default=False)  # Show quick entry button in navbar

    # Relationships
    owned_vehicles = db.relationship('Vehicle', backref='owner', lazy='dynamic',
                                     foreign_keys='Vehicle.owner_id')
    shared_vehicles = db.relationship('Vehicle', secondary=vehicle_users,
                                      backref=db.backref('shared_users', lazy='dynamic'))
    fuel_logs = db.relationship('FuelLog', backref='user', lazy='dynamic')
    expenses = db.relationship('Expense', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_all_vehicles(self):
        """Get all vehicles user has access to (owned + explicitly shared + instance-shared), sorted by make/model"""
        owned = list(self.owned_vehicles.all())
        shared = list(self.shared_vehicles)
        instance_shared = Vehicle.query.filter_by(is_shared=True).all()
        seen = set()
        unique = []
        for v in owned + shared + instance_shared:
            if v.id not in seen:
                seen.add(v.id)
                unique.append(v)
        return sorted(unique, key=lambda v: (v.make or '', v.model or '', v.name or ''))

    def generate_reset_token(self):
        """Generate a password reset token valid for 1 hour"""
        self.password_reset_token = secrets.token_urlsafe(48)
        self.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
        return self.password_reset_token

    def clear_reset_token(self):
        """Clear the password reset token"""
        self.password_reset_token = None
        self.password_reset_expires = None

    @staticmethod
    def get_by_reset_token(token):
        """Find user by valid (non-expired) reset token"""
        if not token:
            return None
        user = User.query.filter_by(password_reset_token=token).first()
        if user and user.password_reset_expires and user.password_reset_expires > datetime.utcnow():
            return user
        return None

    def generate_api_key(self):
        """Generate a new API key for this user"""
        self.api_key = f"may_{secrets.token_hex(32)}"
        self.api_key_created_at = datetime.utcnow()
        return self.api_key

    def revoke_api_key(self):
        """Revoke the current API key"""
        self.api_key = None
        self.api_key_created_at = None

    @staticmethod
    def get_by_api_key(api_key):
        """Find user by API key"""
        if not api_key:
            return None
        return User.query.filter_by(api_key=api_key).first()


class Vehicle(db.Model):
    __tablename__ = 'vehicles'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Basic info
    name = db.Column(db.String(100), nullable=False)
    vehicle_type = db.Column(db.String(20), nullable=False)  # car, van, motorbike, scooter
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.Integer)

    # Identification
    registration = db.Column(db.String(20))
    vin = db.Column(db.String(50))

    # Tracking unit (mileage or hours)
    tracking_unit = db.Column(db.String(20), default='mileage')  # mileage, hours

    # Per-vehicle odometer unit override (if None, falls back to user's distance_unit)
    odometer_unit = db.Column(db.String(10), default=None)  # km, mi, or None (use user preference)

    # Fuel info
    fuel_type = db.Column(db.String(20), default='petrol')  # petrol, diesel, electric, hybrid, lpg
    secondary_fuel_type = db.Column(db.String(20), nullable=True)  # e.g. adblue, lpg
    tank_capacity = db.Column(db.Float)  # in liters
    battery_capacity = db.Column(db.Float)  # in kWh for EVs

    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Image
    image_filename = db.Column(db.String(255))

    # Notes
    notes = db.Column(db.Text)

    # DVLA data (UK vehicles)
    mot_status = db.Column(db.String(50))  # Valid, Not valid, No details held
    mot_expiry = db.Column(db.Date)
    tax_status = db.Column(db.String(50))  # Taxed, Untaxed, SORN, etc.
    tax_due = db.Column(db.Date)
    dvla_colour = db.Column(db.String(50))  # Colour from DVLA
    dvla_last_updated = db.Column(db.DateTime)  # When DVLA data was last fetched

    # Tessie integration (Tesla vehicles)
    tessie_vin = db.Column(db.String(20))  # VIN for Tessie API
    tessie_enabled = db.Column(db.Boolean, default=False)  # Enable Tessie odometer tracking
    tessie_last_odometer = db.Column(db.Float)  # Last fetched odometer in km
    tessie_battery_level = db.Column(db.Integer)  # Last fetched battery %
    tessie_battery_range = db.Column(db.Float)  # Last fetched range in km
    tessie_last_updated = db.Column(db.DateTime)  # When Tessie data was last fetched

    # Annual mileage tracking
    annual_mileage_limit = db.Column(db.Float, nullable=True)
    annual_mileage_start_date = db.Column(db.Date, nullable=True)

    # Sharing — if True, all users on this instance can view and log against this vehicle
    is_shared = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    fuel_logs = db.relationship('FuelLog', backref='vehicle', lazy='dynamic',
                                cascade='all, delete-orphan')
    expenses = db.relationship('Expense', backref='vehicle', lazy='dynamic',
                               cascade='all, delete-orphan')
    attachments = db.relationship('Attachment', backref='vehicle', lazy='dynamic',
                                  cascade='all, delete-orphan')
    specs = db.relationship('VehicleSpec', backref='vehicle', lazy='dynamic',
                            cascade='all, delete-orphan')
    trips = db.relationship('Trip', backref='vehicle', lazy='dynamic',
                            cascade='all, delete-orphan')
    charging_sessions = db.relationship('ChargingSession', backref='vehicle', lazy='dynamic',
                                        cascade='all, delete-orphan')

    def get_effective_odometer_unit(self):
        """Return the odometer unit for this vehicle.

        Uses the vehicle's own odometer_unit if set, otherwise falls back to
        the owner's distance_unit preference.
        """
        if self.odometer_unit:
            return self.odometer_unit
        if self.owner:
            return self.owner.distance_unit
        return 'km'

    def get_total_fuel_cost(self):
        return sum(log.total_cost for log in self.fuel_logs.all() if log.total_cost)

    def get_total_expense_cost(self):
        return sum(exp.cost for exp in self.expenses.all() if exp.cost)

    def get_total_cost(self):
        return self.get_total_fuel_cost() + self.get_total_expense_cost() + self.get_total_charging_cost()

    @property
    def vehicle_type_label(self):
        return dict(VEHICLE_TYPES).get(self.vehicle_type, self.vehicle_type.replace('_', ' ').title())

    @property
    def currency_symbol(self):
        return get_currency_symbol(self.owner.currency if self.owner else None)

    def get_total_distance(self, distance_unit=None):
        """Get total distance for the vehicle.

        If Tessie is enabled, returns the current odometer reading.
        Otherwise, calculates from fuel log entries.

        Args:
            distance_unit: If provided ('km' or 'mi'), converts the result
                to this unit. Otherwise returns the raw value in the
                vehicle's effective odometer unit.
        """
        # If Tessie is enabled, use the odometer reading directly (always stored in km)
        if self.uses_tessie_odometer() and self.tessie_last_odometer:
            odometer = self.tessie_last_odometer
            if distance_unit == 'mi':
                return odometer * 0.621371
            return odometer

        # Otherwise calculate from fuel logs, stored in the vehicle's odometer unit
        logs = self.fuel_logs.order_by(FuelLog.odometer).all()
        if len(logs) < 2:
            return 0
        raw_distance = logs[-1].odometer - logs[0].odometer
        if distance_unit:
            return _distance_in(raw_distance, self.get_effective_odometer_unit(), distance_unit)
        return raw_distance

    def get_average_consumption(self, consumption_unit=None, volume_unit='L'):
        """Calculate average fuel consumption between the first and last
        full-tank fill-ups.

        Sums every litre poured between those two anchors so partial fills
        in the middle are counted (issue #169). Returns None when any log
        in the range is flagged ``is_missed`` — we have no way to make the
        figure honest in that case.
        """
        full_logs = self.fuel_logs.filter_by(is_full_tank=True).order_by(FuelLog.odometer).all()
        if len(full_logs) < 2:
            return None

        first_odo = full_logs[0].odometer
        last_odo = full_logs[-1].odometer
        range_logs = self.fuel_logs.filter(
            FuelLog.odometer > first_odo,
            FuelLog.odometer <= last_odo,
        ).all()
        if any(log.is_missed for log in range_logs):
            return None

        total_fuel = sum(log.volume for log in range_logs if log.volume)
        total_distance = last_odo - first_odo

        if total_distance > 0 and total_fuel > 0:
            odometer_unit = self.get_effective_odometer_unit()
            if consumption_unit == 'mpg':
                miles = _distance_in(total_distance, odometer_unit, 'mi')
                gallons = _to_uk_gallons(total_fuel, volume_unit)
                return miles / gallons if gallons > 0 else None
            if consumption_unit == 'mpg_us':
                miles = _distance_in(total_distance, odometer_unit, 'mi')
                gallons = _to_us_gallons(total_fuel, volume_unit)
                return miles / gallons if gallons > 0 else None
            km = _distance_in(total_distance, odometer_unit, 'km')
            litres = _to_litres(total_fuel, volume_unit)
            return (litres / km) * 100  # L/100km
        return None

    def uses_tessie_odometer(self):
        """Check if this vehicle uses Tessie for odometer tracking"""
        from app.services.tessie import TessieService
        return (self.tessie_enabled and
                self.tessie_vin and
                TessieService.is_configured())

    def get_last_odometer(self, distance_unit=None):
        """Get the most recent odometer reading.

        If Tessie is enabled for this vehicle, returns the Tessie odometer.
        Otherwise, returns the highest from fuel logs, trips, or charging sessions.

        Args:
            distance_unit: If provided ('km' or 'mi'), converts Tessie odometer to this unit.
                          Tessie odometer is stored in km internally.
        """
        # If Tessie is enabled, use Tessie odometer exclusively
        if self.uses_tessie_odometer() and self.tessie_last_odometer:
            odometer = self.tessie_last_odometer
            # Convert from km to user's unit if specified
            if distance_unit == 'mi':
                odometer = odometer * 0.621371
            return round(odometer)

        last_fuel = self.fuel_logs.order_by(FuelLog.odometer.desc()).first()
        fuel_odo = last_fuel.odometer if last_fuel else 0

        last_trip = self.trips.filter(Trip.end_odometer.isnot(None)).order_by(Trip.end_odometer.desc()).first()
        trip_odo = last_trip.end_odometer if last_trip else 0

        last_charge = self.charging_sessions.filter(ChargingSession.odometer.isnot(None)).order_by(
            ChargingSession.odometer.desc()).first()
        charge_odo = last_charge.odometer if last_charge else 0

        return max(fuel_odo, trip_odo, charge_odo)

    def get_total_charging_cost(self):
        """Get total cost of all charging sessions"""
        return sum(session.total_cost for session in self.charging_sessions.all() if session.total_cost) or 0

    def get_total_charging_kwh(self):
        """Total energy delivered across all charging sessions (kWh)."""
        return sum(s.kwh_added for s in self.charging_sessions.all() if s.kwh_added) or 0

    def get_average_charging_consumption(self, distance_unit=None):
        """Mean energy consumption between the first and last charging sessions
        that have odometer readings.

        Returns kWh per 100 distance units in ``distance_unit`` (falls back to
        the vehicle's odometer unit). Mirrors the fill-to-fill approach used
        for fuel: needs at least two anchor sessions with odometers, and sums
        every charge in between.
        """
        sessions = (self.charging_sessions
                    .filter(ChargingSession.odometer.isnot(None))
                    .order_by(ChargingSession.odometer)
                    .all())
        if len(sessions) < 2:
            return None
        first_odo, last_odo = sessions[0].odometer, sessions[-1].odometer
        raw_distance = last_odo - first_odo
        if raw_distance <= 0:
            return None
        total_kwh = sum(s.kwh_added for s in sessions if s.kwh_added) or 0
        if total_kwh <= 0:
            return None
        target = distance_unit or self.get_effective_odometer_unit()
        distance = _distance_in(raw_distance, self.get_effective_odometer_unit(), target)
        return (total_kwh / distance) * 100 if distance > 0 else None

    def get_cost_per_kwh(self):
        """Average cost per kWh across all charging sessions with data."""
        total_kwh = self.get_total_charging_kwh()
        if total_kwh <= 0:
            return None
        return self.get_total_charging_cost() / total_kwh

    def get_total_trip_distance(self):
        """Get total distance from all trips"""
        return sum(trip.distance for trip in self.trips.all()) or 0

    def get_cost_per_distance(self):
        """Calculate total cost of ownership per distance unit"""
        total_cost = self.get_total_fuel_cost() + self.get_total_expense_cost() + self.get_total_charging_cost()
        total_distance = self.get_total_distance()
        if total_distance > 0:
            return total_cost / total_distance
        return None

    def is_electric(self):
        """Check if vehicle uses any electric propulsion"""
        return self.fuel_type in ('electric', 'plugin_hybrid', 'hybrid')

    def uses_charging(self):
        """Check if vehicle can be plugged in for charging (pure EV or plug-in hybrid)"""
        return self.fuel_type in ('electric', 'plugin_hybrid')

    def uses_fuel(self):
        """Check if vehicle uses liquid fuel (not pure electric)"""
        return self.fuel_type != 'electric'

    def get_annual_mileage_stats(self):
        """Return mileage tracking stats for the current annual period, or None if not configured."""
        if not self.annual_mileage_limit or not self.annual_mileage_start_date:
            return None

        from datetime import date as date_type

        today = date_type.today()
        limit = self.annual_mileage_limit
        start = self.annual_mileage_start_date

        # Find the most recent anniversary of start that is <= today
        period_year = today.year
        try:
            candidate = start.replace(year=period_year)
        except ValueError:
            candidate = start.replace(year=period_year, day=28)
        if candidate > today:
            period_year -= 1
            try:
                candidate = start.replace(year=period_year)
            except ValueError:
                candidate = start.replace(year=period_year, day=28)
        period_start = candidate

        try:
            period_end = start.replace(year=period_year + 1)
        except ValueError:
            period_end = start.replace(year=period_year + 1, day=28)

        days_total = (period_end - period_start).days
        days_elapsed = max(0, (today - period_start).days)
        days_remaining = max(0, (period_end - today).days)

        # Baseline: last odometer reading before this period
        baseline_log = (self.fuel_logs
                        .filter(FuelLog.date < period_start)
                        .order_by(FuelLog.date.desc(), FuelLog.odometer.desc())
                        .first())
        current_log = (self.fuel_logs
                       .order_by(FuelLog.date.desc(), FuelLog.odometer.desc())
                       .first())

        if not current_log:
            driven = 0.0
        elif baseline_log:
            driven = max(0.0, current_log.odometer - baseline_log.odometer)
        else:
            first_log = (self.fuel_logs
                         .filter(FuelLog.date >= period_start)
                         .order_by(FuelLog.date.asc(), FuelLog.odometer.asc())
                         .first())
            if first_log and current_log.id != first_log.id:
                driven = max(0.0, current_log.odometer - first_log.odometer)
            else:
                driven = 0.0

        remaining = max(0.0, limit - driven)
        progress_pct = min(100.0, round(driven / limit * 100, 1)) if limit > 0 else 0.0
        time_pct = round(days_elapsed / days_total * 100, 1) if days_total > 0 else 0.0
        expected = round(limit / days_total * days_elapsed) if days_total > 0 else 0
        projected = round(driven / days_elapsed * days_total) if days_elapsed > 0 else 0

        return {
            'limit': limit,
            'period_start': period_start,
            'period_end': period_end,
            'days_total': days_total,
            'days_elapsed': days_elapsed,
            'days_remaining': days_remaining,
            'driven': round(driven),
            'remaining': round(remaining),
            'projected': projected,
            'on_pace': projected <= limit,
            'over_limit': driven >= limit,
            'progress_pct': progress_pct,
            'time_pct': time_pct,
            'expected': expected,
        }

    def to_dict(self):
        """Serialize vehicle to dictionary for API"""
        return {
            'id': self.id,
            'name': self.name,
            'vehicle_type': self.vehicle_type,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'registration': self.registration,
            'vin': self.vin,
            'fuel_type': self.fuel_type,
            'secondary_fuel_type': self.secondary_fuel_type,
            'tank_capacity': self.tank_capacity,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'stats': {
                'total_fuel_cost': round(self.get_total_fuel_cost(), 2),
                'total_expense_cost': round(self.get_total_expense_cost(), 2),
                'total_distance': round(self.get_total_distance(), 2),
                'average_consumption': round(avg, 2) if (avg := self.get_average_consumption()) else None,
                'last_odometer': self.get_last_odometer()
            }
        }


def _to_litres(volume, volume_unit):
    if volume_unit == 'gal':
        return volume * 4.54609
    if volume_unit == 'us_gal':
        return volume * 3.78541
    return volume  # already litres


def _to_uk_gallons(volume, volume_unit):
    if volume_unit == 'gal':
        return volume
    if volume_unit == 'us_gal':
        return volume * 3.78541 / 4.54609
    return volume / 4.54609  # litres to UK gallons


def _to_us_gallons(volume, volume_unit):
    if volume_unit == 'us_gal':
        return volume
    if volume_unit == 'gal':
        return volume * 4.54609 / 3.78541
    return volume / 3.78541  # litres to US gallons


def _distance_in(distance, from_unit, to_unit):
    if from_unit == to_unit:
        return distance
    if from_unit == 'km' and to_unit == 'mi':
        return distance * 0.621371
    if from_unit == 'mi' and to_unit == 'km':
        return distance * 1.609344
    return distance


class FuelLog(db.Model):
    __tablename__ = 'fuel_logs'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    odometer = db.Column(db.Float, nullable=False)  # stored in km
    volume = db.Column(db.Float)  # stored in liters
    price_per_unit = db.Column(db.Float)  # price per liter
    total_cost = db.Column(db.Float)

    fuel_type = db.Column(db.String(20), nullable=True)  # overrides vehicle primary; set when vehicle has secondary fuel type
    is_full_tank = db.Column(db.Boolean, default=True)
    is_missed = db.Column(db.Boolean, default=False)  # missed fill-up flag

    station = db.Column(db.String(100))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    attachments = db.relationship('Attachment', backref='fuel_log', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def get_consumption(self, consumption_unit=None, volume_unit='L'):
        """Calculate consumption for this fill-up.

        Only meaningful for full-tank fills: sum every litre poured between
        the previous full tank and this one (inclusive) and divide by the
        distance covered — the "fill-to-fill" method. Partial fills between
        two full tanks are therefore counted in the next full tank's figure
        (issue #169). If any of the intervening logs is flagged ``is_missed``,
        the figure is unknowable and we return None.

        Partial fills return None: the litres added in a top-up tell you
        nothing about consumption over the preceding distance, and surfacing
        a number there is misleading (issue #194).
        """
        if not self.volume or not self.is_full_tank:
            return None

        prev_full = FuelLog.query.filter(
            FuelLog.vehicle_id == self.vehicle_id,
            FuelLog.odometer < self.odometer,
            FuelLog.is_full_tank == True,
        ).order_by(FuelLog.odometer.desc()).first()
        if not prev_full:
            return None
        distance = self.odometer - prev_full.odometer
        between = FuelLog.query.filter(
            FuelLog.vehicle_id == self.vehicle_id,
            FuelLog.odometer > prev_full.odometer,
            FuelLog.odometer <= self.odometer,
        ).all()
        if any(log.is_missed for log in between):
            return None
        volume_native = sum(log.volume for log in between if log.volume)

        if distance > 0 and volume_native > 0:
            odometer_unit = self.vehicle.get_effective_odometer_unit()
            if consumption_unit == 'mpg':
                miles = _distance_in(distance, odometer_unit, 'mi')
                gallons = _to_uk_gallons(volume_native, volume_unit)
                return miles / gallons if gallons > 0 else None
            if consumption_unit == 'mpg_us':
                miles = _distance_in(distance, odometer_unit, 'mi')
                gallons = _to_us_gallons(volume_native, volume_unit)
                return miles / gallons if gallons > 0 else None
            km = _distance_in(distance, odometer_unit, 'km')
            litres = _to_litres(volume_native, volume_unit)
            return (litres / km) * 100  # L/100km
        return None

    def to_dict(self, consumption_unit=None, volume_unit='L'):
        """Serialize fuel log to dictionary for API"""
        consumption = self.get_consumption(consumption_unit, volume_unit)
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'odometer': self.odometer,
            'volume': self.volume,
            'price_per_unit': self.price_per_unit,
            'total_cost': self.total_cost,
            'is_full_tank': self.is_full_tank,
            'is_missed': self.is_missed,
            'station': self.station,
            'notes': self.notes,
            'consumption': round(consumption, 2) if consumption else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Expense(db.Model):
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    category = db.Column(db.String(50), nullable=False)  # maintenance, insurance, repairs, tax, parking, tolls, other
    description = db.Column(db.String(200), nullable=False)
    cost = db.Column(db.Float, nullable=False)
    odometer = db.Column(db.Float)  # optional

    vendor = db.Column(db.String(100))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    attachments = db.relationship('Attachment', backref='expense', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def to_dict(self):
        """Serialize expense to dictionary for API"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'category': self.category,
            'description': self.description,
            'cost': self.cost,
            'odometer': self.odometer,
            'vendor': self.vendor,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Attachment(db.Model):
    __tablename__ = 'attachments'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)

    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'))
    fuel_log_id = db.Column(db.Integer, db.ForeignKey('fuel_logs.id'))
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'))

    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class VehicleSpec(db.Model):
    """Custom specifications/attributes for vehicles"""
    __tablename__ = 'vehicle_specs'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)

    spec_type = db.Column(db.String(50), nullable=False)  # predefined or custom type
    label = db.Column(db.String(100), nullable=False)  # display label
    value = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Reminder(db.Model):
    """Reminders for vehicle-related dates and events"""
    __tablename__ = 'reminders'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    reminder_type = db.Column(db.String(50), nullable=False)  # service, mot, insurance, tax, custom
    due_date = db.Column(db.Date, nullable=False)

    # Relationships (defined here since this class is defined last)
    vehicle = db.relationship('Vehicle', backref=db.backref('reminders', lazy='dynamic', cascade='all, delete-orphan'))
    user_rel = db.relationship('User', backref=db.backref('reminders', lazy='dynamic'))

    # Recurrence settings
    recurrence = db.Column(db.String(20), default='none')  # none, monthly, yearly
    recurrence_interval = db.Column(db.Integer, default=1)  # e.g., every 1 year, every 6 months

    # Notification settings
    notify_days_before = db.Column(db.Integer, default=7)
    notification_sent = db.Column(db.Boolean, default=False)

    # Status
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)

    # Tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_overdue(self):
        """Check if reminder is past due date"""
        from datetime import date
        return not self.is_completed and self.due_date < date.today()

    def is_upcoming(self, days=7):
        """Check if reminder is coming up within specified days"""
        from datetime import date, timedelta
        if self.is_completed:
            return False
        today = date.today()
        return today <= self.due_date <= today + timedelta(days=days)

    def days_until_due(self):
        """Calculate days until due date"""
        from datetime import date
        return (self.due_date - date.today()).days

    def to_dict(self):
        """Serialize reminder to dictionary"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'title': self.title,
            'description': self.description,
            'reminder_type': self.reminder_type,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'recurrence': self.recurrence,
            'is_completed': self.is_completed,
            'is_overdue': self.is_overdue(),
            'days_until_due': self.days_until_due(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class AppSettings(db.Model):
    """Application-wide settings for branding and customization"""
    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        """Get a setting value by key"""
        setting = AppSettings.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set(key, value):
        """Set a setting value"""
        setting = AppSettings.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = AppSettings(key=key, value=value)
            db.session.add(setting)
        db.session.commit()
        return setting

    @staticmethod
    def get_all_branding():
        """Get all branding settings as a dictionary"""
        defaults = {
            'app_name': 'May',
            'app_tagline': 'Vehicle Management',
            'primary_color': '#0284c7',
            'logo_filename': None,
            'favicon_filename': None,
        }
        settings = AppSettings.query.filter(AppSettings.key.in_(defaults.keys())).all()
        result = defaults.copy()
        for s in settings:
            result[s.key] = s.value
        return result


# Predefined vehicle specification types
VEHICLE_SPEC_TYPES = [
    ('tire_size_front', _l('Front Tire Size')),
    ('tire_size_rear', _l('Rear Tire Size')),
    ('wheel_size', _l('Wheel Size')),
    ('oil_type', _l('Engine Oil Type')),
    ('oil_capacity', _l('Oil Capacity')),
    ('coolant_type', _l('Coolant Type')),
    ('wiper_front', _l('Front Wiper Size')),
    ('wiper_rear', _l('Rear Wiper Size')),
    ('battery_type', _l('Battery Type')),
    ('spark_plug', _l('Spark Plug Type')),
    ('air_filter', _l('Air Filter Part #')),
    ('cabin_filter', _l('Cabin Filter Part #')),
    ('brake_pads_front', _l('Front Brake Pads')),
    ('brake_pads_rear', _l('Rear Brake Pads')),
    ('transmission_fluid', _l('Transmission Fluid')),
    ('custom', _l('Custom')),
]

# Expense categories
EXPENSE_CATEGORIES = [
    ('maintenance', _l('Maintenance')),
    ('repairs', _l('Repairs')),
    ('inspection', _l('Inspection')),
    ('insurance', _l('Insurance')),
    ('tax', _l('Road Tax')),
    ('registration', _l('Registration')),
    ('parking', _l('Parking')),
    ('tolls', _l('Tolls')),
    ('cleaning', _l('Cleaning')),
    ('accessories', _l('Accessories')),
    ('other', _l('Other'))
]

# Vehicle types
VEHICLE_TYPES = [
    ('car', _l('Car')),
    ('van', _l('Van')),
    ('motorbike', _l('Motorbike')),
    ('scooter', _l('Scooter')),
    ('truck', _l('Truck')),
    ('suv', _l('SUV')),
    ('hatchback', _l('Hatchback')),
    ('station_wagon', _l('Station Wagon / Estate')),
    ('pickup', _l('Pickup / Ute')),
    ('tractor', _l('Tractor')),
    ('atv_utv', _l('ATV/UTV')),
    ('boat', _l('Boat')),
    ('other', _l('Other'))
]

# Tracking unit options
TRACKING_UNITS = [
    ('mileage', _l('Mileage (km/mi)')),
    ('hours', _l('Hours')),
]

# Odometer unit options (for per-vehicle override)
ODOMETER_UNITS = [
    ('km', _l('Kilometres (km)')),
    ('mi', _l('Miles (mi)')),
]

# Fuel types
FUEL_TYPES = [
    ('petrol', _l('Petrol/Gasoline')),
    ('diesel', _l('Diesel')),
    ('electric', _l('Electric')),
    ('hybrid', _l('Hybrid')),
    ('plugin_hybrid', _l('Plug-in Hybrid')),
    ('lpg', _l('LPG')),
    ('cng', _l('CNG')),
    ('hydrogen', _l('Hydrogen')),
    ('e85', _l('E85/Flex Fuel')),
    ('other', _l('Other'))
]

# Reminder types
REMINDER_TYPES = [
    ('mot', _l('MOT/Inspection')),
    ('service', _l('Service Due')),
    ('insurance', _l('Insurance Renewal')),
    ('tax', _l('Road Tax')),
    ('registration', _l('Registration Renewal')),
    ('warranty', _l('Warranty Expiry')),
    ('tire_change', _l('Tire Change')),
    ('oil_change', _l('Oil Change')),
    ('custom', _l('Custom'))
]

# Recurrence options. The legacy values (quarterly, biannual) remain accepted on
# read so saved reminders keep working; new reminders use a unit + interval pair
# (see Reminder.recurrence_interval).
RECURRENCE_OPTIONS = [
    ('none', _l('No Repeat')),
    ('daily', _l('Day(s)')),
    ('weekly', _l('Week(s)')),
    ('monthly', _l('Month(s)')),
    ('yearly', _l('Year(s)')),
]

# Trip purposes for tax deductions
TRIP_PURPOSES = [
    ('business', _l('Business')),
    ('personal', _l('Personal')),
    ('commute', _l('Commute')),
    ('medical', _l('Medical')),
    ('charity', _l('Charity')),
    ('other', _l('Other')),
]

# EV charger types
CHARGER_TYPES = [
    ('home', _l('Home Charging')),
    ('level1', _l('Level 1')),
    ('level2', _l('Level 2')),
    ('dcfc', _l('DC Fast Charge')),
    ('tesla', _l('Tesla Supercharger')),
    ('other', _l('Other')),
]

# Maintenance schedule types
MAINTENANCE_TYPES = [
    ('oil_change', _l('Oil Change')),
    ('oil_filter', _l('Oil Filter')),
    ('air_filter', _l('Air Filter')),
    ('cabin_filter', _l('Cabin/Pollen Filter')),
    ('fuel_filter', _l('Fuel Filter')),
    ('spark_plugs', _l('Spark Plugs')),
    ('brake_pads', _l('Brake Pads')),
    ('brake_fluid', _l('Brake Fluid')),
    ('coolant', _l('Coolant Flush')),
    ('transmission', _l('Transmission Service')),
    ('timing_belt', _l('Timing Belt')),
    ('serpentine_belt', _l('Serpentine Belt')),
    ('tire_rotation', _l('Tire Rotation')),
    ('wheel_alignment', _l('Wheel Alignment')),
    ('battery', _l('Battery Check/Replace')),
    ('wiper_blades', _l('Wiper Blades')),
    ('full_service', _l('Full Service')),
    ('custom', _l('Custom')),
]

# Document types
DOCUMENT_TYPES = [
    ('insurance', _l('Insurance Policy')),
    ('registration', _l('Registration/V5C')),
    ('mot', _l('MOT Certificate')),
    ('service_record', _l('Service Record')),
    ('purchase', _l('Purchase Invoice')),
    ('warranty', _l('Warranty Document')),
    ('manual', _l("Owner's Manual")),
    ('other', _l('Other')),
]


class MaintenanceSchedule(db.Model):
    """Predefined maintenance schedules with mileage/time intervals"""
    __tablename__ = 'maintenance_schedules'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)
    maintenance_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)

    # Interval settings (either or both)
    interval_miles = db.Column(db.Integer)  # e.g., every 5000 miles
    interval_km = db.Column(db.Integer)  # e.g., every 8000 km
    interval_months = db.Column(db.Integer)  # e.g., every 12 months

    # Last performed
    last_performed_date = db.Column(db.Date)
    last_performed_odometer = db.Column(db.Float)

    # Next due (calculated or manually set)
    next_due_date = db.Column(db.Date)
    next_due_odometer = db.Column(db.Float)

    # Estimated cost for budgeting
    estimated_cost = db.Column(db.Float)

    # Auto-create reminder when due
    auto_remind = db.Column(db.Boolean, default=True)
    remind_days_before = db.Column(db.Integer, default=14)
    remind_miles_before = db.Column(db.Integer, default=500)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    vehicle = db.relationship('Vehicle', backref=db.backref('maintenance_schedules', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('maintenance_schedules', lazy='dynamic'))

    def calculate_next_due(self):
        """Calculate next due date/odometer based on intervals"""
        from datetime import date
        from dateutil.relativedelta import relativedelta

        if self.last_performed_date and self.interval_months:
            self.next_due_date = self.last_performed_date + relativedelta(months=self.interval_months)

        if self.last_performed_odometer:
            if self.interval_km:
                self.next_due_odometer = self.last_performed_odometer + self.interval_km
            elif self.interval_miles:
                self.next_due_odometer = self.last_performed_odometer + (self.interval_miles * 1.60934)

    def is_due(self, current_odometer=None):
        """Check if maintenance is due"""
        from datetime import date

        # Check date-based
        if self.next_due_date and self.next_due_date <= date.today():
            return True

        # Check odometer-based
        if self.next_due_odometer and current_odometer:
            if current_odometer >= self.next_due_odometer:
                return True

        return False

    def is_due_soon(self, current_odometer=None, days=14, distance=500):
        """Check if maintenance is due soon"""
        from datetime import date, timedelta

        # Check date-based
        if self.next_due_date:
            if self.next_due_date <= date.today() + timedelta(days=days):
                return True

        # Check odometer-based
        if self.next_due_odometer and current_odometer:
            if current_odometer >= (self.next_due_odometer - distance):
                return True

        return False


class RecurringExpense(db.Model):
    """Recurring expenses that auto-generate expense entries"""
    __tablename__ = 'recurring_expenses'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    amount = db.Column(db.Float, nullable=True)
    vendor = db.Column(db.String(100))

    # Recurrence settings
    frequency = db.Column(db.String(20), nullable=False)  # weekly, monthly, quarterly, yearly
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)  # optional end date

    # Tracking
    last_generated = db.Column(db.Date)
    next_due = db.Column(db.Date)

    # Auto-create setting
    auto_create = db.Column(db.Boolean, default=True)  # auto-create expense when due
    notify_before_days = db.Column(db.Integer, default=3)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    vehicle = db.relationship('Vehicle', backref=db.backref('recurring_expenses', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('recurring_expenses', lazy='dynamic'))

    def calculate_next_due(self):
        """Calculate next due date based on frequency"""
        from datetime import date
        from dateutil.relativedelta import relativedelta

        base_date = self.last_generated or self.start_date

        if self.frequency == 'weekly':
            self.next_due = base_date + relativedelta(weeks=1)
        elif self.frequency == 'monthly':
            self.next_due = base_date + relativedelta(months=1)
        elif self.frequency == 'quarterly':
            self.next_due = base_date + relativedelta(months=3)
        elif self.frequency == 'yearly':
            self.next_due = base_date + relativedelta(years=1)

        # Check if past end date
        if self.end_date and self.next_due > self.end_date:
            self.is_active = False

    def is_due(self):
        """Check if recurring expense is overdue"""
        if not self.next_due or not self.is_active:
            return False
        return self.next_due <= date.today()

    def is_due_soon(self, days=None):
        """Check if recurring expense is due within notification window"""
        if not self.next_due or not self.is_active:
            return False
        if days is None:
            days = self.notify_before_days or 3
        today = date.today()
        return today <= self.next_due <= today + timedelta(days=days)


class FuelStation(db.Model):
    """Favorite fuel stations"""
    __tablename__ = 'fuel_stations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(50))  # Shell, BP, Esso, etc.
    address = db.Column(db.String(255))
    city = db.Column(db.String(100))
    postcode = db.Column(db.String(20))

    # Location
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    # Notes and preferences
    notes = db.Column(db.Text)
    is_favorite = db.Column(db.Boolean, default=False)

    # Usage tracking
    times_used = db.Column(db.Integer, default=0)
    last_used = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('fuel_stations', lazy='dynamic'))

    def increment_usage(self):
        """Increment usage counter when station is used"""
        self.times_used = (self.times_used or 0) + 1
        self.last_used = datetime.utcnow()


class Document(db.Model):
    """Document storage for vehicle-related documents"""
    __tablename__ = 'documents'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    title = db.Column(db.String(100), nullable=False)
    document_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)

    # File info
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)

    # Optional metadata
    issue_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    reference_number = db.Column(db.String(100))

    # Reminder for expiry
    remind_before_expiry = db.Column(db.Boolean, default=True)
    remind_days = db.Column(db.Integer, default=30)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    vehicle = db.relationship('Vehicle', backref=db.backref('documents', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('documents', lazy='dynamic'))

    def is_expiring_soon(self, days=30):
        """Check if document is expiring soon"""
        from datetime import date, timedelta
        if not self.expiry_date:
            return False
        return self.expiry_date <= date.today() + timedelta(days=days)

    def is_expired(self):
        """Check if document has expired"""
        from datetime import date
        if not self.expiry_date:
            return False
        return self.expiry_date < date.today()


class Trip(db.Model):
    """Trip logging for tax deductions and mileage tracking"""
    __tablename__ = 'trips'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    start_odometer = db.Column(db.Float, nullable=False)
    end_odometer = db.Column(db.Float, nullable=True)

    purpose = db.Column(db.String(20), nullable=False)  # business, personal, commute, etc.
    description = db.Column(db.String(200))
    start_location = db.Column(db.String(200))
    end_location = db.Column(db.String(200))

    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('trips', lazy='dynamic'))

    @property
    def distance(self):
        """Calculate trip distance"""
        if self.end_odometer is None or self.start_odometer is None:
            return 0
        return self.end_odometer - self.start_odometer

    def to_dict(self):
        """Serialize trip to dictionary for API"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'start_odometer': self.start_odometer,
            'end_odometer': self.end_odometer,
            'distance': self.distance,
            'purpose': self.purpose,
            'description': self.description,
            'start_location': self.start_location,
            'end_location': self.end_location,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class TripTemplate(db.Model):
    """Reusable trip templates for common routes"""
    __tablename__ = 'trip_templates'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=True)

    name = db.Column(db.String(100), nullable=False)
    purpose = db.Column(db.String(20), nullable=False)
    start_location = db.Column(db.String(200))
    end_location = db.Column(db.String(200))
    description = db.Column(db.String(200))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('trip_templates', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'name': self.name,
            'purpose': self.purpose,
            'start_location': self.start_location,
            'end_location': self.end_location,
            'description': self.description,
            'notes': self.notes,
        }


class ChargingSession(db.Model):
    """EV charging session logging"""
    __tablename__ = 'charging_sessions'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    odometer = db.Column(db.Float)

    kwh_added = db.Column(db.Float)  # Energy added in kWh
    start_soc = db.Column(db.Integer)  # Start state of charge (%)
    end_soc = db.Column(db.Integer)  # End state of charge (%)

    cost_per_kwh = db.Column(db.Float)
    total_cost = db.Column(db.Float)

    charger_type = db.Column(db.String(20))  # home, level1, level2, dcfc, tesla, other
    location = db.Column(db.String(200))  # Station name or "Home"
    network = db.Column(db.String(100))  # ChargePoint, Electrify America, etc.

    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Tessie integration - track imported charges
    tessie_charge_id = db.Column(db.String(50), unique=True, nullable=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('charging_sessions', lazy='dynamic'))

    def to_dict(self):
        """Serialize charging session to dictionary for API"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'odometer': self.odometer,
            'kwh_added': self.kwh_added,
            'start_soc': self.start_soc,
            'end_soc': self.end_soc,
            'cost_per_kwh': self.cost_per_kwh,
            'total_cost': self.total_cost,
            'charger_type': self.charger_type,
            'location': self.location,
            'network': self.network,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# Part types for vehicle parts catalog
PART_TYPES = [
    ('oil', _l('Engine Oil')),
    ('oil_filter', _l('Oil Filter')),
    ('air_filter', _l('Air Filter')),
    ('fuel_filter', _l('Fuel Filter')),
    ('cabin_filter', _l('Cabin Filter')),
    ('spark_plug', _l('Spark Plug')),
    ('brake_pad', _l('Brake Pad')),
    ('brake_fluid', _l('Brake Fluid')),
    ('coolant', _l('Coolant')),
    ('transmission_fluid', _l('Transmission Fluid')),
    ('battery', _l('Battery')),
    ('tire', _l('Tire')),
    ('belt', _l('Belt')),
    ('wiper', _l('Wiper Blade')),
    ('bulb', _l('Light Bulb')),
    ('other', _l('Other')),
]


class VehiclePart(db.Model):
    """Parts and consumables needed for servicing vehicles"""
    __tablename__ = 'vehicle_parts'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)  # "Engine Oil", "Oil Filter"
    part_type = db.Column(db.String(50), nullable=False)  # From PART_TYPES
    specification = db.Column(db.String(200))  # "10W-40", "K&N KN-204"

    quantity = db.Column(db.Float)  # 3.5
    unit = db.Column(db.String(20))  # "L", "ml", "units"

    part_number = db.Column(db.String(100))  # Manufacturer part number
    supplier_url = db.Column(db.String(500))  # Link to purchase
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    vehicle = db.relationship('Vehicle', backref=db.backref('parts', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('vehicle_parts', lazy='dynamic'))

    def to_dict(self):
        """Serialize part to dictionary"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'name': self.name,
            'part_type': self.part_type,
            'specification': self.specification,
            'quantity': self.quantity,
            'unit': self.unit,
            'part_number': self.part_number,
            'supplier_url': self.supplier_url,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class FuelPriceHistory(db.Model):
    """Historical fuel prices at stations"""
    __tablename__ = 'fuel_price_history'

    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('fuel_stations.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    fuel_type = db.Column(db.String(20), nullable=False)  # petrol, diesel, premium, etc.
    price_per_unit = db.Column(db.Float, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    station = db.relationship('FuelStation', backref=db.backref('price_history', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('fuel_price_history', lazy='dynamic'))
