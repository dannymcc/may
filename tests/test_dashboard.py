import pytest
from datetime import date

from app import db
from app.models import Attachment, ChargingSession, Vehicle


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

    def test_timeline_shows_fuel_log_notes(self, auth_client, sample_fuel_log, sample_vehicle):
        """Notes recorded against an entry are visible on the timeline (#284)."""
        sample_fuel_log.notes = 'Filled up before the long drive'
        db.session.commit()

        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Filled up before the long drive' in resp.data

    def test_timeline_shows_expense_notes(self, auth_client, sample_expense, sample_vehicle):
        sample_expense.notes = 'Independent garage, kept the receipt'
        db.session.commit()

        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Independent garage, kept the receipt' in resp.data

    def test_timeline_shows_charging_notes(self, auth_client, test_user, sample_vehicle):
        session = ChargingSession(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 2, 1),
            kwh_added=30.0,
            total_cost=12.0,
            notes='Rapid charger was half price',
        )
        db.session.add(session)
        db.session.commit()

        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Rapid charger was half price' in resp.data

    def test_timeline_escapes_notes(self, auth_client, sample_expense, sample_vehicle):
        """Notes are user input, so they must be escaped rather than rendered."""
        sample_expense.notes = '<script>alert(1)</script>'
        db.session.commit()

        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'<script>alert(1)</script>' not in resp.data
        assert b'&lt;script&gt;alert(1)&lt;/script&gt;' in resp.data

    def test_timeline_shows_expense_attachment_link(self, auth_client, sample_expense, sample_vehicle):
        attachment = Attachment(
            filename='abc123_receipt.pdf',
            original_filename='receipt.pdf',
            expense_id=sample_expense.id,
            vehicle_id=sample_vehicle.id,
        )
        db.session.add(attachment)
        db.session.commit()

        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'receipt.pdf' in resp.data
        assert b'/api/uploads/abc123_receipt.pdf' in resp.data

    def test_timeline_shows_fuel_log_attachment_link(self, auth_client, sample_fuel_log, sample_vehicle):
        attachment = Attachment(
            filename='def456_fuel.jpg',
            original_filename='fuel-receipt.jpg',
            fuel_log_id=sample_fuel_log.id,
            vehicle_id=sample_vehicle.id,
        )
        db.session.add(attachment)
        db.session.commit()

        resp = auth_client.get(f'/timeline/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'fuel-receipt.jpg' in resp.data
        assert b'/api/uploads/def456_fuel.jpg' in resp.data

    def test_timeline_attachments_not_shared_between_vehicles(self, auth_client, test_user,
                                                              sample_expense, sample_vehicle):
        """An attachment on another vehicle's expense must not leak onto this timeline."""
        other_vehicle = Vehicle(
            owner_id=test_user.id,
            name='Second Car',
            vehicle_type='car',
            fuel_type='petrol',
        )
        db.session.add(other_vehicle)
        db.session.commit()

        attachment = Attachment(
            filename='xyz789_other.pdf',
            original_filename='other-receipt.pdf',
            expense_id=sample_expense.id,
            vehicle_id=sample_vehicle.id,
        )
        db.session.add(attachment)
        db.session.commit()

        resp = auth_client.get(f'/timeline/{other_vehicle.id}')
        assert resp.status_code == 200
        assert b'other-receipt.pdf' not in resp.data
