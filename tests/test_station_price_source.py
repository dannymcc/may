"""Tests for the station price-source identity columns (#155).

Saved stations carry ``(price_source, external_id)`` so a live price
provider's own id for a forecourt can be recorded once and reused, rather
than re-derived from postcodes and addresses on every run.
"""

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import PRICE_SOURCES, FuelStation, User


def _station(user, name, **kwargs):
    station = FuelStation(user_id=user.id, name=name, **kwargs)
    db.session.add(station)
    db.session.commit()
    return station


@pytest.fixture
def other_user(app):
    user = User(username='otheruser', email='other@example.com')
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return user


class TestSchema:
    def test_columns_exist(self, app):
        cols = {c['name'] for c in inspect(db.engine).get_columns('fuel_stations')}
        assert 'price_source' in cols
        assert 'external_id' in cols

    def test_unique_index_exists(self, app):
        indexes = {i['name']: i for i in inspect(db.engine).get_indexes('fuel_stations')}
        index = indexes.get('ix_fuel_stations_source_external_id')
        assert index is not None
        assert index['unique']
        assert index['column_names'] == ['user_id', 'price_source', 'external_id']

    def test_defaults_to_unlinked(self, app, test_user):
        station = _station(test_user, 'Unlinked')
        assert station.price_source is None
        assert station.external_id is None
        assert station.price_source_label is None

    def test_several_unlinked_stations_are_allowed(self, app, test_user):
        # NULLs compare as distinct, so the unique index must not stop a user
        # keeping any number of stations with no provider link.
        _station(test_user, 'One')
        _station(test_user, 'Two')
        assert FuelStation.query.filter_by(price_source=None).count() == 2

    def test_same_forecourt_twice_for_one_user_is_rejected(self, app, test_user):
        _station(test_user, 'One', price_source='uk_fuel_prices', external_id='A1')
        with pytest.raises(IntegrityError):
            _station(test_user, 'Two', price_source='uk_fuel_prices', external_id='A1')
        db.session.rollback()

    def test_same_forecourt_for_two_users_is_allowed(self, app, test_user, other_user):
        _station(test_user, 'Mine', price_source='uk_fuel_prices', external_id='A1')
        _station(other_user, 'Theirs', price_source='uk_fuel_prices', external_id='A1')
        assert FuelStation.query.filter_by(external_id='A1').count() == 2

    def test_same_id_across_sources_is_allowed(self, app, test_user):
        _station(test_user, 'UK', price_source='uk_fuel_prices', external_id='A1')
        _station(test_user, 'DE', price_source='tankerkoenig', external_id='A1')
        assert FuelStation.query.filter_by(external_id='A1').count() == 2


class TestLookupAndLinking:
    def test_find_by_external_id(self, app, test_user):
        station = _station(test_user, 'Linked',
                           price_source='uk_fuel_prices', external_id='A1')
        found = FuelStation.find_by_external_id(test_user.id, 'uk_fuel_prices', 'A1')
        assert found is station

    def test_find_ignores_other_users(self, app, test_user, other_user):
        _station(test_user, 'Mine', price_source='uk_fuel_prices', external_id='A1')
        assert FuelStation.find_by_external_id(
            other_user.id, 'uk_fuel_prices', 'A1') is None

    def test_find_ignores_other_sources(self, app, test_user):
        _station(test_user, 'Mine', price_source='uk_fuel_prices', external_id='A1')
        assert FuelStation.find_by_external_id(
            test_user.id, 'tankerkoenig', 'A1') is None

    def test_find_with_missing_arguments(self, app, test_user):
        assert FuelStation.find_by_external_id(test_user.id, None, 'A1') is None
        assert FuelStation.find_by_external_id(test_user.id, 'uk_fuel_prices', None) is None

    def test_link_records_identity(self, app, test_user):
        station = _station(test_user, 'Unlinked')
        assert station.link_price_source('uk_fuel_prices', 'A1') is True
        db.session.commit()
        assert station.price_source == 'uk_fuel_prices'
        assert station.external_id == 'A1'

    def test_link_stringifies_the_id(self, app, test_user):
        station = _station(test_user, 'Unlinked')
        station.link_price_source('uk_fuel_prices', 1234)
        assert station.external_id == '1234'

    def test_link_leaves_an_existing_link_alone(self, app, test_user):
        station = _station(test_user, 'Linked',
                           price_source='uk_fuel_prices', external_id='A1')
        assert station.link_price_source('uk_fuel_prices', 'B2') is False
        assert station.external_id == 'A1'

    def test_link_refuses_a_clash_with_another_station(self, app, test_user):
        _station(test_user, 'First', price_source='uk_fuel_prices', external_id='A1')
        second = _station(test_user, 'Second')
        assert second.link_price_source('uk_fuel_prices', 'A1') is False
        assert second.price_source is None
        db.session.commit()  # must not trip the unique index

    def test_link_ignores_a_missing_id(self, app, test_user):
        station = _station(test_user, 'Unlinked')
        assert station.link_price_source('uk_fuel_prices', None) is False
        assert station.link_price_source(None, 'A1') is False
        assert station.price_source is None

    def test_price_source_label(self, app, test_user):
        station = _station(test_user, 'Linked',
                           price_source='uk_fuel_prices', external_id='A1')
        assert station.price_source_label == PRICE_SOURCES['uk_fuel_prices']

    def test_price_source_label_falls_back_to_the_key(self, app, test_user):
        station = _station(test_user, 'Linked',
                           price_source='something_new', external_id='A1')
        assert station.price_source_label == 'something_new'


class TestExport:
    def test_json_export_includes_the_link(self, auth_client, test_user):
        _station(test_user, 'Linked', price_source='uk_fuel_prices', external_id='A1')
        resp = auth_client.get('/api/export/json')
        assert resp.status_code == 200
        stations = resp.get_json()['fuel_stations']
        assert stations[0]['price_source'] == 'uk_fuel_prices'
        assert stations[0]['external_id'] == 'A1'
