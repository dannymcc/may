"""Starting readings change cost distance using fuel readings and an optional baseline."""
from datetime import date
import pytest
from app import db
from app.models import Expense, FuelLog


def test_baseline_and_fallback(app, sample_vehicle, test_user):
    """Ignore newer expense mileage and preserve fuel economy when applying a baseline."""
    for reading in (647, 2700):
        db.session.add(FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                              date=date(2026, 10, 1), odometer=reading,
                              volume=40, total_cost=60, is_full_tank=True))
    db.session.add(Expense(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                          date=date(2026, 10, 2), category='maintenance',
                          description='Service', odometer=2935, cost=100))
    db.session.commit()
    consumption = sample_vehicle.get_average_consumption()
    assert sample_vehicle.get_total_distance() == 2053
    sample_vehicle.starting_odometer = 16
    assert sample_vehicle.get_total_distance() == 2684
    assert sample_vehicle.get_total_distance('mi') == pytest.approx(2684 * 0.621371)
    assert sample_vehicle.get_cost_per_distance() == pytest.approx(220 / 2684)
    assert sample_vehicle.get_average_consumption() == consumption
    sample_vehicle.starting_odometer = 0
    assert sample_vehicle.get_total_distance() == 2700
    sample_vehicle.starting_odometer = 3000
    assert sample_vehicle.get_total_distance() == 0
    assert sample_vehicle.get_cost_per_distance() is None
    sample_vehicle.starting_odometer = None
    assert sample_vehicle.get_total_distance() == 2053
    sample_vehicle.tracking_unit = 'hours'
    sample_vehicle.starting_odometer = 16
    assert sample_vehicle.get_total_distance('mi') == 2684


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'abc'])
def test_invalid_baseline_is_rejected(auth_client, sample_vehicle, value):
    """Reject invalid readings before any vehicle fields are changed."""
    response = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={'starting_odometer': value}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Starting odometer must be a nonnegative number.' in response.data
    assert sample_vehicle.starting_odometer is None
    assert sample_vehicle.name == 'Test Car'


def test_create_and_clear_baseline(auth_client, test_user):
    """Persist a zero baseline and let the owner clear the explicit baseline."""
    from app.models import Vehicle
    response = auth_client.post('/vehicles/new', data={'name':'Baseline car', 'vehicle_type':'car', 'fuel_type':'petrol', 'starting_odometer':'0'})
    assert response.status_code == 302
    vehicle = Vehicle.query.filter_by(name='Baseline car').one()
    assert vehicle.starting_odometer == 0
    assert b'value="0.0"' in auth_client.get(f'/vehicles/{vehicle.id}/edit').data
    auth_client.post(f'/vehicles/{vehicle.id}/edit', data={'name':vehicle.name, 'vehicle_type':'car', 'fuel_type':'petrol', 'starting_odometer':''})
    db.session.refresh(vehicle)
    assert vehicle.starting_odometer is None


def test_saved_baseline_updates_vehicle_and_dashboard(auth_client, sample_vehicle, test_user):
    """Saving the form updates both displayed totals; clearing uses the earliest fuel baseline."""
    for reading in (647, 2700):
        db.session.add(FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                              date=date(2026, 10, 1), odometer=reading,
                              volume=40, total_cost=60, is_full_tank=True))
    db.session.add(Expense(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                          date=date(2026, 10, 2), category='maintenance',
                          description='Service', odometer=2935, cost=100))
    test_user.distance_unit = 'km'
    db.session.commit()
    data = {'name': sample_vehicle.name, 'vehicle_type': 'car',
            'fuel_type': 'petrol', 'odometer_unit': 'km', 'starting_odometer': '16'}
    response = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data=data, follow_redirects=True)
    assert response.status_code == 200
    db.session.refresh(sample_vehicle)
    assert sample_vehicle.starting_odometer == 16
    assert sample_vehicle.get_total_distance() == 2684
    assert '2684' in response.text
    assert '2684' in auth_client.get('/dashboard').text
    edit_form = auth_client.get(f'/vehicles/{sample_vehicle.id}/edit')
    assert b'value="16.0"' in edit_form.data
    assert b'placeholder="e.g., 16000"' in edit_form.data
    data['starting_odometer'] = ''
    auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data=data)
    db.session.refresh(sample_vehicle)
    assert sample_vehicle.starting_odometer is None
    assert sample_vehicle.get_total_distance() == 2053
    assert '2053' in auth_client.get('/dashboard').text


