import secrets
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from flask_babel import lazy_gettext as _l
from app import db
from app.utils import utcnow

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


# User roles (#285). Roles sit below the admin flag: an administrator always
# has full access, and every other account carries one of these roles.
#
#   editor      - the historic behaviour: full control of the data for every
#                 vehicle the account can see. This is the default.
#   contributor - may record fuel fill-ups and charging sessions, and nothing
#                 else. Intended for drivers.
#   viewer      - may read everything the account can see, but change nothing.
ROLE_EDITOR = 'editor'
ROLE_CONTRIBUTOR = 'contributor'
ROLE_VIEWER = 'viewer'

USER_ROLES = [
    (ROLE_EDITOR, _l('Editor')),
    (ROLE_CONTRIBUTOR, _l('Contributor')),
    (ROLE_VIEWER, _l('Viewer')),
]

USER_ROLE_DESCRIPTIONS = {
    ROLE_EDITOR: _l('Full access to the vehicles and data this account can see.'),
    ROLE_CONTRIBUTOR: _l('Can record fuel fill-ups and charging sessions. Everything else is read-only.'),
    ROLE_VIEWER: _l('Read-only. Can see the data but cannot change anything.'),
}

# The areas of the application a role may write to. Every write route belongs
# to exactly one of these scopes; see app/permissions.py for the mapping.
WRITE_SCOPES = (
    'vehicles', 'fuel', 'charging', 'expenses', 'maintenance', 'trips',
    'reminders', 'documents', 'notes', 'stations', 'recurring', 'allowance',
    'tires', 'import',
)

