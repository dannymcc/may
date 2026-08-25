import pytest
from datetime import date
from app import db
from app.models import MileageAllowance


@pytest.fixture(scope='function')
def sample_allowance(app, test_user, sample_vehicle):
    allowance = MileageAllowance(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 1, 25),
        description='January business miles',
        distance=200.0,
        rate_per_unit=0.45,
        amount=90.0,
    )
    db.session.add(allowance)
    db.session.commit()
    return allowance


class TestAllowanceIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/allowance/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/allowance/')
        assert resp.status_code == 200

    def test_index_shows_allowances(self, auth_client, sample_allowance):
        resp = auth_client.get('/allowance/')
        assert resp.status_code == 200
        assert b'January business miles' in resp.data


class TestAllowanceNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/allowance/new', follow_redirects=False)
        assert resp.status_code == 302

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/allowance/new')
        assert resp.status_code == 200

    def test_create_allowance(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/allowance/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-02-10',
            'description': 'February miles',
            'distance': '100',
            'rate_per_unit': '0.45',
            'amount': '45.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        allowance = MileageAllowance.query.filter_by(description='February miles').first()
        assert allowance is not None
        assert allowance.amount == 45.0
        assert allowance.user_id == test_user.id

    def test_create_allowance_amount_only(self, auth_client, sample_vehicle):
        resp = auth_client.post('/allowance/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-02-12',
            'amount': '120.50',
        }, follow_redirects=True)
        assert resp.status_code == 200
        allowance = MileageAllowance.query.filter_by(amount=120.5).first()
        assert allowance is not None
        assert allowance.distance is None
        assert allowance.rate_per_unit is None


class TestAllowanceEdit:
    def test_edit_requires_auth(self, client, sample_allowance):
        resp = client.get(f'/allowance/{sample_allowance.id}/edit', follow_redirects=False)
        assert resp.status_code == 302

    def test_edit_allowance(self, auth_client, sample_allowance):
        resp = auth_client.post(f'/allowance/{sample_allowance.id}/edit', data={
            'date': '2024-01-25',
            'description': 'January business miles',
            'amount': '100.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_allowance)
        assert sample_allowance.amount == 100.0


class TestAllowanceDelete:
    def test_delete_allowance(self, auth_client, sample_allowance):
        allowance_id = sample_allowance.id
        resp = auth_client.post(f'/allowance/{allowance_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(MileageAllowance, allowance_id) is None


class TestAllowanceOffsetsCost:
    def test_total_allowance_and_net_cost(self, app, sample_vehicle, sample_fuel_log, sample_allowance):
        # sample_fuel_log total_cost = 60.0; sample_allowance amount = 90.0
        assert sample_vehicle.get_total_allowance() == 90.0
        gross = sample_vehicle.get_total_cost()
        assert sample_vehicle.get_net_cost() == gross - 90.0
