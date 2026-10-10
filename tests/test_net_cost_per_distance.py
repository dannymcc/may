from datetime import date
import re

import pytest

from app import db
from app.models import Expense, MileageAllowance, Vehicle


@pytest.mark.parametrize('allowance,expected', [(0, 1690.12 / 2053), (804.54, 885.58 / 2053), (1690.12, 0), (1800, -109.88 / 2053)])
def test_net_cost_card(auth_client, sample_vehicle, test_user, monkeypatch, allowance, expected):
    monkeypatch.setattr(Vehicle, 'get_total_distance', lambda self, *args: 2053)
    db.session.add(Expense(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                           date=date(2026, 10, 10), category='maintenance',
                           description='Recorded costs', cost=1690.12))
    if allowance:
        db.session.add(MileageAllowance(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                                        date=date(2026, 10, 10), amount=allowance))
    db.session.commit()
    assert sample_vehicle.get_net_cost_per_distance() == pytest.approx(expected)
    assert sample_vehicle.get_cost_per_distance() == pytest.approx(1690.12 / 2053)
    gross = auth_client.get(f'/vehicles/{sample_vehicle.id}')
    assert 'Net cost per km' not in gross.text
    assert '0.82' in gross.text
    saved = auth_client.post('/auth/settings', data={'show_net_cost_per_distance': 'on'})
    assert saved.status_code == 302
    db.session.refresh(test_user)
    assert test_user.show_net_cost_per_distance is True
    response = auth_client.get(f'/vehicles/{sample_vehicle.id}')
    assert 'Cost per km' in response.text
    assert '0.82' in response.text
    assert response.status_code == 200
    label = 'Net cost per km'
    card = re.search(label + r'.*?</dt>\s*<dd[^>]*>(.*?)</dd>', response.text, re.S)
    assert card
    assert card.group(1) == f'{expected:.2f}'


def test_no_distance_has_no_net_rate(app, sample_vehicle, monkeypatch):
    monkeypatch.setattr(Vehicle, 'get_total_distance', lambda self, *args: 0)
    assert sample_vehicle.get_net_cost_per_distance() is None


def test_settings_can_disable_net_card(auth_client, sample_vehicle, test_user):
    test_user.show_net_cost_per_distance = True
    db.session.commit()
    response = auth_client.post('/auth/settings', data={})
    assert response.status_code == 302
    db.session.refresh(test_user)
    assert test_user.show_net_cost_per_distance is False
    assert 'Net cost per km' not in auth_client.get(f'/vehicles/{sample_vehicle.id}?net_cost=1').text