ROLE_WRITE_SCOPES = {
    ROLE_EDITOR: set(WRITE_SCOPES),
    ROLE_CONTRIBUTOR: {'fuel', 'charging'},
    ROLE_VIEWER: set(),
}


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
    role = db.Column(db.String(20), default=ROLE_EDITOR)  # editor, contributor, viewer (#285)
    created_at = db.Column(db.DateTime, default=utcnow)

    # User preferences
    language = db.Column(db.String(10), default='en')  # en, de, fr, es, etc.
    distance_unit = db.Column(db.String(10), default='km')  # km, mi
    volume_unit = db.Column(db.String(10), default='L')  # L, gal, us_gal
    consumption_unit = db.Column(db.String(10), default='L/100km')  # L/100km, mpg, mpg_us
    currency = db.Column(db.String(10), default='USD')
    dark_mode = db.Column(db.Boolean, default=False)  # Dark mode preference
    date_format = db.Column(db.String(20), default='DD/MM/YYYY')  # DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD.MM.YYYY
    # Number display (#134): grouping separator for large numbers and
    # optional whole-number rounding for money amounts
    thousand_separator = db.Column(db.String(10), default='none')  # none, space, comma, period
    round_costs = db.Column(db.Boolean, default=False)

    # Notification preferences
    email_reminders = db.Column(db.Boolean, default=True)
    reminder_days_before = db.Column(db.Integer, default=7)  # Days before due date to notify
    notification_method = db.Column(db.String(20), default='email')  # email, webhook, ntfy, pushover, none
    webhook_url = db.Column(db.String(500))  # URL to POST notifications to
    ntfy_topic = db.Column(db.String(200))  # ntfy.sh topic or custom server URL
    ntfy_token = db.Column(db.String(200))  # access token for authenticated ntfy servers (#90)
    pushover_user_key = db.Column(db.String(50))  # Pushover user key

    # Password reset
    password_reset_token = db.Column(db.String(100), unique=True, index=True)
    password_reset_expires = db.Column(db.DateTime)

    # API access
    api_key = db.Column(db.String(64), unique=True, index=True)
    api_key_created_at = db.Column(db.DateTime)

    # Menu preferences
    start_page = db.Column(db.String(50), default='dashboard')  # dashboard, vehicles, fuel, expenses, etc.
    # users and vehicles reference each other on purpose: a vehicle has an
    # owner, and a user may pin one of their vehicles as the default. The cycle
    # leaves SQLAlchemy unable to order the two tables for CREATE or DROP, so
    # this half -- the nullable one -- is marked use_alter: the constraint is
    # emitted separately, after both tables exist. SQLite has no ALTER TABLE for
    # constraints, so its DDL is unchanged and the foreign key stays inline;
    # only PostgreSQL sees a separate ADD CONSTRAINT.
    default_vehicle_id = db.Column(
        db.Integer,
        db.ForeignKey('vehicles.id', use_alter=True, name='fk_users_default_vehicle_id'),
        nullable=True
    )
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
    show_menu_notes = db.Column(db.Boolean, default=True)  # issue #204
    show_menu_allowance = db.Column(db.Boolean, default=True)  # issue #208
    show_menu_tires = db.Column(db.Boolean, default=True)  # issue #293
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

    @property
    def effective_role(self):
        """The role in force for this account (#285).

        Administrators always have full access whatever is stored against
        them, and an account with no role set (every account predating the
        feature) is treated as an editor so behaviour is unchanged.
        """
        if self.is_admin:
            return 'admin'
        return self.role if self.role in ROLE_WRITE_SCOPES else ROLE_EDITOR

    @property
    def role_label(self):
        """Translated label for the account's role, for display."""
        if self.is_admin:
            return _l('Administrator')
        return dict(USER_ROLES).get(self.effective_role, self.effective_role)

    def can_write(self, scope):
        """Whether this account may add, change or delete data in ``scope``."""
        if self.is_admin:
            return True
        return scope in ROLE_WRITE_SCOPES.get(self.effective_role, set())

    @property
    def has_full_write_access(self):
        """Whether this account may write everywhere (admin or editor)."""
        return self.is_admin or self.effective_role == ROLE_EDITOR

    @property
    def is_read_only(self):
        """Whether this account may not write anywhere at all."""
        return not self.is_admin and not ROLE_WRITE_SCOPES.get(self.effective_role)

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
        self.password_reset_expires = utcnow() + timedelta(hours=1)
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
        if user and user.password_reset_expires and user.password_reset_expires > utcnow():
            return user
        return None

    def generate_api_key(self):
        """Generate a new API key for this user"""
        self.api_key = f"may_{secrets.token_hex(32)}"
        self.api_key_created_at = utcnow()
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
    created_at = db.Column(db.DateTime, default=utcnow)

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

    # Default trip purpose pre-selected when logging a trip for this vehicle (#272)
    default_trip_purpose = db.Column(db.String(20), default='business')

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

    def tracks_hours(self):
        """True when this vehicle's readings are engine hours, not distance (#323).

        ``tracking_unit`` is the authority for how every ``odometer`` value
        belonging to this vehicle is interpreted: a tractor logged at 50 is
        at 50 engine hours, not 50 miles. Hours never convert by a distance
        factor, so ``odometer_unit`` is meaningless for such a vehicle.
        """
        return self.tracking_unit == 'hours'

    def has_odometer_readings(self):
        """True when anything has already been logged against this odometer (#323).

        Used to refuse a ``tracking_unit`` change that would silently
        reinterpret existing readings — 50 miles becoming 50 hours.
        """
        if self.fuel_logs.first() is not None:
            return True
        if self.trips.filter(Trip.end_odometer.isnot(None)).first() is not None:
            return True
        if self.charging_sessions.filter(ChargingSession.odometer.isnot(None)).first() is not None:
            return True
        return self.expenses.filter(Expense.odometer.isnot(None)).first() is not None

    def get_effective_odometer_unit(self):
        """Return the odometer unit for this vehicle.

        Uses the vehicle's own odometer_unit if set, otherwise falls back to
        the owner's distance_unit preference. Only meaningful for a vehicle
        tracked by distance; see :meth:`tracks_hours`.
        """
        if self.odometer_unit:
            return self.odometer_unit
        if self.owner:
            return self.owner.distance_unit
        return 'km'

    def get_reading_unit(self):
        """The unit to print beside one of this vehicle's readings (#282).

        'h' for a vehicle metered in engine hours, otherwise its effective
        odometer unit. This is a display label: never pass it to
        :func:`_distance_in` or any other conversion, which want
        :meth:`get_effective_odometer_unit`.
        """
        if self.tracks_hours():
            return 'h'
        return self.get_effective_odometer_unit()

    def get_reading_label(self):
        """What this vehicle's readings are called (#282).

        A machine metered in hours has no odometer to read, so calling the
        field "Odometer" on its forms is what the reporter of #282 ran into.
        """
        if self.tracks_hours():
            return _l('Engine hours')
        return _l('Odometer')

    def get_span_label(self):
        """What the gap between two of this vehicle's readings is called (#282)."""
        if self.tracks_hours():
            return _l('Hours')
        return _l('Distance')

    def get_consumption_unit(self):
        """The unit to print beside :meth:`get_average_consumption` (#282).

        An hours-tracked vehicle is averaged in litres per engine hour
        whatever the account's preferred consumption unit says, because mpg,
        km/L and L/100km are each named for a distance it never records.
        Returns None for any other vehicle, so callers fall back to the
        account preference they already hold.
        """
        if self.tracks_hours():
            return 'L / h'
        return None

    def get_total_fuel_cost(self):
        return sum(log.total_cost for log in self.fuel_logs.all() if log.total_cost)

    def get_total_expense_cost(self):
        return sum(exp.cost for exp in self.expenses.all() if exp.cost)

    def get_total_fuel_volume(self):
        """Total fuel logged, in the unit the logs were entered in."""
        return sum(log.volume for log in self.fuel_logs.all() if log.volume)

    def get_total_co2_kg(self, volume_unit='L'):
        """Estimated lifetime tailpipe CO2 in kg from logged fuel (#218).

        Uses per-fuel-type DEFRA conversion factors; each log's own fuel
        type wins (dual-fuel vehicles), falling back to the vehicle's.
        Electric charging is not counted — grid intensity varies too much
        to state honestly.
        """
        total = 0.0
        for log in self.fuel_logs.all():
            if not log.volume:
                continue
            fuel_type = log.fuel_type or self.fuel_type
            factor = FUEL_CO2_KG_PER_LITRE.get(fuel_type, FUEL_CO2_KG_PER_LITRE['petrol'])
            total += _to_litres(log.volume, volume_unit) * factor
        return total

    def get_total_cost(self):
        return self.get_total_fuel_cost() + self.get_total_expense_cost() + self.get_total_charging_cost()

    def get_total_allowance(self):
        """Total mileage-allowance income recorded for this vehicle (issue #208)."""
        return sum(a.amount for a in self.mileage_allowances.all() if a.amount) or 0

    def get_net_cost(self):
        """Running cost after mileage allowance is deducted (issue #208)."""
        return self.get_total_cost() - self.get_total_allowance()

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

        For an hours-tracked vehicle the readings are engine hours, so the
        span is returned as logged and ``distance_unit`` is ignored — there
        is no km/mi conversion to apply to an hour (#323).
        """
        if self.tracks_hours():
            logs = self.fuel_logs.order_by(FuelLog.odometer).all()
            if len(logs) < 2:
                return 0
            return logs[-1].odometer - logs[0].odometer

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

    def get_primary_fuel_type(self):
        """The fuel this vehicle burns by default, propulsion resolved (#221)."""
        return resolve_price_fuel_type(None, self.fuel_type)

    def get_propulsion_fuel_types(self):
        """Distinct fuels the fill-ups say this vehicle actually burns (#221).

        A log without its own fuel type counts as the vehicle's primary fuel,
        and propulsion labels are resolved to the fuel they burn, so a
        hybrid's untyped rows and its explicit petrol rows are one fuel, not
        two (#268). Auxiliary fluids are left out: AdBlue propels nothing
        (#319). Ordered primary fuel first so bi-fuel vehicles read naturally.
        """
        types = {_propulsion_fuel_type(log.fuel_type or self.fuel_type)
                 for log in self.fuel_logs.all()}
        types.discard(None)
        primary = self.get_primary_fuel_type()
        return sorted(types, key=lambda ft: (ft != primary, ft))

    def declares_second_fuel(self):
        """True when the owner has declared a second fuel this vehicle burns.

        Distinct from :meth:`runs_on_two_fuels`, which also wants fill-ups of
        both to exist: the fuel form has to offer the distance field before
        the first such fill-up, or the attribution could never be entered.
        """
        secondary = _propulsion_fuel_type(self.secondary_fuel_type)
        return bool(secondary) and secondary != self.get_primary_fuel_type()

    def runs_on_two_fuels(self):
        """True when this vehicle burns two different fuels (#221).

        An LPG conversion is the usual case: the owner declares a
        ``secondary_fuel_type`` and fills up on both. That declaration is
        what makes the odometer ambiguous — only the owner knows the car can
        run on either — so it, not the mix of fuel types happening to appear
        in the logs, is the gate. A plain hybrid whose older fill-ups predate
        the fuel type selector must not be mistaken for a bi-fuel car (#268).

        Both halves have to hold. Until fill-ups of both fuels exist there is
        nothing to disentangle, so a declared bi-fuel car that has only ever
        logged petrol keeps the ordinary odometer maths.
        """
        return self.declares_second_fuel() and len(self.get_propulsion_fuel_types()) > 1

    def _other_fuel_odometers(self, fuel_type=None):
        """Odometer readings of fill-ups of this vehicle's *other* fuel (#221).

        A span containing one of these covers ground run on both fuels, so
        its odometer difference says nothing about either and the driver's
        own attribution is needed. A span with none of them is unambiguous:
        a car converted to LPG last year keeps the ordinary odometer maths
        over the years it ran on petrol alone.

        Empty unless the vehicle actually runs on two fuels.
        """
        if not self.runs_on_two_fuels():
            return []
        target = fuel_type or self.get_primary_fuel_type()
        return [log.odometer for log in self.fuel_logs.all()
                if _propulsion_fuel_type(log.fuel_type or self.fuel_type) not in (None, target)]

    @staticmethod
    def _span_runs_on_both_fuels(other_odometers, start_odometer, end_odometer):
        """True when a fill-up of the other fuel falls inside this span (#221)."""
        return any(start_odometer < odometer <= end_odometer
                   for odometer in other_odometers)

    def _valid_consumption_segments(self, fuel_type=None):
        """Collect (distance, fuel) spans usable for the consumption average.

        Each span runs between consecutive full-tank fill-ups, counting every
        litre poured within it so partial fills are included (issue #169).
        A span containing a log flagged ``is_missed`` is discarded — there is
        no way to make that span honest — but spans either side of it remain
        usable, so one missed fill-up doesn't invalidate the whole history
        (issue #251).

        Only logs of one fuel type are considered, defaulting to the
        vehicle's own. A diesel that also tracks AdBlue keeps the two
        apart: AdBlue is an auxiliary fluid, not propulsion, so pouring it
        in must never move the diesel figure (issue #319).

        Where a span covers ground run on both fuels the odometer cannot say
        which miles went on which, so its distance is the one the driver
        attributed to this fuel, and a span missing that attribution is
        dropped rather than guessed at (issue #221).

        Returns ``None`` when there are fewer than two full-tank anchors,
        otherwise a (possibly empty) list of ``(distance, fuel)`` tuples.
        The span is expressed in the vehicle's own ``tracking_unit`` — km or
        miles for a distance-tracked vehicle, engine hours for one tracked by
        hours (#323) — and is never converted here.
        """
        same_fuel = FuelLog.effective_fuel_type_filter(
            fuel_type or resolve_price_fuel_type(None, self.fuel_type), self.fuel_type)
        full_logs = self.fuel_logs.filter(
            FuelLog.is_full_tank == True, same_fuel
        ).order_by(FuelLog.odometer).all()
        if len(full_logs) < 2:
            return None

        range_logs = self.fuel_logs.filter(
            FuelLog.odometer > full_logs[0].odometer,
            FuelLog.odometer <= full_logs[-1].odometer,
            same_fuel,
        ).order_by(FuelLog.odometer).all()

        other_fuel_odometers = self._other_fuel_odometers(fuel_type)
        segments = []
        for start, end in zip(full_logs, full_logs[1:]):
            span_logs = [log for log in range_logs
                         if start.odometer < log.odometer <= end.odometer]
            if any(log.is_missed for log in span_logs):
                continue
            fuel = sum(log.volume for log in span_logs if log.volume)
            if self._span_runs_on_both_fuels(other_fuel_odometers,
                                             start.odometer, end.odometer):
                distances = [log.fuel_distance for log in span_logs]
                if any(distance is None for distance in distances):
                    continue
                distance = sum(distances)
            else:
                distance = end.odometer - start.odometer
            if distance > 0 and fuel > 0:
                segments.append((distance, fuel))
        return segments

    def get_average_consumption(self, consumption_unit=None, volume_unit='L', fuel_type=None):
        """Calculate average fuel consumption across full-tank fill-up spans.

        Spans contaminated by a missed fill-up are excluded rather than
        poisoning the whole figure (issue #251); the average covers every
        remaining span, partial fills included (issue #169). Each fuel type
        is averaged on its own, the vehicle's primary fuel by default
        (issue #319). Returns None when no honest span exists.

        An hours-tracked vehicle is averaged in litres per engine hour and
        ``consumption_unit`` is ignored: mpg, km/L and L/100km are all named
        for a distance this vehicle never records (issue #323).

        On a bi-fuel vehicle the figure covers one fuel at a time and needs
        the distance the driver attributed to that fuel (issue #221).
        """
        segments = self._valid_consumption_segments(fuel_type)
        if not segments:
            return None

        total_distance = sum(distance for distance, _ in segments)
        total_fuel = sum(fuel for _, fuel in segments)

        if total_distance > 0 and total_fuel > 0:
            if self.tracks_hours():
                return _to_litres(total_fuel, volume_unit) / total_distance
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
            if consumption_unit == 'km/L':
                return km / litres if litres > 0 else None
            return (litres / km) * 100  # L/100km
        return None

    def get_consumption_unavailable_reason(self, fuel_type=None):
        """Explain why :meth:`get_average_consumption` returns ``None``.

        Returns a stable reason code (translated for display in the template)
        or ``None`` when a figure is available. Mirrors the exact conditions
        in ``get_average_consumption`` (issues #169/#194) so the UI can show a
        helpful empty state instead of a bare dash (issue #214):

        - ``'insufficient_full_tanks'`` — fewer than two full-tank fill-ups
        - ``'missed_fill_up'`` — every span is invalidated by a missed fill-up
        - ``'needs_distance_attribution'`` — bi-fuel vehicle whose fill-ups
          don't say how far the car ran on this fuel (issue #221)
        - ``'insufficient_data'`` — not enough distance/volume to calculate
        """
        segments = self._valid_consumption_segments(fuel_type)
        if segments is None:
            return 'insufficient_full_tanks'
        if segments:
            return None

        same_fuel = FuelLog.effective_fuel_type_filter(
            fuel_type or resolve_price_fuel_type(None, self.fuel_type), self.fuel_type)
        full_logs = self.fuel_logs.filter(
            FuelLog.is_full_tank == True, same_fuel
        ).order_by(FuelLog.odometer).all()
        range_logs = self.fuel_logs.filter(
            FuelLog.odometer > full_logs[0].odometer,
            FuelLog.odometer <= full_logs[-1].odometer,
            same_fuel,
        ).all()
        if any(log.is_missed for log in range_logs):
            return 'missed_fill_up'
        other_fuel_odometers = self._other_fuel_odometers(fuel_type)
        if (self._span_runs_on_both_fuels(other_fuel_odometers, full_logs[0].odometer,
                                          full_logs[-1].odometer)
                and any(log.fuel_distance is None for log in range_logs)):
            return 'needs_distance_attribution'
        return 'insufficient_data'

    def get_average_consumption_by_fuel(self, consumption_unit=None, volume_unit='L'):
        """Average consumption per fuel for a bi-fuel vehicle (#221).

        Returns one entry per fuel type logged, each with the figure (or
        ``None``) and the reason it is missing, so the UI can show both
        fuels side by side instead of one meaningless combined number.
        A vehicle with no fill-ups yet still gets a single entry for its
        primary fuel, so the UI keeps its usual empty state.
        """
        return [
            {
                'fuel_type': fuel_type,
                'value': self.get_average_consumption(consumption_unit, volume_unit, fuel_type),
                'reason': self.get_consumption_unavailable_reason(fuel_type),
            }
            for fuel_type in self.get_propulsion_fuel_types() or [self.get_primary_fuel_type()]
        ]

    def uses_tessie_odometer(self):
        """Check if this vehicle uses Tessie for odometer tracking"""
        from app.services.tessie import TessieService
        return (self.tessie_enabled and
                self.tessie_vin and
                TessieService.is_configured())

    def get_last_odometer(self, distance_unit=None):
        """Get the most recent odometer reading.

        If Tessie is enabled for this vehicle, returns the Tessie odometer.
        Otherwise, returns the highest from fuel logs, trips, charging sessions
        or expenses. Expenses count because a maintenance entry such as an oil
        change records the odometer at the time of the work (#286).

        Args:
            distance_unit: If provided ('km' or 'mi'), converts Tessie odometer to
                          this unit. When omitted, the vehicle's effective odometer
                          unit is used so the result is comparable with logged
                          odometer values, which are stored in that unit (#245).
                          Tessie itself reports km internally.
        """
        # If Tessie is enabled, use Tessie odometer exclusively
        if self.uses_tessie_odometer() and self.tessie_last_odometer:
            target = distance_unit or self.get_effective_odometer_unit()
            odometer = _distance_in(self.tessie_last_odometer, 'km', target)
            return round(odometer)

        last_fuel = self.fuel_logs.order_by(FuelLog.odometer.desc()).first()
        fuel_odo = last_fuel.odometer if last_fuel else 0

        last_trip = self.trips.filter(Trip.end_odometer.isnot(None)).order_by(Trip.end_odometer.desc()).first()
        trip_odo = last_trip.end_odometer if last_trip else 0

        last_charge = self.charging_sessions.filter(ChargingSession.odometer.isnot(None)).order_by(
            ChargingSession.odometer.desc()).first()
        charge_odo = last_charge.odometer if last_charge else 0

        last_expense = self.expenses.filter(Expense.odometer.isnot(None)).order_by(
            Expense.odometer.desc()).first()
        expense_odo = last_expense.odometer if last_expense else 0

        return max(fuel_odo, trip_odo, charge_odo, expense_odo)

    def get_fitted_tire_set(self):
        """The tire set currently on this vehicle, or None (#293)."""
        for tire_set in self.tire_sets.all():
            if tire_set.is_fitted:
                return tire_set
        return None

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

        Charging is rare on hours-tracked machinery but not impossible —
        electric plant exists — so the same rule applies as for fuel: an
        hours-tracked vehicle gets kWh per 100 engine hours and
        ``distance_unit`` is ignored (issue #323).
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
        if self.tracks_hours():
            return (total_kwh / raw_distance) * 100
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
        """Calculate total cost of ownership per unit on the vehicle's odometer.

        That unit is whatever ``tracking_unit`` says it is: cost per km or
        per mile for a distance-tracked vehicle, cost per engine hour for an
        hours-tracked one (issue #323). The arithmetic is the same either
        way because :meth:`get_total_distance` returns the span as logged,
        without a km/mi conversion, for an hours-tracked vehicle.
        """
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


# Tailpipe CO2 emitted per litre of fuel burned, in kg — standard UK
# DEFRA/BEIS conversion factors (#218). Zero-tailpipe types are listed
# explicitly so unknown/custom types can fall back to the petrol factor.
FUEL_CO2_KG_PER_LITRE = {
    'petrol': 2.31,
    'diesel': 2.68,
    'lpg': 1.51,
    'cng': 2.75,  # approximation: CNG is normally metered by kg, not litres
    'e85': 1.61,
    'hybrid': 2.31,
    'plugin_hybrid': 2.31,
    'electric': 0.0,
    'hydrogen': 0.0,
    'adblue': 0.0,  # a diesel exhaust additive, not a fuel being burned (#319)
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

    date = db.Column(db.Date, nullable=False, default=utcnow)
    odometer = db.Column(db.Float, nullable=False)  # stored in km
    volume = db.Column(db.Float)  # stored in liters
    price_per_unit = db.Column(db.Float)  # price per the user's volume unit, as entered
    discount_per_unit = db.Column(db.Float)  # optional loyalty discount per liter (issue #209)
    total_cost = db.Column(db.Float)
    sales_tax = db.Column(db.Float)  # sales tax paid, included in total_cost (issue #225)

    fuel_type = db.Column(db.String(20), nullable=True)  # overrides vehicle primary; set when vehicle has secondary fuel type
    # Distance run on this fuel since the previous fill-up of the same fuel,
    # in the vehicle's odometer unit. Only bi-fuel vehicles need it (#221).
    fuel_distance = db.Column(db.Float, nullable=True)
    is_full_tank = db.Column(db.Boolean, default=True)
    is_missed = db.Column(db.Boolean, default=False)  # missed fill-up flag

    station = db.Column(db.String(100))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utcnow)

    # Relationships
    attachments = db.relationship('Attachment', backref='fuel_log', lazy='dynamic',
                                  cascade='all, delete-orphan')

    @property
    def effective_fuel_type(self):
        """The fuel this fill-up actually put in the vehicle (issue #319).

        Logs written before the per-log selector existed carry no fuel type
        of their own, so they inherit the vehicle's. Propulsion types are
        mapped to the fuel they burn, which keeps a hybrid's untyped rows in
        the same series as ones explicitly logged as petrol (issue #268).
        """
        return resolve_price_fuel_type(
            self.fuel_type, self.vehicle.fuel_type if self.vehicle else None)

    @classmethod
    def effective_fuel_type_filter(cls, fuel_type, vehicle_fuel_type):
        """Filter criterion matching logs whose effective fuel type is ``fuel_type``.

        Mirrors :attr:`effective_fuel_type` in SQL: a stored propulsion type
        counts as the fuel it burns, and a NULL fuel type counts as the
        vehicle's own.
        """
        stored = {fuel_type} | {propulsion for propulsion, fuel in PROPULSION_TO_FUEL.items()
                                if fuel == fuel_type}
        criterion = cls.fuel_type.in_(stored)
        if resolve_price_fuel_type(None, vehicle_fuel_type) == fuel_type:
            criterion = db.or_(criterion, cls.fuel_type.is_(None))
        return criterion

    def get_consumption(self, consumption_unit=None, volume_unit='L'):
        """Calculate consumption for this fill-up.

        Only meaningful for full-tank fills: sum every litre poured between
        the previous full tank and this one (inclusive) and divide by the
        distance covered — the "fill-to-fill" method. Partial fills between
        two full tanks are therefore counted in the next full tank's figure
        (issue #169). If any of the intervening logs is flagged ``is_missed``,
        the figure is unknowable and we return None.

        Only logs of the same effective fuel type count, so an AdBlue refill
        never lands in a diesel figure and vice versa (issue #319).

        Partial fills return None: the litres added in a top-up tell you
        nothing about consumption over the preceding distance, and surfacing
        a number there is misleading (issue #194).

        The owning vehicle's ``tracking_unit`` decides what the span between
        two readings means. For an hours-tracked vehicle it is engine hours,
        so the figure is litres per hour and ``consumption_unit`` is ignored
        (issue #323).

        Where the span covers ground run on both of a bi-fuel vehicle's
        fuels, the distance is the one the driver attributed to this fuel
        rather than the odometer difference — the odometer cannot say which
        miles were run on LPG and which on petrol (issue #221).
        """
        if not self.volume or not self.is_full_tank:
            return None

        same_fuel = FuelLog.effective_fuel_type_filter(
            self.effective_fuel_type,
            self.vehicle.fuel_type if self.vehicle else None)

        prev_full = FuelLog.query.filter(
            FuelLog.vehicle_id == self.vehicle_id,
            FuelLog.odometer < self.odometer,
            FuelLog.is_full_tank == True,
            same_fuel,
        ).order_by(FuelLog.odometer.desc()).first()
        if not prev_full:
            return None
        between = FuelLog.query.filter(
            FuelLog.vehicle_id == self.vehicle_id,
            FuelLog.odometer > prev_full.odometer,
            FuelLog.odometer <= self.odometer,
            same_fuel,
        ).all()
        if any(log.is_missed for log in between):
            return None
        other_fuel_odometers = (self.vehicle._other_fuel_odometers(self.effective_fuel_type)
                                if self.vehicle else [])
        if Vehicle._span_runs_on_both_fuels(other_fuel_odometers,
                                            prev_full.odometer, self.odometer):
            if any(log.fuel_distance is None for log in between):
                return None
            distance = sum(log.fuel_distance for log in between)
        else:
            distance = self.odometer - prev_full.odometer
        volume_native = sum(log.volume for log in between if log.volume)

        if distance > 0 and volume_native > 0:
            if self.vehicle and self.vehicle.tracks_hours():
                return _to_litres(volume_native, volume_unit) / distance
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
            if consumption_unit == 'km/L':
                return km / litres if litres > 0 else None
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
            'discount_per_unit': self.discount_per_unit,
            'total_cost': self.total_cost,
            'sales_tax': self.sales_tax,
            'fuel_type': self.effective_fuel_type,
            'fuel_distance': self.fuel_distance,
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

    date = db.Column(db.Date, nullable=False, default=utcnow)
    category = db.Column(db.String(50), nullable=False)  # maintenance, insurance, repairs, tax, parking, tolls, other
    description = db.Column(db.String(200), nullable=False)
    cost = db.Column(db.Float, nullable=False)
    odometer = db.Column(db.Float)  # optional

    vendor = db.Column(db.String(100))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utcnow)

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
    created_at = db.Column(db.DateTime, default=utcnow)


class VehicleSpec(db.Model):
    """Custom specifications/attributes for vehicles"""
    __tablename__ = 'vehicle_specs'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)

    spec_type = db.Column(db.String(50), nullable=False)  # predefined or custom type
    label = db.Column(db.String(100), nullable=False)  # display label
    value = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


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
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

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

    def expense_category(self):
        """The expense category to pre-select when logging an expense for
        this reminder (#296). Unmapped types fall back to 'other'."""
        return REMINDER_EXPENSE_CATEGORIES.get(self.reminder_type, 'other')

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
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

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
    # AdBlue propels nothing — it is an auxiliary fluid a diesel tracks
    # alongside its fuel, so it belongs here only as a secondary type (#319).
    ('adblue', _l('AdBlue/DEF')),
    ('other', _l('Other'))
]

