from datetime import date
import re

from app import db
from app.models import FuelLog, Vehicle


def add_log(vehicle, user, price, fuel_type=None):
    log = FuelLog(vehicle_id=vehicle.id, user_id=user.id, date=date(2026, 9, 12),
                  odometer=100, volume=10, price_per_unit=price, fuel_type=fuel_type)
    db.session.add(log)
    db.session.commit()


def test_quick_price_uses_primary_fuel_and_preserves_zero(auth_client, sample_vehicle, test_user):
    from app.routes.fuel import get_last_fuel_price
    sample_vehicle.fuel_type = 'diesel'
    add_log(sample_vehicle, test_user, 1.5)
    add_log(sample_vehicle, test_user, 0.8, 'adblue')
    assert get_last_fuel_price(sample_vehicle, test_user.id) == 1.5
    add_log(sample_vehicle, test_user, 0, 'diesel')
    add_log(sample_vehicle, test_user, -1, 'diesel')
    assert get_last_fuel_price(sample_vehicle, test_user.id) == 0
    html = auth_client.get(f'/fuel/quick?vehicle_id={sample_vehicle.id}').text
    assert re.search(r'id="price_per_unit"[^>]*value="0(?:\.0)?"', html)


def test_quick_prices_follow_vehicle_and_missing_default(auth_client, sample_vehicle, test_user):
    other = Vehicle(owner_id=test_user.id, name='Second car', vehicle_type='car', fuel_type='petrol')
    db.session.add(other)
    db.session.commit()
    add_log(sample_vehicle, test_user, 1.5)
    add_log(other, test_user, 1.8)
    html = auth_client.get('/fuel/quick').text
    assert 'data-last-price="1.5"' in html
    assert 'data-last-price="1.8"' in html
    assert re.search(r'id="price_per_unit"[^>]*value="1\.[58]"', html)
    html = auth_client.get(f'/fuel/quick?vehicle_id={other.id}').text
    assert re.search(r'id="price_per_unit"[^>]*value="1.8"', html)


def test_quick_price_excludes_other_users_and_invalid_vehicle(auth_client, sample_vehicle, test_user, admin_user):
    from app.routes.fuel import get_last_fuel_price
    add_log(sample_vehicle, admin_user, 9)
    assert get_last_fuel_price(sample_vehicle, test_user.id) is None
    private = Vehicle(owner_id=admin_user.id, name='Private', vehicle_type='car', fuel_type='petrol')
    db.session.add(private)
    db.session.commit()
    add_log(private, test_user, 8)
    html = auth_client.get(f'/fuel/quick?vehicle_id={private.id}').text
    assert 'data-last-price="8' not in html
    assert re.search(r'id="price_per_unit"[^>]*value=""', html)
