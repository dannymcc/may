"""Tests for the UK fuel price scheme integration (#258)."""

from datetime import date

import pytest

from app import db
from app.models import AppSettings, FuelPriceHistory, FuelStation
from app.services import uk_fuel_prices as ukfp
from app.services.uk_fuel_prices import (
    PRICE_SOURCE,
    SETTING_ENABLED,
    SETTING_FEEDS,
    SETTING_LAST_RUN,
    UKFuelPriceService,
)


FEED_PAYLOAD = {
    'last_updated': '01/03/2026 08:00:00',
    'stations': [
        {
            'site_id': 'A1',
            'brand': 'SHELL',
            'address': '123 Main St',
            'postcode': 'SW1A 1AA',
            'location': {'latitude': '51.5010', 'longitude': '-0.1416'},
            'prices': {'E10': 139.9, 'B7': 145.9, 'E5': 149.9, 'LPG': 89.9},
        },
        {
            'site_id': 'B2',
            'brand': 'BP',
            'address': '9 Other Rd',
            'postcode': 'M1 1AA',
            'location': {'latitude': 53.4808, 'longitude': -2.2426},
            'prices': {'E10': 1.359},
        },
    ],
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return self._payload


@pytest.fixture
def enabled_single_feed(app):
    """Enable the integration with one feed URL."""
    AppSettings.set(SETTING_ENABLED, 'true')
    AppSettings.set(SETTING_FEEDS, "Test Retailer|https://example.test/fuel.json")
    return 'https://example.test/fuel.json'


@pytest.fixture
def uk_station(app, test_user):
    station = FuelStation(
        user_id=test_user.id,
        name='Shell Westminster',
        brand='Shell',
        address='123 Main St',
        city='London',
        postcode='sw1a1aa',
    )
    db.session.add(station)
    db.session.commit()
    return station


@pytest.fixture
def fake_feed(monkeypatch):
    """Serve FEED_PAYLOAD to every requests.get call."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(FEED_PAYLOAD)

    monkeypatch.setattr(ukfp.requests, 'get', fake_get)
    return calls


class TestConfiguration:
    def test_disabled_by_default(self, app):
        assert UKFuelPriceService.is_enabled() is False

    def test_enabled_when_set(self, app):
        AppSettings.set(SETTING_ENABLED, 'true')
        assert UKFuelPriceService.is_enabled() is True

    def test_default_feeds_used_when_no_override(self, app):
        assert UKFuelPriceService.get_feeds() == UKFuelPriceService.DEFAULT_FEEDS

    def test_custom_feeds_override_defaults(self, app):
        AppSettings.set(SETTING_FEEDS, (
            "Retailer One|https://one.test/data.json\n"
            "\n"
            "# a comment\n"
            "https://two.test/data.json\n"
        ))
        feeds = UKFuelPriceService.get_feeds()
        assert feeds == {
            'Retailer One': 'https://one.test/data.json',
            'https://two.test/data.json': 'https://two.test/data.json',
        }


class TestParsing:
    def test_normalise_postcode(self):
        assert UKFuelPriceService.normalise_postcode(' sw1a 1aa ') == 'SW1A1AA'
        assert UKFuelPriceService.normalise_postcode(None) == ''

    def test_normalise_price_from_pence(self):
        assert UKFuelPriceService.normalise_price(139.9) == 1.399

    def test_normalise_price_already_in_pounds(self):
        assert UKFuelPriceService.normalise_price(1.359) == 1.359

    def test_normalise_price_rejects_junk(self):
        assert UKFuelPriceService.normalise_price('n/a') is None
        assert UKFuelPriceService.normalise_price(None) is None
        assert UKFuelPriceService.normalise_price(0) is None

    def test_parse_feed_maps_fuel_codes(self):
        forecourts = UKFuelPriceService.parse_feed(FEED_PAYLOAD, 'Test Retailer')
        assert len(forecourts) == 2
        first = forecourts[0]
        assert first['prices'] == {
            'petrol': 1.399,
            'diesel': 1.459,
            'petrol_premium': 1.499,
        }
        assert first['postcode_key'] == 'SW1A1AA'
        assert first['latitude'] == pytest.approx(51.5010)
        assert first['retailer'] == 'Test Retailer'

    def test_parse_feed_skips_entries_without_known_prices(self):
        payload = {'stations': [
            {'postcode': 'AB1 2CD', 'prices': {'XYZ': 100.0}},
            {'postcode': 'AB1 2CD', 'prices': {}},
            'not a dict',
        ]}
        assert UKFuelPriceService.parse_feed(payload) == []

    def test_parse_feed_handles_bad_payload(self):
        assert UKFuelPriceService.parse_feed(None) == []
        assert UKFuelPriceService.parse_feed({}) == []

    def test_parse_feed_tolerates_missing_location(self):
        payload = {'stations': [
            {'postcode': 'AB1 2CD', 'prices': {'E10': 140.0}},
        ]}
        forecourt = UKFuelPriceService.parse_feed(payload)[0]
        assert forecourt['latitude'] is None
        assert forecourt['longitude'] is None


class TestFetching:
    def test_fetch_collects_all_feeds(self, app, enabled_single_feed, fake_feed):
        forecourts, errors = UKFuelPriceService.fetch_forecourts()
        assert errors == []
        assert len(forecourts) == 2
        assert fake_feed == ['https://example.test/fuel.json']

    def test_fetch_records_http_errors(self, app, enabled_single_feed, monkeypatch):
        monkeypatch.setattr(
            ukfp.requests, 'get', lambda url, **kw: FakeResponse(None, status_code=503)
        )
        forecourts, errors = UKFuelPriceService.fetch_forecourts()
        assert forecourts == []
        assert errors == ['Test Retailer: HTTP 503']

    def test_fetch_records_invalid_json(self, app, enabled_single_feed, monkeypatch):
        monkeypatch.setattr(ukfp.requests, 'get', lambda url, **kw: FakeResponse(None))
        forecourts, errors = UKFuelPriceService.fetch_forecourts()
        assert forecourts == []
        assert errors == ['Test Retailer: invalid JSON']

    def test_fetch_records_connection_errors(self, app, enabled_single_feed, monkeypatch):
        def boom(url, **kwargs):
            raise ukfp.requests.exceptions.Timeout()

        monkeypatch.setattr(ukfp.requests, 'get', boom)
        forecourts, errors = UKFuelPriceService.fetch_forecourts()
        assert forecourts == []
        assert errors == ['Test Retailer: request timed out']


class TestMatching:
    def test_matches_on_postcode_ignoring_spacing(self, app, uk_station):
        forecourts = UKFuelPriceService.parse_feed(FEED_PAYLOAD)
        match = UKFuelPriceService.match_forecourt(uk_station, forecourts)
        assert match['site_id'] == 'A1'

    def test_no_match_without_postcode(self, app, uk_station):
        uk_station.postcode = None
        forecourts = UKFuelPriceService.parse_feed(FEED_PAYLOAD)
        assert UKFuelPriceService.match_forecourt(uk_station, forecourts) is None

    def test_no_match_for_unknown_postcode(self, app, uk_station):
        uk_station.postcode = 'ZZ99 9ZZ'
        forecourts = UKFuelPriceService.parse_feed(FEED_PAYLOAD)
        assert UKFuelPriceService.match_forecourt(uk_station, forecourts) is None

    def test_shared_postcode_resolved_by_brand(self, app, test_user):
        station = FuelStation(
            user_id=test_user.id, name='Esso Twin', brand='esso', postcode='AB1 2CD'
        )
        db.session.add(station)
        db.session.commit()
        forecourts = UKFuelPriceService.parse_feed({'stations': [
            {'site_id': 'X', 'brand': 'BP', 'postcode': 'AB1 2CD',
             'prices': {'E10': 140.0}},
            {'site_id': 'Y', 'brand': 'ESSO', 'postcode': 'AB1 2CD',
             'prices': {'E10': 141.0}},
        ]})
        match = UKFuelPriceService.match_forecourt(station, forecourts)
        assert match['site_id'] == 'Y'

    def test_shared_postcode_resolved_by_proximity(self, app, test_user):
        station = FuelStation(
            user_id=test_user.id, name='Corner Garage', postcode='AB1 2CD',
            latitude=51.5010, longitude=-0.1416,
        )
        db.session.add(station)
        db.session.commit()
        forecourts = UKFuelPriceService.parse_feed({'stations': [
            {'site_id': 'far', 'postcode': 'AB1 2CD', 'prices': {'E10': 140.0},
             'location': {'latitude': 53.4808, 'longitude': -2.2426}},
            {'site_id': 'near', 'postcode': 'AB1 2CD', 'prices': {'E10': 141.0},
             'location': {'latitude': 51.5012, 'longitude': -0.1418}},
        ]})
        match = UKFuelPriceService.match_forecourt(station, forecourts)
        assert match['site_id'] == 'near'


class TestLinkedMatching:
    """Stations linked to a scheme site_id match on identity alone (#155)."""

    def test_linked_station_matches_its_site_id(self, app, uk_station):
        uk_station.price_source = PRICE_SOURCE
        uk_station.external_id = 'B2'
        db.session.commit()

        forecourts = UKFuelPriceService.parse_feed(FEED_PAYLOAD)
        match = UKFuelPriceService.match_forecourt(uk_station, forecourts)
        # 'B2' wins even though the station's postcode points at 'A1'.
        assert match['site_id'] == 'B2'

    def test_linked_station_matches_without_a_postcode(self, app, uk_station):
        uk_station.postcode = None
        uk_station.price_source = PRICE_SOURCE
        uk_station.external_id = 'A1'
        db.session.commit()

        forecourts = UKFuelPriceService.parse_feed(FEED_PAYLOAD)
        match = UKFuelPriceService.match_forecourt(uk_station, forecourts)
        assert match['site_id'] == 'A1'

    def test_link_that_left_the_feed_is_unmatched(self, app, uk_station):
        uk_station.price_source = PRICE_SOURCE
        uk_station.external_id = 'GONE'
        db.session.commit()

        forecourts = UKFuelPriceService.parse_feed(FEED_PAYLOAD)
        assert UKFuelPriceService.match_forecourt(uk_station, forecourts) is None

    def test_link_to_another_source_is_ignored(self, app, uk_station):
        uk_station.price_source = 'tankerkoenig'
        uk_station.external_id = 'B2'
        db.session.commit()

        forecourts = UKFuelPriceService.parse_feed(FEED_PAYLOAD)
        match = UKFuelPriceService.match_forecourt(uk_station, forecourts)
        assert match['site_id'] == 'A1'

    def test_refresh_records_the_link(self, app, enabled_single_feed, fake_feed,
                                      uk_station):
        UKFuelPriceService.refresh_prices()
        db.session.refresh(uk_station)
        assert uk_station.price_source == PRICE_SOURCE
        assert uk_station.external_id == 'A1'

    def test_refresh_uses_the_link_on_later_runs(self, app, enabled_single_feed,
                                                 fake_feed, uk_station):
        UKFuelPriceService.refresh_prices()

        # The postcode now points nowhere, but the recorded site_id still does.
        uk_station.postcode = 'ZZ99 9ZZ'
        db.session.commit()

        stats = UKFuelPriceService.refresh_prices()
        assert stats['matched'] == 1
        assert stats['skipped'] == 0

    def test_refresh_does_not_link_two_stations_to_one_forecourt(
            self, app, enabled_single_feed, fake_feed, test_user, uk_station):
        twin = FuelStation(user_id=test_user.id, name='Shell Westminster (dup)',
                           postcode='SW1A 1AA')
        db.session.add(twin)
        db.session.commit()

        stats = UKFuelPriceService.refresh_prices()
        assert stats['matched'] == 2

        linked = FuelStation.query.filter_by(
            price_source=PRICE_SOURCE, external_id='A1').all()
        assert len(linked) == 1


class TestRefreshPrices:
    def test_refresh_records_prices(self, app, enabled_single_feed, fake_feed, uk_station):
        stats = UKFuelPriceService.refresh_prices()
        assert stats['matched'] == 1
        assert stats['prices'] == 3
        assert stats['errors'] == []

        entries = FuelPriceHistory.query.filter_by(station_id=uk_station.id).all()
        assert {e.fuel_type for e in entries} == {'petrol', 'diesel', 'petrol_premium'}
        petrol = next(e for e in entries if e.fuel_type == 'petrol')
        assert petrol.price_per_unit == 1.399
        assert petrol.date == date.today()
        assert petrol.user_id == uk_station.user_id

    def test_refresh_is_idempotent_within_a_day(self, app, enabled_single_feed,
                                                fake_feed, uk_station):
        UKFuelPriceService.refresh_prices()
        second = UKFuelPriceService.refresh_prices()
        assert second['prices'] == 0
        assert FuelPriceHistory.query.filter_by(station_id=uk_station.id).count() == 3

    def test_refresh_updates_a_changed_price(self, app, enabled_single_feed,
                                             fake_feed, uk_station):
        UKFuelPriceService.refresh_prices()
        entry = FuelPriceHistory.query.filter_by(
            station_id=uk_station.id, fuel_type='petrol'
        ).one()
        entry.price_per_unit = 1.0
        db.session.commit()

        stats = UKFuelPriceService.refresh_prices()
        assert stats['prices'] == 1
        db.session.refresh(entry)
        assert entry.price_per_unit == 1.399

    def test_refresh_skips_stations_without_postcode(self, app, enabled_single_feed,
                                                     fake_feed, test_user):
        station = FuelStation(user_id=test_user.id, name='Nowhere')
        db.session.add(station)
        db.session.commit()

        stats = UKFuelPriceService.refresh_prices()
        assert stats['skipped'] == 1
        assert stats['matched'] == 0
        assert FuelPriceHistory.query.count() == 0

    def test_refresh_counts_unmatched_stations(self, app, enabled_single_feed,
                                               fake_feed, test_user):
        station = FuelStation(user_id=test_user.id, name='Elsewhere', postcode='ZZ99 9ZZ')
        db.session.add(station)
        db.session.commit()

        stats = UKFuelPriceService.refresh_prices()
        assert stats['unmatched'] == 1
        assert stats['prices'] == 0

    def test_refresh_records_last_run(self, app, enabled_single_feed, fake_feed, uk_station):
        assert AppSettings.get(SETTING_LAST_RUN) is None
        UKFuelPriceService.refresh_prices()
        assert AppSettings.get(SETTING_LAST_RUN)

    def test_refresh_survives_a_dead_feed(self, app, uk_station, monkeypatch):
        AppSettings.set(SETTING_ENABLED, 'true')
        AppSettings.set(SETTING_FEEDS, (
            "Dead|https://dead.test/data.json\n"
            "Live|https://live.test/data.json"
        ))

        def fake_get(url, **kwargs):
            if 'dead' in url:
                raise ukfp.requests.exceptions.ConnectionError('nope')
            return FakeResponse(FEED_PAYLOAD)

        monkeypatch.setattr(ukfp.requests, 'get', fake_get)

        stats = UKFuelPriceService.refresh_prices()
        assert stats['matched'] == 1
        assert len(stats['errors']) == 1


class TestRefreshIfDue:
    def test_skipped_when_disabled(self, app, fake_feed, uk_station):
        assert UKFuelPriceService.refresh_if_due() is None
        assert fake_feed == []

    def test_runs_when_never_run_before(self, app, enabled_single_feed, fake_feed, uk_station):
        stats = UKFuelPriceService.refresh_if_due()
        assert stats['matched'] == 1

    def test_skipped_when_run_recently(self, app, enabled_single_feed, fake_feed, uk_station):
        UKFuelPriceService.refresh_if_due()
        fake_feed.clear()
        assert UKFuelPriceService.refresh_if_due() is None
        assert fake_feed == []

    def test_runs_again_when_last_run_is_unreadable(self, app, enabled_single_feed,
                                                    fake_feed, uk_station):
        AppSettings.set(SETTING_LAST_RUN, 'not-a-timestamp')
        assert UKFuelPriceService.refresh_if_due() is not None


class TestStationRoutes:
    def test_refresh_requires_auth(self, client):
        resp = client.post('/stations/uk-prices/refresh', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_refresh_rejected_when_disabled(self, auth_client, fake_feed, uk_station):
        resp = auth_client.post('/stations/uk-prices/refresh', follow_redirects=True)
        assert resp.status_code == 200
        assert FuelPriceHistory.query.count() == 0
        assert fake_feed == []

    def test_refresh_all_stations(self, auth_client, enabled_single_feed,
                                  fake_feed, uk_station):
        resp = auth_client.post('/stations/uk-prices/refresh', follow_redirects=True)
        assert resp.status_code == 200
        assert FuelPriceHistory.query.filter_by(station_id=uk_station.id).count() == 3

    def test_refresh_single_station(self, auth_client, enabled_single_feed,
                                    fake_feed, uk_station, test_user):
        other = FuelStation(user_id=test_user.id, name='Other', postcode='M1 1AA')
        db.session.add(other)
        db.session.commit()

        resp = auth_client.post(
            f'/stations/{uk_station.id}/uk-prices/refresh', follow_redirects=True
        )
        assert resp.status_code == 200
        assert FuelPriceHistory.query.filter_by(station_id=uk_station.id).count() == 3
        assert FuelPriceHistory.query.filter_by(station_id=other.id).count() == 0

    def test_refresh_single_station_404(self, auth_client, enabled_single_feed):
        resp = auth_client.post('/stations/9999/uk-prices/refresh')
        assert resp.status_code == 404

    def test_button_hidden_when_disabled(self, auth_client, uk_station):
        resp = auth_client.get('/stations/')
        assert b'Update UK Prices' not in resp.data

    def test_button_shown_when_enabled(self, auth_client, enabled_single_feed, uk_station):
        resp = auth_client.get('/stations/')
        assert b'Update UK Prices' in resp.data


class TestSettingsRoute:
    def test_requires_admin(self, auth_client):
        resp = auth_client.post('/auth/uk-fuel-settings', data={
            'uk_fuel_prices_enabled': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert UKFuelPriceService.is_enabled() is False

    def test_admin_can_enable(self, admin_client):
        resp = admin_client.post('/auth/uk-fuel-settings', data={
            'uk_fuel_prices_enabled': 'on',
            'uk_fuel_feed_urls': 'Test|https://example.test/fuel.json',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert UKFuelPriceService.is_enabled() is True
        assert UKFuelPriceService.get_feeds() == {'Test': 'https://example.test/fuel.json'}

    def test_admin_can_disable(self, admin_client):
        AppSettings.set(SETTING_ENABLED, 'true')
        admin_client.post('/auth/uk-fuel-settings', data={}, follow_redirects=True)
        assert UKFuelPriceService.is_enabled() is False

    def test_settings_page_renders_panel(self, admin_client):
        resp = admin_client.get('/auth/settings')
        assert resp.status_code == 200
        assert b'UK Fuel Prices' in resp.data