# Some vehicle "fuel types" describe how the vehicle is propelled rather than
# what goes in the tank. Station price history is charted per fuel type, so a
# hybrid fill-up has to be recorded against the fuel it actually burns (#268).
# Diesel hybrids are the rarer case, so petrol is the default; owners of one
# can pick diesel per fill-up with the fuel type selector on the fuel form.
PROPULSION_TO_FUEL = {
    'hybrid': 'petrol',
    'plugin_hybrid': 'petrol',
}


def resolve_price_fuel_type(log_fuel_type, vehicle_fuel_type):
    """Return the fuel type to record on a station price history row.

    The fuel type chosen on the log wins; otherwise the vehicle's own fuel
    type is used. Either way a propulsion type is mapped to the fuel it
    burns so the station price charts only ever show real fuels.
    """
    fuel_type = log_fuel_type or vehicle_fuel_type
    return PROPULSION_TO_FUEL.get(fuel_type, fuel_type) or 'petrol'


# Fluids a vehicle carries alongside its fuel without burning them for
# propulsion. They are logged and costed, but they never earn a consumption
# figure of their own (#319) and never split a bi-fuel vehicle's distance
# (#221): an AdBlue top-up says nothing about how far the car ran on diesel.
AUXILIARY_FLUID_TYPES = {'adblue'}


