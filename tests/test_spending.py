"""Tests for the unified Spending page (fuel + expenses + charging)."""
from datetime import date

import pytest

from app import db
from app.models import FuelLog, Expense, ChargingSession


@pytest.fixture
def spending_data(app, test_user, sample_vehicle):
    v = sample_vehicle
    db.session.add(FuelLog(vehicle_id=v.id, user_id=test_user.id, date=date.today(),
                           odometer=100, total_cost=50, station='Shell'))
    db.session.add(Expense(vehicle_id=v.id, user_id=test_user.id, date=date.today(),
                           category='tax', description='Road tax', cost=200))
    db.session.add(ChargingSession(vehicle_id=v.id, user_id=test_user.id, date=date.today(),
                                   total_cost=12, location='Home'))
    db.session.commit()
    return v


class TestSpendingPage:
    def test_page_renders_and_merges_all_three(self, auth_client, spending_data):
        resp = auth_client.get('/spending/')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'Shell' in body        # fuel
        assert 'Road tax' in body     # expense
        assert 'Home' in body         # charging

    def test_type_filter_scopes_the_ledger(self, auth_client, spending_data):
        # Charging is folded into fuel, so the fuel filter shows fill-ups AND charges.
        body = auth_client.get('/spending/?type=fuel').get_data(as_text=True)
        assert 'Shell' in body        # fuel fill-up
        assert 'Home' in body         # charge, now part of fuel
        assert 'Road tax' not in body  # expense excluded

    def test_disabling_fuel_hides_fills_and_charges(self, auth_client, test_user, spending_data):
        # Fuel now gates both fill-ups and charges; expenses stay.
        test_user.show_menu_fuel = False
        db.session.commit()
        body = auth_client.get('/spending/').get_data(as_text=True)
        assert 'Shell' not in body     # fuel fill-up hidden
        assert 'Home' not in body      # charge hidden with it
        assert 'Road tax' in body      # expenses still shown

    def test_source_pages_still_run(self, auth_client, spending_data):
        for path in ('/fuel/', '/expenses/', '/charging/'):
            assert auth_client.get(path).status_code == 200


class TestSpendingMenuToggle:
    def test_nav_shows_spending_link(self, auth_client, sample_vehicle):
        body = auth_client.get('/', follow_redirects=True).get_data(as_text=True)
        assert 'href="/spending/"' in body

    def test_settings_page_offers_the_toggle(self, auth_client):
        # The settings page must let the user select/deselect the Spending item.
        body = auth_client.get('/auth/settings').get_data(as_text=True)
        assert 'name="show_menu_spending"' in body

    def test_spending_hidden_from_nav_when_disabled(self, auth_client, test_user):
        test_user.show_menu_spending = False
        db.session.commit()
        body = auth_client.get('/', follow_redirects=True).get_data(as_text=True)
        assert 'href="/spending/"' not in body
