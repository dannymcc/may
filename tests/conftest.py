import pytest
from datetime import date

from app import create_app, db as _db_ext
from app.models import User, Vehicle, FuelLog, Expense, Trip, ChargingSession


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SERVER_NAME = 'localhost'
    SECRET_KEY = 'test-secret'
    # Prevent file uploads from failing
    UPLOAD_FOLDER = '/tmp/may_test_uploads'


@pytest.fixture(scope='function')
def app():
    """Create a Flask application configured for testing."""
    import os
    os.makedirs('/tmp/may_test_uploads', exist_ok=True)

    flask_app = create_app(TestConfig)

    ctx = flask_app.app_context()
    ctx.push()

    yield flask_app

    _db_ext.session.remove()
    _db_ext.drop_all()
    ctx.pop()


@pytest.fixture(scope='function')
def client(app):
    """A test client for the app."""
    return app.test_client()


@pytest.fixture(scope='function')
def runner(app):
    """A test CLI runner for the app."""
    return app.test_cli_runner()


@pytest.fixture(scope='function')
def _db(app):
    """Provide the database instance."""
    yield _db_ext


@pytest.fixture(scope='function')
def test_user(app):
    """Create a regular test user.

    The app factory creates a default admin user on startup, so 'testuser'
    will be added alongside that admin.
    """
    user = User(
        username='testuser',
        email='test@example.com',
        distance_unit='mi',
        currency='GBP',
    )
    user.set_password('TestPass123!')
    _db_ext.session.add(user)
    _db_ext.session.commit()
    return user


@pytest.fixture(scope='function')
def admin_user(app):
    """Return the auto-created admin user, or create one if absent.

    The app factory auto-creates an admin with username 'admin' when no
    users exist. We look for that user first, and only create a new one if
    it doesn't already exist.
    """
    existing = User.query.filter_by(username='admin').first()
    if existing:
        # Update to known credentials for tests
        existing.email = 'admin@example.com'
        existing.is_admin = True
        existing.set_password('AdminPass123!')
        _db_ext.session.commit()
        return existing

    user = User(
        username='admin',
        email='admin@example.com',
        is_admin=True,
    )
    user.set_password('AdminPass123!')
    _db_ext.session.add(user)
    _db_ext.session.commit()
    return user


@pytest.fixture(scope='function')
def auth_client(client, test_user):
    """A test client logged in as test_user."""
    client.post('/auth/login', data={
        'username': 'testuser',
        'password': 'TestPass123!',
    }, follow_redirects=True)
    yield client


@pytest.fixture(scope='function')
def admin_client(client, admin_user):
    """A test client logged in as admin_user."""
    client.post('/auth/login', data={
        'username': 'admin',
        'password': 'AdminPass123!',
    }, follow_redirects=True)
    yield client


@pytest.fixture(scope='function')
def sample_vehicle(app, test_user):
    """Create a sample vehicle owned by test_user."""
    vehicle = Vehicle(
        owner_id=test_user.id,
        name='Test Car',
        vehicle_type='car',
        make='Toyota',
        model='Corolla',
        year=2023,
        fuel_type='petrol',
        odometer_unit='km',
    )
    _db_ext.session.add(vehicle)
    _db_ext.session.commit()
    return vehicle


@pytest.fixture(scope='function')
def sample_fuel_log(app, test_user, sample_vehicle):
    """Create a sample fuel log entry."""
    log = FuelLog(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 1, 15),
        odometer=10000.0,
        volume=40.0,
        price_per_unit=1.50,
        total_cost=60.0,
        is_full_tank=True,
    )
    _db_ext.session.add(log)
    _db_ext.session.commit()
    return log


@pytest.fixture(scope='function')
def sample_expense(app, test_user, sample_vehicle):
    """Create a sample expense entry."""
    expense = Expense(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 1, 20),
        category='maintenance',
        description='Oil change',
        cost=75.0,
    )
    _db_ext.session.add(expense)
    _db_ext.session.commit()
    return expense


@pytest.fixture(scope='function')
def sample_trip(app, test_user, sample_vehicle):
    """Create a sample trip entry."""
    trip = Trip(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 1, 25),
        start_odometer=10000.0,
        end_odometer=10050.0,
        purpose='business',
        description='Client visit',
    )
    _db_ext.session.add(trip)
    _db_ext.session.commit()
    return trip


@pytest.fixture(scope='function')
def sample_charging_session(app, test_user, sample_vehicle):
    """Create a sample charging session entry."""
    session = ChargingSession(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 1, 30),
        odometer=10100.0,
        kwh_added=40.0,
        cost_per_kwh=0.30,
        total_cost=12.0,
        charger_type='home',
    )
    _db_ext.session.add(session)
    _db_ext.session.commit()
    return session


@pytest.fixture(scope='function')
def api_headers(test_user):
    """Return headers with a valid API key for test_user."""
    api_key = test_user.generate_api_key()
    _db_ext.session.commit()
    return {'X-API-Key': api_key}
