"""Minimal CalDAV publishing adapter."""
from base64 import b64encode
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from app.services.calendar import build_icalendar, payload_from_calendar_event


class CalDAVService:
    """Publish May calendar events to a CalDAV calendar collection."""

    @staticmethod
    def _event_url(calendar_url, uid):
        base = calendar_url if calendar_url.endswith('/') else f'{calendar_url}/'
        return urljoin(base, f'{quote(uid, safe="")}.ics')

    @staticmethod
    def publish_event(calendar_url, event, username=None, password=None, timeout=15):
        """PUT a single event as an .ics resource into a CalDAV collection."""
        if not calendar_url:
            return False, 'CalDAV calendar URL is required', None

        payload = payload_from_calendar_event(event)
        ics = build_icalendar([payload], calendar_name='May')
        event_url = CalDAVService._event_url(calendar_url, payload.uid)

        headers = {
            'Content-Type': 'text/calendar; charset=utf-8',
            'User-Agent': 'May-Vehicle-Manager/1.0',
        }
        if username and password:
            token = b64encode(f'{username}:{password}'.encode('utf-8')).decode('ascii')
            headers['Authorization'] = f'Basic {token}'
        if event.external_etag:
            headers['If-Match'] = event.external_etag

        request = Request(event_url, data=ics.encode('utf-8'), headers=headers, method='PUT')
        try:
            with urlopen(request, timeout=timeout) as response:
                etag = response.headers.get('ETag')
                return True, event_url, etag
        except HTTPError as e:
            return False, f'HTTP {e.code}: {e.reason}', None
        except URLError as e:
            return False, f'URL Error: {e.reason}', None
