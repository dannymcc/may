"""
UK Fuel Price Scheme Integration

Retailers in the UK government's fuel price transparency scheme publish a
JSON feed of forecourt prices. This service downloads those feeds, matches
the forecourts against saved fuel stations (by postcode, then brand or
proximity) and records the prices into FuelPriceHistory, so the existing
price history and "Cheapest Fuel" screens work from live data.

Scheme documentation (including the canonical list of retailer feeds):
https://www.gov.uk/guidance/access-the-latest-fuel-prices-and-forecourt-data-via-api-or-email

The default feed list below reflects the retailers published at the time of
writing. Retailers join and leave the scheme, so an admin can override the
list entirely in Settings -> Integrations -> UK Fuel Prices.
"""

from datetime import date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt

import requests

from app import db
from app.models import AppSettings, FuelPriceHistory, FuelStation
from app.utils import utcnow

#: Value stored in FuelStation.price_source for forecourts from this scheme.
PRICE_SOURCE = 'uk_fuel_prices'

# Setting keys
SETTING_ENABLED = 'uk_fuel_prices_enabled'
SETTING_FEEDS = 'uk_fuel_feed_urls'
SETTING_LAST_RUN = 'uk_fuel_prices_last_run'


class UKFuelPriceService:
    """Service for the UK fuel price transparency scheme feeds"""

    #: Retailer name -> feed URL, as published on the gov.uk guidance page.
    DEFAULT_FEEDS = {
        'Applegreen': 'https://applegreenstores.com/fuel-prices/data.json',
        'Asda': 'https://storelocator.asda.com/fuel_prices_data.json',
        'Ascona Group': 'https://fuelprices.asconagroup.co.uk/newfuel.json',
        'BP': 'https://www.bp.com/en_gb/united-kingdom/home/fuelprices/fuel_prices_data.json',
        'Esso Tesco Alliance': 'https://fuelprices.esso.co.uk/electronicfieldsystems/fuelvendor/EssoTescoJSON/data.json',
        'JET': 'https://jetlocal.co.uk/fuel_prices_data.json',
        'Morrisons': 'https://www.morrisons.com/fuel-prices/fuel.json',
        'Moto': 'https://moto-way.com/fuel-price/fuel_prices.json',
        'Motor Fuel Group': 'https://fuel.motorfuelgroup.com/fuel_prices_data.json',
        'Rontec': 'https://www.rontec-servicestations.co.uk/fuel-prices/data/fuel_prices_data.json',
        "Sainsbury's": 'https://api.sainsburys.co.uk/v1/exports/latest/fuel_prices_data.json',
        'Shell': 'https://www.shell.co.uk/fuel-prices-data.html',
        'Tesco': 'https://www.tesco.com/fuel_prices/fuel_prices_data.json',
    }

    #: Scheme fuel codes -> May fuel type strings.
    FUEL_CODE_MAP = {
        'E10': 'petrol',
        'E5': 'petrol_premium',
        'B7': 'diesel',
        'SDV': 'diesel_premium',
    }

    #: A forecourt has to be this close to a saved station's coordinates to
    #: count as a match when the postcode alone is ambiguous.
    MATCH_RADIUS_KM = 1.0

    REQUEST_TIMEOUT = 15

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @classmethod
    def is_enabled(cls):
        """Whether the integration has been switched on by an admin"""
        return AppSettings.get(SETTING_ENABLED, 'false') == 'true'

    @classmethod
    def get_feeds(cls):
        """Return the retailer name -> feed URL mapping in use.

        Admins can override the built-in list with one feed per line, each
        either `Name|https://...` or a bare URL.
        """
        custom = (AppSettings.get(SETTING_FEEDS) or '').strip()
        if not custom:
            return dict(cls.DEFAULT_FEEDS)

        feeds = {}
        for line in custom.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '|' in line:
                name, _, url = line.partition('|')
                name, url = name.strip(), url.strip()
            else:
                name, url = line, line
            if url:
                feeds[name or url] = url
        return feeds

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def normalise_postcode(postcode):
        """Uppercase a postcode and strip spaces/punctuation for comparison"""
        if not postcode:
            return ''
        return ''.join(c for c in str(postcode).upper() if c.isalnum())

    @staticmethod
    def normalise_price(value):
        """Convert a feed price to pounds per litre.

        Most retailers publish pence (139.9), a few publish pounds (1.399).
        Anything above 10 is therefore treated as pence.
        """
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        if price > 10:
            price = price / 100
        return round(price, 3)

    @classmethod
    def parse_feed(cls, payload, retailer=None):
        """Parse one retailer feed into a list of forecourt dicts.

        Malformed entries are skipped rather than failing the whole feed.
        """
        if not isinstance(payload, dict):
            return []

        forecourts = []
        for raw in payload.get('stations') or []:
            if not isinstance(raw, dict):
                continue

            prices = {}
            for code, value in (raw.get('prices') or {}).items():
                fuel_type = cls.FUEL_CODE_MAP.get(str(code).upper())
                if not fuel_type:
                    continue
                price = cls.normalise_price(value)
                if price is not None:
                    prices[fuel_type] = price

            if not prices:
                continue

            location = raw.get('location') or {}
            try:
                latitude = float(location.get('latitude'))
                longitude = float(location.get('longitude'))
            except (TypeError, ValueError):
                latitude = longitude = None

            forecourts.append({
                'site_id': raw.get('site_id'),
                'brand': raw.get('brand'),
                'address': raw.get('address'),
                'postcode': raw.get('postcode'),
                'postcode_key': cls.normalise_postcode(raw.get('postcode')),
                'latitude': latitude,
                'longitude': longitude,
                'prices': prices,
                'retailer': retailer,
            })

        return forecourts

    @staticmethod
    def _distance_km(lat1, lon1, lat2, lon2):
        """Great-circle distance between two points in kilometres"""
        radius = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = (
            sin(dlat / 2) ** 2
            + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        )
        return 2 * radius * asin(sqrt(a))

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    @classmethod
    def fetch_forecourts(cls, timeout=None):
        """Download and parse every configured feed.

        Returns:
            tuple: (forecourts: list[dict], errors: list[str])
        """
        forecourts = []
        errors = []

        for retailer, url in cls.get_feeds().items():
            try:
                response = requests.get(
                    url,
                    timeout=timeout or cls.REQUEST_TIMEOUT,
                    headers={'User-Agent': 'May Vehicle Management'},
                )
                if response.status_code != 200:
                    errors.append(f"{retailer}: HTTP {response.status_code}")
                    continue
                payload = response.json()
            except ValueError:
                errors.append(f"{retailer}: invalid JSON")
                continue
            except requests.exceptions.Timeout:
                errors.append(f"{retailer}: request timed out")
                continue
            except requests.exceptions.RequestException as e:
                errors.append(f"{retailer}: {e}")
                continue

            forecourts.extend(cls.parse_feed(payload, retailer))

        return forecourts, errors

    # ------------------------------------------------------------------
    # Matching and recording
    # ------------------------------------------------------------------

    @classmethod
    def match_forecourt(cls, station, forecourts):
        """Find the forecourt matching a saved station, or None.

        A station already linked to a scheme site_id is matched on that id
        alone: identity beats guesswork, and a link that has dropped out of
        the feed should read as unmatched rather than silently resolve to a
        different forecourt.

        Otherwise matching is by postcode. Where a postcode covers more than
        one forecourt, the nearest one within MATCH_RADIUS_KM wins, falling
        back to a brand match and finally to the first candidate.
        """
        if station.price_source == PRICE_SOURCE and station.external_id:
            for forecourt in forecourts:
                site_id = forecourt.get('site_id')
                if site_id is not None and str(site_id) == station.external_id:
                    return forecourt
            return None

        postcode_key = cls.normalise_postcode(station.postcode)
        if not postcode_key:
            return None

        candidates = [f for f in forecourts if f['postcode_key'] == postcode_key]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        if station.latitude is not None and station.longitude is not None:
            located = [
                f for f in candidates
                if f['latitude'] is not None and f['longitude'] is not None
            ]
            if located:
                nearest = min(located, key=lambda f: cls._distance_km(
                    station.latitude, station.longitude, f['latitude'], f['longitude']
                ))
                distance = cls._distance_km(
                    station.latitude, station.longitude,
                    nearest['latitude'], nearest['longitude'],
                )
                if distance <= cls.MATCH_RADIUS_KM:
                    return nearest

        if station.brand:
            brand = station.brand.strip().lower()
            for candidate in candidates:
                if (candidate.get('brand') or '').strip().lower() == brand:
                    return candidate

        return candidates[0]

    @classmethod
    def record_prices(cls, station, forecourt, on_date=None):
        """Store today's prices for a station, one row per fuel type.

        Re-running on the same day updates the existing rows instead of
        piling up duplicates, so the history stays one entry per day.
        Nothing is committed here; the caller commits.

        Returns:
            int: number of rows created or updated
        """
        on_date = on_date or date.today()
        changed = 0

        for fuel_type, price in forecourt['prices'].items():
            existing = FuelPriceHistory.query.filter_by(
                station_id=station.id,
                date=on_date,
                fuel_type=fuel_type,
            ).first()

            if existing:
                if existing.price_per_unit != price:
                    existing.price_per_unit = price
                    changed += 1
                continue

            db.session.add(FuelPriceHistory(
                station_id=station.id,
                user_id=station.user_id,
                date=on_date,
                fuel_type=fuel_type,
                price_per_unit=price,
            ))
            changed += 1

        return changed

    @classmethod
    def refresh_prices(cls, stations=None, timeout=None):
        """Pull live prices for saved stations.

        Args:
            stations: stations to update, or None for every saved station
            timeout: per-feed request timeout

        Returns:
            dict: {matched, unmatched, skipped, prices, errors}
        """
        if stations is None:
            stations = FuelStation.query.all()

        stats = {
            'matched': 0,
            'unmatched': 0,
            'skipped': 0,
            'prices': 0,
            'errors': [],
        }

        # Stations without a postcode can't be matched to a forecourt unless
        # a previous run already linked them to a scheme site_id.
        matchable = [
            s for s in stations
            if cls.normalise_postcode(s.postcode)
            or (s.price_source == PRICE_SOURCE and s.external_id)
        ]
        stats['skipped'] = len(stations) - len(matchable)
        if not matchable:
            return stats

        forecourts, errors = cls.fetch_forecourts(timeout=timeout)
        stats['errors'] = errors
        if not forecourts:
            stats['unmatched'] = len(matchable)
            return stats

        for station in matchable:
            forecourt = cls.match_forecourt(station, forecourts)
            if not forecourt:
                stats['unmatched'] += 1
                continue
            stats['matched'] += 1
            # Remember which forecourt this was, so later runs go straight
            # to it instead of re-running the postcode heuristics.
            station.link_price_source(PRICE_SOURCE, forecourt.get('site_id'))
            stats['prices'] += cls.record_prices(station, forecourt)

        db.session.commit()
        AppSettings.set(SETTING_LAST_RUN, utcnow().isoformat())

        return stats

    @classmethod
    def refresh_if_due(cls, min_interval_hours=6):
        """Refresh prices from the background scheduler, at most every N hours.

        Returns the refresh stats, or None when disabled or not yet due.
        """
        if not cls.is_enabled():
            return None

        last_run = AppSettings.get(SETTING_LAST_RUN)
        if last_run:
            try:
                previous = datetime.fromisoformat(last_run)
            except ValueError:
                previous = None
            if previous and utcnow() - previous < timedelta(hours=min_interval_hours):
                return None

        return cls.refresh_prices()
