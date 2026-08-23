import pytest
from app import db
from app.models import Vehicle


class TestDashboard:
    def test_dashboard_requires_auth(self, client):
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_dashboard_returns_200(self, auth_client):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200

    def test_dashboard_without_vehicles(self, auth_client):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200

    def test_dashboard_with_vehicles(self, auth_client, sample_vehicle):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200
        assert b'Test Car' in resp.data

    def test_dashboard_with_fuel_logs(self, auth_client, sample_fuel_log):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200

    def test_dashboard_with_expenses(self, auth_client, sample_expense):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200

    def test_dashboard_charts_label_currency(self, auth_client, sample_expense):
        """Both dashboard charts must say what their money axis is in (#289)."""
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'const currency = "GBP";' in body
        # The category chart's value axis (x, because indexAxis is 'y') and the
        # monthly spending chart's y axis both carry the currency as a title.
        assert body.count('text: currency') == 2
        assert body.count("' ' + currency") == 2

    def test_dashboard_chart_currency_is_escaped(self, app, auth_client, test_user):
        """A custom currency is free text, so it must not break out of the JS."""
        import json

        test_user.currency = 'X"Y'
        db.session.commit()
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'const currency = %s;' % json.dumps('X"Y') in body
        assert 'const currency = "X"Y";' not in body


class TestTimeline:
    def test_timeline_requires_auth(self, client, sample_vehicle):
        resp = client.get(f'/timeline/{sample_vehicle.id}', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_timeline_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200

    def test_timeline_with_fuel_logs(self, auth_client, sample_fuel_log, sample_vehicle):
        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200

    def test_timeline_with_expenses(self, auth_client, sample_expense, sample_vehicle):
        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200

    def test_timeline_404_for_nonexistent(self, auth_client):
        resp = auth_client.get('/timeline/99999')
        assert resp.status_code == 404

    def test_timeline_chart_months_unique(self, auth_client, sample_vehicle):
        """The Monthly Costs chart must show 12 distinct calendar months (#270).

        The old 30-day stepping drifted against month boundaries, duplicating
        a month and skipping another depending on the date the page loaded.
        """
        import json
        import re
        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200
        match = re.search(r'const chartData = (\{.*?\});', resp.get_data(as_text=True))
        assert match, 'chart data not found in timeline page'
        labels = json.loads(match.group(1))['labels']
        from datetime import datetime
        expected = []
        year, month = datetime.now().year, datetime.now().month
        for _ in range(12):
            expected.append(datetime(year, month, 1).strftime('%b %Y'))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        assert labels == list(reversed(expected))

    def test_timeline_other_user_vehicle_redirects(self, auth_client, admin_user):
        # Create a vehicle owned by admin
        other_vehicle = Vehicle(
            owner_id=admin_user.id,
            name='Admin Car',
            vehicle_type='car',
            fuel_type='petrol',
        )
        db.session.add(other_vehicle)
        db.session.commit()

        resp = auth_client.get(f'/timeline/{other_vehicle.id}', follow_redirects=True)
        assert resp.status_code == 200
        # Should redirect to dashboard since user doesn't have access
