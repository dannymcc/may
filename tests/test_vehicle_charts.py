"""Vehicle-view chart presentation.

Covers two reported faults on /vehicles/<id>:

- #359: the Expense-by-Category chart's value axis (the x axis, because the bar
  is horizontal) showed bare numbers with no currency unit.
- #358: the Fuel Consumption Trend and Fuel Price Trend charts rendered their
  date labels straight from the API's ISO strings, ignoring Settings > Date
  Format.
"""

from app import db


class TestExpenseChartCurrency:
    def test_expense_chart_uses_shared_currency_style(self, auth_client, sample_vehicle, sample_expense):
        """#369: the vehicle chart shares dashboard axis and tooltip units."""
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Use the account currency code consistently on both dashboards.
        assert 'const expenseCurrency = "GBP";' in body
        assert 'text: currency' in body
        assert "context.formattedValue + ' ' + currency" in body
        assert 'createExpenseCategoryChart(expensesEl, categoryData, expenseCurrency)' in body

    def test_expense_chart_currency_is_escaped(self, app, auth_client, sample_vehicle, test_user):
        """A custom currency is free text, so it must not break out of the JS."""
        import json

        test_user.currency = 'X"Y'
        db.session.commit()
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'const expenseCurrency = %s;' % json.dumps('X"Y') in body
        assert 'const expenseCurrency = "X"Y";' not in body


class TestTrendChartDateFormat:
    def test_trend_charts_reformat_dates_to_setting(self, auth_client, sample_vehicle):
        """#358: both trend charts route their ISO labels through the formatter."""
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # A single formatter is defined once and applied to both series.
        assert 'function formatChartDate(iso)' in body
        assert body.count('formatChartDate(d.date)') == 2
        # It reads the format from the meta tag base.html already exposes,
        # rather than inventing a second source of truth.
        assert 'meta[name="date-format"]' in body

    def test_formatter_covers_every_configured_format(self, auth_client, sample_vehicle):
        """Each of the four Settings date formats has a branch in the formatter."""
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        body = resp.get_data(as_text=True)
        for fmt in ('MM/DD/YYYY', 'YYYY-MM-DD', 'DD.MM.YYYY', 'DD/MM/YYYY'):
            assert "case '%s'" % fmt in body

    def test_date_format_meta_tag_reflects_user_setting(self, auth_client, sample_vehicle, test_user):
        """The meta tag the formatter reads must carry the user's chosen format."""
        test_user.date_format = 'DD.MM.YYYY'
        db.session.commit()
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        body = resp.get_data(as_text=True)
        assert '<meta name="date-format" content="DD.MM.YYYY">' in body


class TestCategoryRunningCosts:
    def test_both_charts_include_fuel_and_charging(self, auth_client, sample_vehicle,
                                                 sample_fuel_log, sample_charging_session):
        import json
        import re
        for url in ('/dashboard', f'/vehicles/{sample_vehicle.id}'):
            body = auth_client.get(url).get_data(as_text=True)
            data = json.loads(re.search(r'const categoryData = (.*);', body).group(1))
            assert data['Fuel'] == sample_fuel_log.total_cost
            assert data['Charging'] == sample_charging_session.total_cost

    def test_private_vehicle_fuel_is_excluded(self, auth_client, sample_vehicle,
                                            sample_fuel_log, admin_user):
        import json
        import re
        from datetime import date
        from app.models import Vehicle, FuelLog
        private = Vehicle(owner_id=admin_user.id, name='Private', vehicle_type='car', fuel_type='petrol')
        db.session.add(private)
        db.session.flush()
        db.session.add(FuelLog(vehicle_id=private.id, user_id=admin_user.id,
                               date=date.today(), odometer=100, total_cost=999))
        db.session.commit()
        for url in ('/dashboard', f'/vehicles/{sample_vehicle.id}'):
            body = auth_client.get(url).get_data(as_text=True)
            data = json.loads(re.search(r'const categoryData = (.*);', body).group(1))
            assert data['Fuel'] == sample_fuel_log.total_cost