def _propulsion_fuel_type(fuel_type):
    """The fuel a stored type actually burns, or None if it burns nothing.

    Propulsion labels resolve to the fuel behind them, so 'hybrid' and
    'petrol' are one fuel rather than two (#268), and auxiliary fluids
    resolve to None (#319).
    """
    if not fuel_type or fuel_type in AUXILIARY_FLUID_TYPES:
        return None
    return resolve_price_fuel_type(fuel_type, fuel_type)


def fuel_type_label(fuel_type):
    """Display label for a stored fuel type slug, translated where known."""
    return dict(FUEL_TYPES).get(fuel_type) or (fuel_type or '').replace('_', ' ').title()


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

# Which expense category to pre-select when an expense is logged against a
# reminder (#296). Types with no obvious equivalent fall back to 'other'.
REMINDER_EXPENSE_CATEGORIES = {
    'mot': 'inspection',
    'service': 'maintenance',
    'insurance': 'insurance',
    'tax': 'tax',
    'registration': 'registration',
    'tire_change': 'maintenance',
    'oil_change': 'maintenance',
}

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

# Tire set types (#293)
TIRE_TYPES = [
    ('summer', _l('Summer')),
    ('winter', _l('Winter')),
    ('all_season', _l('All Season')),
    ('other', _l('Other')),
]


