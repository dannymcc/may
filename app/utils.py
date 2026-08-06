"""Shared utility helpers for May."""

import re


def parse_decimal(value, default=None):
    """Parse a user-entered number into a float, tolerating locale variations.

    Web browsers submit the raw text of ``inputmode="decimal"`` fields, and users
    in non-US locales frequently type a comma as the decimal separator (e.g. the
    German ``9,99`` for 9.99). Plain ``float()`` rejects those. This helper accepts:

    - Period decimals: ``"9.99"`` -> 9.99 (unchanged behaviour)
    - Comma decimals: ``"9,99"`` -> 9.99
    - Grouped values with a decimal comma: ``"1.234,56"`` -> 1234.56
    - Grouped values with a decimal period: ``"1,234.56"`` -> 1234.56
    - Values already numeric (int/float) are returned as float

    Empty / missing input returns ``default`` (``None`` by default) so callers can
    drop the ``... if request.form.get('x') else None`` guards.

    Genuinely non-numeric input raises ``ValueError`` (matching ``float()``), so
    existing error handling in the routes continues to work.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        # Guard against bools sneaking in as "numbers".
        raise ValueError(f"Cannot parse boolean {value!r} as a decimal")
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if s == '' or s == 'None':
        # A literal "None" is a server-rendered artefact of a NULL field (a
        # user wouldn't type it), so treat it as absent rather than invalid
        # (issues #217, #241).
        return default

    # Preserve a leading sign, strip spaces used as grouping separators.
    s = s.replace(' ', '').replace(' ', '')

    has_dot = '.' in s
    has_comma = ',' in s

    if has_dot and has_comma:
        # Both separators present: the right-most one is the decimal separator,
        # the other is a thousands separator to be removed.
        if s.rfind(',') > s.rfind('.'):
            # e.g. "1.234,56" -> decimal comma
            s = s.replace('.', '').replace(',', '.')
        else:
            # e.g. "1,234.56" -> decimal period
            s = s.replace(',', '')
    elif has_comma:
        if s.count(',') > 1:
            # Multiple commas can only be thousands separators, e.g. "1,234,567".
            s = s.replace(',', '')
        else:
            # A single comma is treated as a decimal separator, e.g. "9,99".
            s = s.replace(',', '.')
    # Only a period (or no separator) is left as-is: standard float parsing.

    return float(s)


# Locales whose calendars conventionally start the week on Sunday. Everything
# else (the ISO 8601 default used across most of Europe) starts on Monday.
_SUNDAY_FIRST_LOCALES = {'en', 'ja', 'ko', 'zh', 'pt'}

# Territory-specific exceptions to the base-language rule above: these regions
# use Monday-first calendars even though their base language defaults to Sunday
# (e.g. en-GB vs en-US, pt-PT vs pt-BR).
_MONDAY_FIRST_TAGS = {'en-gb', 'en-ie', 'en-au', 'en-nz', 'en-za', 'pt-pt', 'zh-cn'}


def first_day_of_week(locale):
    """Return the first day of the week for a locale (0 = Sunday, 1 = Monday).

    Uses a small locale -> first-day mapping. Full tags are checked first so
    territories can override their base language (``en-GB`` -> Monday), then
    region-agnostic codes resolve by base language (``de-DE`` -> ``de``).
    Unknown locales default to Monday, matching ISO 8601 and most non-US
    conventions.
    """
    if not locale:
        return 1
    tag = re.sub(r'_', '-', str(locale).strip().lower())
    if tag in _MONDAY_FIRST_TAGS:
        return 1
    base = tag.split('-', 1)[0]
    return 0 if base in _SUNDAY_FIRST_LOCALES else 1
