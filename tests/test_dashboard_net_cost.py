from datetime import date
import re
import pytest
from app import db
from app.models import Vehicle, Expense, MileageAllowance

@pytest.mark.parametrize('allowance, expected', [(100, '0.30'), (1000, '0.00'), (1300, '-0.10')])
def test_dashboard_weighted_net_cost(auth_client, test_user, sample_vehicle, monkeypatch, allowance, expected):
    second = Vehicle(owner_id=test_user.id, name='Second', vehicle_type='car', fuel_type='petrol', odometer_unit='mi')
    db.session.add(second)
    db.session.flush()
    test_user.distance_unit = 'km'
    def distance(vehicle, unit=None):
        assert unit == 'km'
        return 1000 if vehicle.id == sample_vehicle.id else 2000
    monkeypatch.setattr(Vehicle, 'get_total_distance', distance)
    for vehicle, cost in [(sample_vehicle, 800), (second, 200)]:
        db.session.add(Expense(vehicle_id=vehicle.id, user_id=test_user.id, date=date(2026, 10, 1), category='maintenance', description='Test', cost=cost))
    db.session.add(MileageAllowance(vehicle_id=sample_vehicle.id, user_id=test_user.id, date=date(2026, 10, 1), amount=allowance))
    db.session.commit()
    assert 'Net cost per km' not in auth_client.get('/dashboard').text
    test_user.show_net_cost_per_distance = True
    db.session.commit()
    response = auth_client.get('/dashboard')
    assert response.status_code == 200
    card = re.search(r'Net cost per km</dt>\s*<dd[^>]*>(.*?)</dd>', response.text, re.S)
    assert card and card.group(1).strip() == expected + ' GBP'
    second.tracking_unit = 'hours'
    db.session.commit()
    response = auth_client.get('/dashboard')
    assert 'Net cost per (mixed units)' in response.text
    card = re.search(r'Net cost per \(mixed units\)</dt>\s*<dd[^>]*>(.*?)</dd>', response.text, re.S)
    assert card and card.group(1).strip() == '-'
