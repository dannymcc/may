"""Tests for global search (#112)."""
from datetime import date

from app import db
from app.models import Expense, FuelLog


class TestSearch:
    def test_requires_auth(self, client):
        resp = client.get('/search/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_empty_query_shows_form_only(self, auth_client):
        resp = auth_client.get('/search/')
        assert resp.status_code == 200
        assert b'No results' not in resp.data

    def test_finds_expense_by_description(self, auth_client, sample_expense):
        resp = auth_client.get(f'/search/?q={sample_expense.description.split()[0]}')
        assert resp.status_code == 200
        assert sample_expense.description.encode() in resp.data

    def test_finds_expense_by_vendor(self, auth_client, sample_vehicle, test_user):
        expense = Expense(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 5, 1), category='repairs',
            description='Brake pads', cost=120.0, vendor='Halfords',
        )
        db.session.add(expense)
        db.session.commit()
        resp = auth_client.get('/search/?q=Halfords')
        assert resp.status_code == 200
        assert b'Brake pads' in resp.data

    def test_date_range_filters_results(self, auth_client, sample_vehicle, test_user):
        expense = Expense(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 1, 15), category='repairs',
            description='January-only-job', cost=50.0,
        )
        db.session.add(expense)
        db.session.commit()
        resp = auth_client.get('/search/?q=January-only&date_from=2026-02-01')
        assert b'January-only-job' not in resp.data
        resp = auth_client.get('/search/?q=January-only&date_from=2026-01-01&date_to=2026-01-31')
        assert b'January-only-job' in resp.data

    def test_finds_fuel_log_by_station(self, auth_client, sample_vehicle, test_user):
        log = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 6, 1), odometer=12345.0,
            volume=40.0, total_cost=60.0, station='Shell Garage Searchtown',
        )
        db.session.add(log)
        db.session.commit()
        resp = auth_client.get('/search/?q=Searchtown')
        assert resp.status_code == 200
        assert b'Shell Garage Searchtown' in resp.data

    def test_other_users_records_not_searchable(self, auth_client, admin_user):
        from app.models import Vehicle
        other_vehicle = Vehicle(
            owner_id=admin_user.id, name='Admin Car',
            vehicle_type='car', fuel_type='petrol',
        )
        db.session.add(other_vehicle)
        db.session.flush()
        expense = Expense(
            vehicle_id=other_vehicle.id, user_id=admin_user.id,
            date=date(2026, 5, 1), category='repairs',
            description='Secret-admin-expense', cost=1.0,
        )
        db.session.add(expense)
        db.session.commit()
        resp = auth_client.get('/search/?q=Secret-admin')
        assert b'Secret-admin-expense' not in resp.data