@pytest.mark.parametrize('source,extends', [('trip', True), ('expense', False), ('charging', True)])
@pytest.mark.parametrize('unit', ['km', 'mi', 'hours'])
def test_which_readings_extend_distance(app, sample_vehicle, test_user, source, extends, unit):
    """Charging readings count like fuel readings, and trips fill in when
    there is no other span to measure (#412); an expense reading never does."""
    from app.models import Trip, ChargingSession
    sample_vehicle.tracking_unit = 'hours' if unit == 'hours' else 'mileage'
    sample_vehicle.odometer_unit = 'mi' if unit == 'mi' else 'km'
    common = dict(vehicle_id=sample_vehicle.id, user_id=test_user.id, date=date(2026, 10, 1))
    db.session.add(FuelLog(**common, odometer=100, volume=10, total_cost=20))
    if source == 'trip':
        record = Trip(**common, start_odometer=100, end_odometer=300, purpose='business')
    elif source == 'expense':
        record = Expense(**common, odometer=300, category='maintenance', description='Service', cost=10)
    else:
        record = ChargingSession(**common, odometer=300, kwh_added=10, total_cost=5)
    db.session.add(record)
    db.session.commit()
    assert sample_vehicle.get_total_distance() == (200 if extends else 0)
    sample_vehicle.starting_odometer = 50
    expected = 250 if extends else 50
    assert sample_vehicle.get_total_distance() == expected
    if unit == 'mi':
        assert sample_vehicle.get_total_distance('km') == pytest.approx(expected / 0.621371)
    elif unit == 'hours':
        assert sample_vehicle.get_total_distance('mi') == expected


def test_trips_do_not_stretch_a_span_measured_at_the_pump(app, sample_vehicle, test_user):
    """Trips only stand in when fill-ups and charges give no span of their own."""
    from app.models import Trip
    common = dict(vehicle_id=sample_vehicle.id, user_id=test_user.id, date=date(2026, 10, 1))
    db.session.add_all([
        FuelLog(**common, odometer=100, volume=10, total_cost=20),
        FuelLog(**common, odometer=400, volume=10, total_cost=20),
        Trip(**common, start_odometer=400, end_odometer=900, purpose='business'),
    ])
    db.session.commit()
    assert sample_vehicle.get_total_distance() == 300


def test_electric_vehicle_distance_and_cost_rate(app, sample_vehicle, test_user):
    """An EV with charging sessions and no fuel logs gets a distance and a rate (#412)."""
    from app.models import ChargingSession
    sample_vehicle.fuel_type = 'electric'
    sample_vehicle.odometer_unit = 'km'
    for day, reading in [(1, 263), (9, 352), (14, 447)]:
        db.session.add(ChargingSession(
            vehicle_id=sample_vehicle.id, user_id=test_user.id, date=date(2026, 10, day),
            odometer=reading, kwh_added=20, total_cost=4.6))
    db.session.commit()
    assert sample_vehicle.get_total_distance() == 184
    assert sample_vehicle.get_cost_per_distance() == pytest.approx(13.8 / 184)


def test_electric_vehicle_with_trips_only(app, sample_vehicle, test_user):
    """Trips alone are enough when no charge carries a reading (#412)."""
    from app.models import ChargingSession, Trip
    sample_vehicle.fuel_type = 'electric'
    common = dict(vehicle_id=sample_vehicle.id, user_id=test_user.id)
    db.session.add_all([
        ChargingSession(**common, date=date(2026, 10, 1), kwh_added=20, total_cost=4.91),
        Trip(**common, date=date(2026, 10, 9), start_odometer=263, end_odometer=333, purpose='personal'),
        Trip(**common, date=date(2026, 10, 14), start_odometer=438, end_odometer=447, purpose='personal'),
    ])
    db.session.commit()
    assert sample_vehicle.get_total_distance() == 184


def test_annual_mileage_counts_charging_and_trip_readings(app, sample_vehicle, test_user):
    """The mileage allowance tracker no longer reads zero for an EV (#412)."""
    from datetime import timedelta
    from app.models import ChargingSession, Trip
    today = date.today()
    sample_vehicle.annual_mileage_limit = 10000
    sample_vehicle.annual_mileage_start_date = today - timedelta(days=60)
    common = dict(vehicle_id=sample_vehicle.id, user_id=test_user.id)
    db.session.add_all([
        ChargingSession(**common, date=today - timedelta(days=30), odometer=263, kwh_added=20),
        Trip(**common, date=today - timedelta(days=1), start_odometer=438, end_odometer=447,
             purpose='personal'),
    ])
    db.session.commit()
    assert sample_vehicle.get_annual_mileage_stats()['driven'] == 184