# How many engine hours ahead of a service still counts as "due soon" for a
# vehicle metered in hours (issue #282). Distance-tracked vehicles use 500,
# in whichever of km or miles their odometer reads.
MAINTENANCE_DUE_SOON_HOURS = 25


class MaintenanceSchedule(db.Model):
    """Predefined maintenance schedules with reading/time intervals.

    The reading-based interval is stated in the owning vehicle's own unit:
    kilometres or miles for a vehicle tracked by distance, engine hours for
    one tracked by hours (issue #282).
    """
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
    interval_hours = db.Column(db.Integer)  # e.g., every 250 engine hours (#282)
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
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

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
            if self.tracks_hours():
                # This vehicle's readings are engine hours, so the only
                # interval that means anything is one stated in hours, and no
                # distance factor may touch it (issue #282).
                if self.interval_hours:
                    self.next_due_odometer = (
                        self.last_performed_odometer + self.interval_hours)
                return
            # last_performed_odometer is stored in the vehicle's effective
            # odometer unit (the same unit next_due_odometer is displayed and
            # compared in). Convert the interval into that same unit before
            # adding, so the two operands never mix km and miles (issue #230).
            unit = self._effective_odometer_unit()
            if self.interval_km:
                interval = _distance_in(self.interval_km, 'km', unit)
                self.next_due_odometer = self.last_performed_odometer + interval
            elif self.interval_miles:
                interval = _distance_in(self.interval_miles, 'mi', unit)
                self.next_due_odometer = self.last_performed_odometer + interval

    def _resolve_vehicle(self):
        """The vehicle this schedule belongs to, or None.

        Uses the loaded ``vehicle`` relationship when available, otherwise
        looks it up by ``vehicle_id`` (calculate_next_due runs on new
        schedules before they are flushed, so the relationship may be unset).
        """
        if self.vehicle is not None:
            return self.vehicle
        if self.vehicle_id:
            return db.session.get(Vehicle, self.vehicle_id)
        return None

    def tracks_hours(self):
        """True when this schedule's vehicle is metered in engine hours (#282)."""
        vehicle = self._resolve_vehicle()
        return vehicle is not None and vehicle.tracks_hours()

    def _effective_odometer_unit(self):
        """Resolve the odometer unit for this schedule's vehicle.

        Defaults to 'km' when no vehicle can be resolved. Only meaningful for
        a vehicle tracked by distance; see :meth:`tracks_hours`.
        """
        vehicle = self._resolve_vehicle()
        if vehicle:
            return vehicle.get_effective_odometer_unit()
        return 'km'

    def get_interval(self):
        """The reading-based interval, in the vehicle's own unit (#282).

        Returns an ``(amount, unit)`` pair — ``(250, 'h')`` for an
        hours-tracked machine — or None when no reading-based interval is
        set. Time-based intervals are reported separately.
        """
        if self.tracks_hours():
            return (self.interval_hours, 'h') if self.interval_hours else None
        if self.interval_km:
            return (self.interval_km, 'km')
        if self.interval_miles:
            return (self.interval_miles, 'mi')
        return None

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

    def is_due_soon(self, current_odometer=None, days=14, distance=None):
        """Check if maintenance is due soon.

        ``distance`` is how far ahead of the next-due reading still counts as
        soon, in the vehicle's own unit. Left unset it is 500 km or miles for
        a distance-tracked vehicle and 25 engine hours for an hours-tracked
        one — 500 hours would put a tractor's every service permanently in
        the amber (issue #282).
        """
        from datetime import date, timedelta

        # Check date-based
        if self.next_due_date:
            if self.next_due_date <= date.today() + timedelta(days=days):
                return True

        # Check odometer-based
        if self.next_due_odometer and current_odometer:
            if distance is None:
                distance = MAINTENANCE_DUE_SOON_HOURS if self.tracks_hours() else 500
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
    created_at = db.Column(db.DateTime, default=utcnow)

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
        elif self.frequency == 'biannual':
            self.next_due = base_date + relativedelta(months=6)
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


