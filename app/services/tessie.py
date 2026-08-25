"""
Tessie (Tesla) API Integration Service

Uses the Tessie API to fetch Tesla vehicle data including:
- Odometer reading
- Battery level and range
- Vehicle state

API Documentation: https://developer.tessie.com/
"""

import requests
from datetime import datetime
from app.models import AppSettings
from app.utils import utcfromtimestamp, utcnow


class TessieService:
    """Service for interacting with the Tessie API"""

    BASE_URL = "https://api.tessie.com"

    @classmethod
    def get_api_token(cls):
        """Get the Tessie API token from app settings"""
        return AppSettings.get('tessie_api_token')

    @classmethod
    def is_configured(cls):
        """Check if Tessie integration is configured"""
        return bool(cls.get_api_token())

    @classmethod
    def get_vehicle_state(cls, vin):
        """
        Fetch vehicle state from Tessie API

        Args:
            vin: Tesla vehicle VIN

        Returns:
            tuple: (success: bool, data: dict or error: str)
        """
        api_token = cls.get_api_token()
        if not api_token:
            return False, "Tessie API token not configured"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json"
        }

        try:
            response = requests.get(
                f"{cls.BASE_URL}/{vin}/state",
                headers=headers,
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                return True, cls._parse_response(data)
            elif response.status_code == 401:
                return False, "Invalid Tessie API token"
            elif response.status_code == 404:
                return False, "Vehicle not found or not connected to Tessie"
            else:
                return False, f"Tessie API error: {response.status_code}"

        except requests.exceptions.Timeout:
            return False, "Tessie API request timed out"
        except requests.exceptions.RequestException as e:
            return False, f"Tessie API connection error: {str(e)}"

    @classmethod
    def _parse_response(cls, data):
        """Parse the Tessie API response into a standardized format"""
        vehicle_state = data.get('vehicle_state', {})
        charge_state = data.get('charge_state', {})
        drive_state = data.get('drive_state', {})

        # Tessie returns odometer in miles, convert to km
        odometer_miles = vehicle_state.get('odometer', 0)
        odometer_km = odometer_miles * 1.60934

        battery_range_miles = charge_state.get('battery_range')
        battery_range_km = (battery_range_miles * 1.60934) if battery_range_miles else None

        return {
            'odometer_miles': odometer_miles,
            'odometer_km': odometer_km,
            'battery_level': charge_state.get('battery_level'),
            'battery_range_miles': battery_range_miles,
            'battery_range_km': battery_range_km,
            'charging_state': charge_state.get('charging_state'),
            'is_locked': vehicle_state.get('locked'),
            'car_version': vehicle_state.get('car_version'),
            'latitude': drive_state.get('latitude'),
            'longitude': drive_state.get('longitude'),
            'timestamp': utcnow()
        }

    @classmethod
    def test_api_token(cls, api_token):
        """
        Test if a Tessie API token is valid

        Makes a simple API call to verify the token works.
        Returns:
            tuple: (success: bool, message: str)
        """
        if not api_token:
            return False, "API token is required"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json"
        }

        try:
            response = requests.get(
                f"{cls.BASE_URL}/vehicles",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                count = len(data.get('results', []))
                return True, f"API token is valid ({count} vehicle{'s' if count != 1 else ''} found)"
            elif response.status_code == 401:
                return False, "Invalid API token"
            else:
                return False, f"Unexpected response: {response.status_code}"

        except requests.exceptions.Timeout:
            return False, "Request timed out"
        except requests.exceptions.RequestException as e:
            return False, f"Connection error: {str(e)}"

    @classmethod
    def get_vehicles(cls):
        """
        Get list of vehicles associated with the Tessie account

        Returns:
            tuple: (success: bool, list of vehicles or error: str)
        """
        api_token = cls.get_api_token()
        if not api_token:
            return False, "Tessie API token not configured"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json"
        }

        try:
            response = requests.get(
                f"{cls.BASE_URL}/vehicles",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                vehicles = []
                for v in data.get('results', []):
                    vehicles.append({
                        'vin': v.get('vin'),
                        'display_name': v.get('last_state', {}).get('display_name') or v.get('display_name'),
                        'state': v.get('state')
                    })
                return True, vehicles
            elif response.status_code == 401:
                return False, "Invalid API token"
            else:
                return False, f"API error: {response.status_code}"

        except requests.exceptions.RequestException as e:
            return False, f"Connection error: {str(e)}"

    @classmethod
    def get_charges(cls, vin, from_timestamp=None, to_timestamp=None, limit=100):
        """
        Get charging history from Tessie API

        Args:
            vin: Tesla vehicle VIN
            from_timestamp: Unix timestamp to start from (optional)
            to_timestamp: Unix timestamp to end at (optional)
            limit: Maximum number of results (default 100)

        Returns:
            tuple: (success: bool, list of charges or error: str)
        """
        api_token = cls.get_api_token()
        if not api_token:
            return False, "Tessie API token not configured"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json"
        }

        params = {
            "distance_format": "mi",
            "limit": limit
        }
        if from_timestamp:
            params["from"] = from_timestamp
        if to_timestamp:
            params["to"] = to_timestamp

        try:
            response = requests.get(
                f"{cls.BASE_URL}/{vin}/charges",
                headers=headers,
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                charges = []
                for c in data.get('results', []):
                    charges.append(cls._parse_charge(c))
                return True, charges
            elif response.status_code == 401:
                return False, "Invalid API token"
            elif response.status_code == 404:
                return False, "Vehicle not found"
            else:
                return False, f"API error: {response.status_code}"

        except requests.exceptions.Timeout:
            return False, "Request timed out"
        except requests.exceptions.RequestException as e:
            return False, f"Connection error: {str(e)}"

    @classmethod
    def _parse_charge(cls, data):
        """Parse a charge record from Tessie API"""
        # Parse timestamps - can be Unix timestamp (int) or ISO string
        started_at = data.get('started_at')
        ended_at = data.get('ended_at')

        def parse_timestamp(ts):
            if ts is None:
                return None
            if isinstance(ts, int):
                return utcfromtimestamp(ts)
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return None

        start_dt = parse_timestamp(started_at)
        end_dt = parse_timestamp(ended_at)

        # Odometer is in miles, convert to km for storage
        odometer_miles = data.get('odometer', 0)
        odometer_km = odometer_miles * 1.60934 if odometer_miles else None

        return {
            'tessie_id': data.get('id'),
            'date': start_dt.date() if start_dt else None,
            'start_time': start_dt.time() if start_dt else None,
            'end_time': end_dt.time() if end_dt else None,
            'location': data.get('location'),
            'is_supercharger': data.get('is_supercharger', False),
            'odometer_miles': odometer_miles,
            'odometer_km': odometer_km,
            'kwh_added': data.get('energy_added'),
            'start_soc': data.get('starting_battery'),
            'end_soc': data.get('ending_battery'),
            'cost': data.get('cost'),
            'latitude': data.get('latitude'),
            'longitude': data.get('longitude'),
        }