def test_no_baseline_and_confirmed_zero(app, sample_vehicle, test_user):
    """Missing readings do not invent distance, but an explicit zero counts."""
    assert sample_vehicle.get_total_distance() == 0
    sample_vehicle.starting_odometer = 16
    assert sample_vehicle.get_total_distance() == 0
    common = dict(vehicle_id=sample_vehicle.id, user_id=test_user.id, date=date(2026, 10, 1))
    db.session.add(Expense(**common, odometer=200, category='maintenance', description='Service', cost=20))
    db.session.commit()
    sample_vehicle.starting_odometer = None
    assert sample_vehicle.get_total_distance() == 0
    log = FuelLog(**common, odometer=0, volume=10, total_cost=20, odometer_confirmed=False)
    db.session.add(log)
    db.session.commit()
    assert sample_vehicle.get_total_distance() == 0
    log.odometer_confirmed = True
    db.session.commit()
    assert sample_vehicle.get_total_distance() == 0
    sample_vehicle.starting_odometer = 0
    assert sample_vehicle.get_total_distance() == 0
    assert sample_vehicle.get_cost_per_distance() is None
    db.session.add(FuelLog(**common, odometer=100, volume=10, total_cost=20))
    db.session.commit()
    assert sample_vehicle.get_total_distance() == 100
    sample_vehicle.starting_odometer = None
    assert sample_vehicle.get_total_distance() == 100


def test_tessie_baseline_units(app, sample_vehicle, monkeypatch):
    """Convert Tessie's kilometres before subtracting a miles baseline."""
    from app.models import Vehicle
    monkeypatch.setattr(Vehicle, 'uses_tessie_odometer', lambda self: True)
    sample_vehicle.odometer_unit = 'mi'
    sample_vehicle.tessie_last_odometer = 1000
    assert sample_vehicle.get_total_distance() == 1000  # Preserve legacy Tessie fallback.
    assert sample_vehicle.get_total_distance('mi') == pytest.approx(621.371)
    sample_vehicle.starting_odometer = 100
    assert sample_vehicle.get_total_distance() == pytest.approx(521.371)
    assert sample_vehicle.get_total_distance('km') == pytest.approx(1000 - 100 / 0.621371)


@pytest.mark.parametrize('value,expected', [('1,5', 1.5), ('1.234,56', 1234.56), ('1,234.56', 1234.56)])
def test_localised_baseline(auth_client, sample_vehicle, value, expected):
    """Accept decimal formats supported by the other vehicle form fields."""
    auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
        'name': sample_vehicle.name, 'vehicle_type': 'car', 'starting_odometer': value})
    db.session.refresh(sample_vehicle)
    assert sample_vehicle.starting_odometer == expected


def test_admin_edit_requires_vehicle_access(admin_client, sample_vehicle):
    """Deny an unshared vehicle but allow an administrator once it is shared."""
    url = f'/vehicles/{sample_vehicle.id}/edit'
    data = {'name': sample_vehicle.name, 'vehicle_type': 'car', 'starting_odometer': '100'}
    response = admin_client.post(url, data=data)
    assert response.status_code == 302
    assert sample_vehicle.starting_odometer is None
    sample_vehicle.is_shared = True
    db.session.commit()
    admin_client.post(url, data=data)
    db.session.refresh(sample_vehicle)
    assert sample_vehicle.starting_odometer == 100


@pytest.mark.parametrize('endpoint', ['/api/export/json', '/api/export/backup'])
@pytest.mark.parametrize('tracking,unit', [('mileage', 'mi'), ('hours', 'km')])
def test_baseline_export_restore_units(auth_client, sample_vehicle, admin_user, endpoint, tracking, unit):
    """Both backup formats retain the baseline and its unit interpretation."""
    import io
    import json
    import zipfile
    from app.models import Vehicle
    from app.services.backup_restore import restore_backup
    sample_vehicle.starting_odometer = 120.5
    sample_vehicle.odometer_unit = unit
    sample_vehicle.tracking_unit = tracking
    db.session.commit()
    response = auth_client.get(endpoint)
    assert response.status_code == 200
    if endpoint.endswith('backup'):
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            data = json.loads(archive.read('data.json'))
    else:
        data = response.get_json()
    restore_backup(data, admin_user)
    restored = Vehicle.query.filter_by(owner_id=admin_user.id).one()
    assert (restored.starting_odometer, restored.odometer_unit, restored.tracking_unit) == (120.5, unit, tracking)


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), 'bad', True])
def test_restore_rejects_invalid_baseline(app, test_user, value):
    """Reject corrupt backup baselines and roll back vehicle creation."""
    from app.models import Vehicle
    from app.services.backup_restore import BackupError, restore_backup
    data = {'vehicles': [{'name': 'Invalid baseline', 'starting_odometer': value}]}
    with pytest.raises(BackupError, match='Starting odometer'):
        restore_backup(data, test_user)
    assert Vehicle.query.filter_by(name='Invalid baseline').count() == 0