#: Price sources a station can be linked to. The key is stored in
#: ``FuelStation.price_source``; the value is a human-readable label.
PRICE_SOURCES = {
    'uk_fuel_prices': 'UK Fuel Price Scheme',
    'tankerkoenig': 'Tankerkönig',
}


class FuelStation(db.Model):
    """Favorite fuel stations"""
    __tablename__ = 'fuel_stations'

    # A station may be linked to at most one forecourt per price source, and
    # a forecourt to at most one of a user's stations. NULLs compare as
    # distinct in SQLite, so unlinked stations are unaffected.
    __table_args__ = (
        db.Index(
            'ix_fuel_stations_source_external_id',
            'user_id', 'price_source', 'external_id',
            unique=True,
        ),
    )

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

    created_at = db.Column(db.DateTime, default=utcnow)

    # Live price provider this station stands for, if any. ``price_source``
    # is a key from PRICE_SOURCES and ``external_id`` the provider's own id
    # for the forecourt (a UK scheme site_id, a Tankerkönig station uuid,
    # ...). Recording identity as stations are matched avoids having to
    # re-derive it later from addresses and postcodes.
    price_source = db.Column(db.String(30))
    external_id = db.Column(db.String(64))

    # Relationships
    user = db.relationship('User', backref=db.backref('fuel_stations', lazy='dynamic'))

    def increment_usage(self):
        """Increment usage counter when station is used"""
        self.times_used = (self.times_used or 0) + 1
        self.last_used = utcnow()

    @property
    def price_source_label(self):
        """Human-readable name of the linked price source, or None"""
        if not self.price_source:
            return None
        return PRICE_SOURCES.get(self.price_source, self.price_source)

    @classmethod
    def find_by_external_id(cls, user_id, price_source, external_id):
        """Return the user's station linked to a provider forecourt, or None"""
        if not price_source or not external_id:
            return None
        return cls.query.filter_by(
            user_id=user_id,
            price_source=price_source,
            external_id=str(external_id),
        ).first()

    def link_price_source(self, price_source, external_id):
        """Link this station to a provider forecourt if that is unambiguous.

        Does nothing when the station is already linked or when another of
        the user's stations holds the same identity, so the unique index can
        never be tripped by a heuristic match.

        Returns:
            bool: True if the link was recorded
        """
        if not price_source or not external_id:
            return False
        if self.price_source or self.external_id:
            return False

        external_id = str(external_id)
        clash = self.find_by_external_id(self.user_id, price_source, external_id)
        if clash is not None and clash is not self:
            return False

        self.price_source = price_source
        self.external_id = external_id
        return True


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

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

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

    date = db.Column(db.Date, nullable=False, default=utcnow)
    start_odometer = db.Column(db.Float, nullable=False)
    end_odometer = db.Column(db.Float, nullable=True)

    # Fuel gauge readings as a percentage of a full tank (0-100), so fuel used
    # can be approximated against the vehicle's tank capacity (#273)
    start_fuel_level = db.Column(db.Float, nullable=True)
    end_fuel_level = db.Column(db.Float, nullable=True)

    purpose = db.Column(db.String(20), nullable=False)  # business, personal, commute, etc.
    description = db.Column(db.String(200))
    start_location = db.Column(db.String(200))
    end_location = db.Column(db.String(200))

    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('trips', lazy='dynamic'))

    @property
    def distance(self):
        """Calculate trip distance"""
        if self.end_odometer is None or self.start_odometer is None:
            return 0
        return self.end_odometer - self.start_odometer

    @property
    def fuel_used(self):
        """Approximate fuel burnt on the trip from the gauge readings.

        Returned in the same unit as the vehicle's tank capacity. ``None`` when
        either reading or the tank capacity is missing, or when the tank ended
        fuller than it started (a fill-up mid-trip makes the figure meaningless).
        """
        if self.start_fuel_level is None or self.end_fuel_level is None:
            return None
        capacity = self.vehicle.tank_capacity if self.vehicle else None
        if not capacity:
            return None
        used = (self.start_fuel_level - self.end_fuel_level) / 100 * capacity
        if used < 0:
            return None
        return used

    def to_dict(self):
        """Serialize trip to dictionary for API"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'start_odometer': self.start_odometer,
            'end_odometer': self.end_odometer,
            'distance': self.distance,
            'start_fuel_level': self.start_fuel_level,
            'end_fuel_level': self.end_fuel_level,
            'fuel_used': self.fuel_used,
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

    created_at = db.Column(db.DateTime, default=utcnow)

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

    date = db.Column(db.Date, nullable=False, default=utcnow)
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
    created_at = db.Column(db.DateTime, default=utcnow)

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

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

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
    # Exact link to the fuel log that produced this row (#254). Nullable:
    # legacy rows and manually recorded station prices have no owning log.
    fuel_log_id = db.Column(db.Integer, db.ForeignKey('fuel_logs.id'), nullable=True)

    date = db.Column(db.Date, nullable=False, default=utcnow)
    fuel_type = db.Column(db.String(20), nullable=False)  # petrol, diesel, premium, etc.
    price_per_unit = db.Column(db.Float, nullable=False)

    created_at = db.Column(db.DateTime, default=utcnow)

    # Relationships
    # Cascade so deleting a station removes its price rows rather than
    # violating the NOT NULL station_id constraint with a 500 (#256).
    station = db.relationship(
        'FuelStation',
        backref=db.backref('price_history', lazy='dynamic', cascade='all, delete-orphan'),
    )
    user = db.relationship('User', backref=db.backref('fuel_price_history', lazy='dynamic'))
    fuel_log = db.relationship(
        'FuelLog', backref=db.backref('price_history_entries', lazy='dynamic')
    )


class Note(db.Model):
    """Freeform note attached to a vehicle, with optional odometer reading.

    Issue #204: a place to record things that don't fit fuel/expenses/maintenance
    (e.g. a DPF regeneration) without inventing a cost.
    """
    __tablename__ = 'notes'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=utcnow)
    title = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False)
    odometer = db.Column(db.Float)  # optional, stored in vehicle odometer unit

    created_at = db.Column(db.DateTime, default=utcnow)

    # Relationships — backref is `note_entries` to avoid clashing with Vehicle.notes column
    vehicle = db.relationship('Vehicle', backref=db.backref('note_entries', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('notes', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'title': self.title,
            'content': self.content,
            'odometer': self.odometer,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class MileageAllowance(db.Model):
    """Mileage-allowance income for a vehicle used for business (issue #208).

    Records money received per the recorded distance; the totals offset the
    vehicle's running costs (see Vehicle.get_net_cost).
    """
    __tablename__ = 'mileage_allowances'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=utcnow)
    description = db.Column(db.String(200))
    distance = db.Column(db.Float)  # optional, stored in vehicle odometer unit
    rate_per_unit = db.Column(db.Float)  # optional reimbursement rate per distance unit
    amount = db.Column(db.Float, nullable=False)  # total amount received

    created_at = db.Column(db.DateTime, default=utcnow)

    # Relationships
    vehicle = db.relationship('Vehicle', backref=db.backref('mileage_allowances', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('mileage_allowances', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'description': self.description,
            'distance': self.distance,
            'rate_per_unit': self.rate_per_unit,
            'amount': self.amount,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TireSet(db.Model):
    """A set of tires owned for a vehicle (issue #293).

    Seasonal sets come on and off a vehicle repeatedly, so the distance a set
    has covered is the sum of the distances of every period it spent fitted —
    see :class:`TireFitment`. Odometer values are stored in the vehicle's
    odometer unit, as they are everywhere else.
    """
    __tablename__ = 'tire_sets'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)  # "Michelin Alpin 6"
    tire_type = db.Column(db.String(20), nullable=False, default='all_season')
    size = db.Column(db.String(50))  # "205/55 R16 91H"

    purchase_date = db.Column(db.Date)
    purchase_odometer = db.Column(db.Float)  # vehicle odometer when the set was bought
    cost = db.Column(db.Float)

    notes = db.Column(db.Text)
    is_retired = db.Column(db.Boolean, default=False)  # worn out, sold, scrapped

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    vehicle = db.relationship('Vehicle', backref=db.backref('tire_sets', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('tire_sets', lazy='dynamic'))

    @property
    def type_label(self):
        return dict(TIRE_TYPES).get(self.tire_type, self.tire_type)

    @property
    def current_fitment(self):
        """The open fitment period — fitted and not yet taken off — if any."""
        return self.fitments.filter(
            TireFitment.removed_odometer.is_(None)
        ).order_by(TireFitment.fitted_date.desc(), TireFitment.id.desc()).first()

    @property
    def is_fitted(self):
        return self.current_fitment is not None

    def get_distance(self, current_odometer=None):
        """Total distance covered on this set, in the vehicle's odometer unit.

        A closed period contributes its removed minus fitted reading; an open
        period is measured against the vehicle's latest odometer reading.
        Periods that would count backwards (a reading entered out of order)
        contribute nothing rather than a negative distance.
        """
        total = 0.0
        for fitment in self.fitments.all():
            if fitment.fitted_odometer is None:
                continue
            end = fitment.removed_odometer
            if end is None:
                if current_odometer is None:
                    current_odometer = self.vehicle.get_last_odometer() if self.vehicle else 0
                end = current_odometer
            total += max(0.0, (end or 0) - fitment.fitted_odometer)
        return total

    def to_dict(self):
        """Serialize the tire set to a dictionary"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'name': self.name,
            'tire_type': self.tire_type,
            'size': self.size,
            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,
            'purchase_odometer': self.purchase_odometer,
            'cost': self.cost,
            'notes': self.notes,
            'is_retired': self.is_retired,
            'is_fitted': self.is_fitted,
            'distance': self.get_distance(),
            'fitments': [f.to_dict() for f in self.fitments.all()],
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TireFitment(db.Model):
    """One period a tire set spent fitted to its vehicle (issue #293).

    A period with no removal reading is the set currently on the vehicle.
    """
    __tablename__ = 'tire_fitments'

    id = db.Column(db.Integer, primary_key=True)
    tire_set_id = db.Column(db.Integer, db.ForeignKey('tire_sets.id'), nullable=False)

    fitted_date = db.Column(db.Date, nullable=False, default=utcnow)
    fitted_odometer = db.Column(db.Float, nullable=False)
    removed_date = db.Column(db.Date)
    removed_odometer = db.Column(db.Float)

    created_at = db.Column(db.DateTime, default=utcnow)

    # Relationships
    tire_set = db.relationship(
        'TireSet',
        backref=db.backref(
            'fitments',
            lazy='dynamic',
            cascade='all, delete-orphan',
            order_by='TireFitment.fitted_date.desc(), TireFitment.id.desc()',
        ),
    )

    def get_distance(self, current_odometer=None):
        """Distance covered during this period, in the vehicle's odometer unit."""
        if self.fitted_odometer is None:
            return 0.0
        end = self.removed_odometer
        if end is None:
            if current_odometer is None:
                vehicle = self.tire_set.vehicle if self.tire_set else None
                current_odometer = vehicle.get_last_odometer() if vehicle else 0
            end = current_odometer
        return max(0.0, (end or 0) - self.fitted_odometer)

    def to_dict(self):
        """Serialize the fitment period to a dictionary"""
        return {
            'id': self.id,
            'tire_set_id': self.tire_set_id,
            'fitted_date': self.fitted_date.isoformat() if self.fitted_date else None,
            'fitted_odometer': self.fitted_odometer,
            'removed_date': self.removed_date.isoformat() if self.removed_date else None,
            'removed_odometer': self.removed_odometer,
            'distance': self.get_distance(),
        }
