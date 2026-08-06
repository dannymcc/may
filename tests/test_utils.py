"""Tests for app/utils.py — locale-tolerant helpers (#237, #238)."""
import pytest

from app.utils import parse_decimal, first_day_of_week


class TestParseDecimal:
    def test_period_decimal_unchanged(self):
        assert parse_decimal('9.99') == 9.99

    def test_literal_none_string_treated_as_absent(self):
        # A NULL field rendered into a form comes back as the text "None";
        # treat it like an empty submission rather than a parse error (#241).
        assert parse_decimal('None') is None
        assert parse_decimal('None', default=0) == 0

    def test_comma_decimal(self):
        assert parse_decimal('9,99') == 9.99

    def test_plain_integer_string(self):
        assert parse_decimal('42') == 42.0

    def test_grouped_with_decimal_comma(self):
        # German grouping: dot thousands, comma decimal.
        assert parse_decimal('1.234,56') == 1234.56

    def test_grouped_with_decimal_period(self):
        # Anglo grouping: comma thousands, dot decimal.
        assert parse_decimal('1,234.56') == 1234.56

    def test_multiple_commas_are_thousands_separators(self):
        assert parse_decimal('1,234,567') == 1234567.0

    def test_negative_comma_decimal(self):
        assert parse_decimal('-3,5') == -3.5

    def test_numeric_int_returned_as_float(self):
        assert parse_decimal(5) == 5.0
        assert isinstance(parse_decimal(5), float)

    def test_numeric_float_returned(self):
        assert parse_decimal(2.5) == 2.5

    def test_whitespace_is_stripped(self):
        assert parse_decimal('  12,5  ') == 12.5

    def test_none_returns_default(self):
        assert parse_decimal(None) is None
        assert parse_decimal(None, default=0) == 0

    def test_empty_string_returns_default(self):
        assert parse_decimal('') is None
        assert parse_decimal('   ', default=0.0) == 0.0

    def test_invalid_input_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_decimal('not a number')

    def test_bool_rejected(self):
        with pytest.raises(ValueError):
            parse_decimal(True)


class TestFirstDayOfWeek:
    def test_german_starts_monday(self):
        assert first_day_of_week('de-DE') == 1

    def test_english_starts_sunday(self):
        assert first_day_of_week('en') == 0
        assert first_day_of_week('en-US') == 0

    def test_french_starts_monday(self):
        assert first_day_of_week('fr-FR') == 1

    def test_underscore_locale_form(self):
        # Underscore-separated locales resolve by base language.
        assert first_day_of_week('en_US') == 0
        assert first_day_of_week('de_DE') == 1

    def test_territory_overrides_base_language(self):
        # UK/Irish/Antipodean English and European Portuguese are Monday-first
        # despite their base languages defaulting to Sunday.
        assert first_day_of_week('en-GB') == 1
        assert first_day_of_week('en_GB') == 1
        assert first_day_of_week('en-IE') == 1
        assert first_day_of_week('pt-PT') == 1
        assert first_day_of_week('pt-BR') == 0

    def test_unknown_locale_defaults_monday(self):
        assert first_day_of_week('xx-YY') == 1

    def test_empty_or_none_defaults_monday(self):
        assert first_day_of_week('') == 1
        assert first_day_of_week(None) == 1
