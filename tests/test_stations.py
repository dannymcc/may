import pytest
from app import db
from app.models import FuelStation, FuelPriceHistory
from datetime import date


@pytest.fixture
def sample_station(app, test_user):
    station = FuelStation(
        user_id=test_user.id,
        name='Shell Station',
        brand='Shell',
        address='123 Main St',
        city='London',
        postcode='SW1A 1AA',
    )
    db.session.add(station)
    db.session.commit()
    return station


@pytest.fixture
def station_with_prices(app, test_user, sample_station):
    price = FuelPriceHistory(
        station_id=sample_station.id,
        user_id=test_user.id,
        date=date(2024, 3, 1),
        fuel_type='petrol',
        price_per_unit=1.60,
    )
    db.session.add(price)
    db.session.commit()
    return sample_station


class TestStationIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/stations/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/stations/')
        assert resp.status_code == 200

    def test_index_shows_stations(self, auth_client, sample_station):
        resp = auth_client.get('/stations/')
        assert resp.status_code == 200
        assert b'Shell Station' in resp.data


class TestStationNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/stations/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client):
        resp = auth_client.get('/stations/new')
        assert resp.status_code == 200

    def test_create_station(self, auth_client, test_user):
        resp = auth_client.post('/stations/new', data={
            'name': 'BP Station',
            'brand': 'BP',
            'address': '456 High St',
            'city': 'Manchester',
            'postcode': 'M1 1AA',
        }, follow_redirects=True)
        assert resp.status_code == 200
        station = FuelStation.query.filter_by(name='BP Station').first()
        assert station is not None
        assert station.brand == 'BP'


class TestStationEdit:
    def test_edit_requires_auth(self, client, sample_station):
        resp = client.get(f'/stations/{sample_station.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_station):
        resp = auth_client.get(f'/stations/{sample_station.id}/edit')
        assert resp.status_code == 200

    def test_edit_station(self, auth_client, sample_station):
        resp = auth_client.post(f'/stations/{sample_station.id}/edit', data={
            'name': 'Shell Garage',
            'brand': 'Shell',
            'address': '123 Main St',
            'city': 'London',
            'postcode': 'SW1A 1AA',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_station)
        assert sample_station.name == 'Shell Garage'


class TestStationDelete:
    def test_delete_requires_auth(self, client, sample_station):
        resp = client.post(f'/stations/{sample_station.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_station(self, auth_client, sample_station):
        station_id = sample_station.id
        resp = auth_client.post(f'/stations/{station_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert FuelStation.query.get(station_id) is None

    def test_delete_station_with_price_history(self, auth_client, test_user, sample_station):
        # #256 — deleting a station with price rows must cascade rather than
        # 500 on the NOT NULL station_id constraint.
        from datetime import date
        from app.models import FuelPriceHistory
        entry = FuelPriceHistory(
            station_id=sample_station.id,
            user_id=test_user.id,
            date=date(2026, 6, 9),
            fuel_type='petrol',
            price_per_unit=1.899,
        )
        db.session.add(entry)
        db.session.commit()
        station_id = sample_station.id
        resp = auth_client.post(f'/stations/{station_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert FuelStation.query.get(station_id) is None
        assert FuelPriceHistory.query.filter_by(station_id=station_id).count() == 0


class TestStationToggleFavorite:
    def test_toggle_requires_auth(self, client, sample_station):
        resp = client.post(f'/stations/{sample_station.id}/favorite', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_toggle_favorite(self, auth_client, sample_station):
        assert sample_station.is_favorite is False
        resp = auth_client.post(f'/stations/{sample_station.id}/favorite')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['is_favorite'] is True

    def test_toggle_favorite_twice(self, auth_client, sample_station):
        auth_client.post(f'/stations/{sample_station.id}/favorite')
        resp = auth_client.post(f'/stations/{sample_station.id}/favorite')
        data = resp.get_json()
        assert data['is_favorite'] is False


class TestStationPriceHistory:
    def test_price_history_requires_auth(self, client, sample_station):
        resp = client.get(f'/stations/{sample_station.id}/prices', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_price_history_returns_200(self, auth_client, station_with_prices):
        resp = auth_client.get(f'/stations/{station_with_prices.id}/prices')
        assert resp.status_code == 200

    def test_price_history_empty_station(self, auth_client, sample_station):
        resp = auth_client.get(f'/stations/{sample_station.id}/prices')
        assert resp.status_code == 200


class TestStationCheapest:
    def test_cheapest_requires_auth(self, client):
        resp = client.get('/stations/cheapest', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_cheapest_returns_200(self, auth_client):
        resp = auth_client.get('/stations/cheapest')
        assert resp.status_code == 200

    def test_cheapest_with_prices(self, auth_client, station_with_prices):
        resp = auth_client.get('/stations/cheapest')
        assert resp.status_code == 200


class TestStationDeletePrice:
    def test_delete_price_requires_auth(self, client, station_with_prices):
        price = FuelPriceHistory.query.filter_by(station_id=station_with_prices.id).first()
        resp = client.post(f'/stations/prices/{price.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_price_removes_entry(self, auth_client, station_with_prices):
        price = FuelPriceHistory.query.filter_by(station_id=station_with_prices.id).first()
        price_id = price.id
        resp = auth_client.post(f'/stations/prices/{price_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert FuelPriceHistory.query.get(price_id) is None

    def test_delete_price_other_user_blocked(self, auth_client, sample_station):
        from app.models import User
        other = User(username='other', email='other@example.com')
        other.set_password('pw')
        db.session.add(other)
        db.session.commit()
        price = FuelPriceHistory(
            station_id=sample_station.id,
            user_id=other.id,
            date=date(2024, 4, 1),
            fuel_type='petrol',
            price_per_unit=1.55,
        )
        db.session.add(price)
        db.session.commit()
        price_id = price.id
        resp = auth_client.post(f'/stations/prices/{price_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert FuelPriceHistory.query.get(price_id) is not None
