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
    def test_expense_chart_x_axis_prefixes_currency(self, auth_client, sample_vehicle, sample_expense):
        """#359: the expense bar chart's x ticks carry the configured currency."""
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # The symbol is resolved server-side (£ for GBP, escaped as \u00a3 in the
        # JS string literal by tojson) and used in a ticks callback.
        assert r'const expenseCurrencySymbol = "\u00a3";' in body
        assert 'expenseCurrencySymbol + value.toLocaleString()' in body

    def test_expense_chart_currency_is_escaped(self, app, auth_client, sample_vehicle, test_user):
        """A custom currency is free text, so it must not break out of the JS."""
        import json

        test_user.currency = 'X"Y'
        db.session.commit()
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'const expenseCurrencySymbol = %s;' % json.dumps('X"Y') in body
        assert 'const expenseCurrencySymbol = "X"Y";' not in body


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
