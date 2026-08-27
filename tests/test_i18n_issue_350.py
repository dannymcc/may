"""The Hungarian catalogue mixes formal and informal address (#350).

Hungarian distinguishes formal ("magázás", third-person forms addressed to
the reader: "Ellenőrizze", "a fiókja") from informal ("tegezés", second-person
forms: "Ellenőrizd", "a fiókod"). Everything the catalogue carried before the
bulk fill in #340 is informal -- "Kezeld a beállításaidat", "Válassz",
"Add meg" -- so that is the settled house style; a handful of the strings
#340 added were written formal instead, and one mixed both registers inside
a single sentence.

This is cosmetic: nothing was mistranslated. These tests pin the register so
the next bulk fill cannot quietly reintroduce the drift, and they check the
tidy-up did not disturb the catalogue itself.
"""
import os
import re

import pytest
from babel.messages.pofile import read_po

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSLATIONS_DIR = os.path.join(BASE_DIR, 'app', 'translations')
HU_PO = os.path.join(TRANSLATIONS_DIR, 'hu', 'LC_MESSAGES', 'messages.po')

# Formal address in Hungarian shows up in three shapes. Each entry is
# (pattern, informal counterpart), so a failure says what to write instead.
FORMAL_FORMS = [
    # Formal imperatives (third-person subjunctive used as a polite command).
    (r'\bEllenőrizze\b', 'Ellenőrizd'),
    (r'\bAdjon\b', 'Adj'),
    (r'\bAdja\b', 'Add'),
    (r'\bÁllítsa\b', 'Állítsd'),
    (r'\bÁllítson\b', 'Állíts'),
    (r'\bMentse\b', 'Mentsd'),
    (r'\bTöltse\b', 'Töltsd'),
    (r'\bTöltsön\b', 'Tölts'),
    (r'\bHagyja\b', 'Hagyd'),
    (r'\bKövesse\b', 'Kövesd'),
    (r'\bKérjen\b', 'Kérj'),
    (r'\bVálassza\b', 'Válaszd'),
    (r'\bVálasszon\b', 'Válassz'),
    (r'\bKattintson\b', 'Kattints'),
    (r'\bTörölje\b', 'Töröld'),
    (r'\bFrissítse\b', 'Frissítsd'),
    (r'\bMódosítsa\b', 'Módosítsd'),
    # Polite plural ("we ask you"), which reads as magázás next to tegezés.
    (r'\bKérjük\b', 'Kérlek'),
    # Formal second-person possessive: "your account" as a third-person
    # possessive ("a fiókja") rather than "a fiókod". Only a noun that can
    # belong to nobody but the reader is safe to match this bluntly: "-ait"
    # is an ordinary third-person possessive elsewhere ("az út adatait" is
    # the *trip's* details), so the rest are pinned string by string below
    # rather than by pattern.
    (r'\bfiókj\w*\b', 'a fiókod / fiókodban / fiókodba / fiókoddal'),
    # Formal indicative used to address the reader.
    (r'\bTörli ezt\b', 'Törlöd ezt'),
    (r'\bMielőtt elkezdi\b', 'Mielőtt elkezded'),
]


def _hu_catalogue():
    with open(HU_PO, encoding='utf-8') as handle:
        return read_po(handle)


def _hu_messages():
    """Every translated (msgid, msgstr) pair in the Hungarian catalogue."""
    return [
        (message.id, message.string)
        for message in _hu_catalogue()
        if message.id and message.string and isinstance(message.id, str)
    ]


class TestHungarianUsesInformalAddress:
    """Acceptance criterion: every msgstr in the hu catalogue addresses the
    reader informally, matching the pre-#340 strings."""

    @pytest.mark.parametrize(
        'pattern,informal', FORMAL_FORMS, ids=[p for p, _ in FORMAL_FORMS]
    )
    def test_no_formal_address(self, pattern, informal):
        compiled = re.compile(pattern)
        offenders = [
            f'{msgid!r} -> {msgstr!r}'
            for msgid, msgstr in _hu_messages()
            if compiled.search(msgstr)
        ]
        assert offenders == [], (
            f"Hungarian strings using formal address ({pattern}); the "
            f"catalogue is informal throughout, so use {informal!r} "
            f"instead (#350):\n" + '\n'.join(offenders)
        )

    def test_the_sales_tax_hint_is_informal(self):
        # The pair the issue quotes: the Sales Tax help text on the fuel
        # form read "adja össze" while the rest of the catalogue tegez.
        hint = dict(_hu_messages())[
            'Optional. Sales tax shown on the receipt, already included in '
            'the total cost. Add the amounts together where more than one '
            'tax applies.'
        ]
        assert 'add össze' in hint, hint
        assert 'adja össze' not in hint, hint

    def test_the_trip_templates_strapline_is_not_mixed(self):
        # trips/templates_index.html:9 managed both registers in one
        # sentence: a formal "Mentse el" governing an informal
        # "kitölthesd".
        strapline = dict(_hu_messages())[
            'Save common routes to quickly fill in trip details'
        ]
        assert strapline.startswith('Mentsd el'), strapline
        assert 'kitölthesd' in strapline, strapline

    def test_reader_owned_nouns_use_the_informal_possessive(self):
        # The cases a blanket "-ait" pattern cannot judge: here the thing
        # possessed belongs to the reader, so it needs "-aid", not "-ait".
        messages = dict(_hu_messages())
        restore = messages[
            'Restore a May backup, or import your data from other fuel '
            'tracking applications'
        ]
        assert 'adataidat' in restore, restore
        assert 'adatait' not in restore, restore

        forecourts = messages[
            'UK retailers publish forecourt prices under the government fuel '
            'price transparency scheme. May matches your saved stations to '
            'those forecourts by postcode and records the prices, so price '
            'history and Cheapest Fuel stay up to date without manual entry.'
        ]
        assert 'állomásaidat' in forecourts, forecourts
        assert 'állomásait' not in forecourts, forecourts


class TestHungarianCatalogueIsOtherwiseUnchanged:
    """The tidy-up is register only: it must not drop, add or blank an
    entry."""

    def test_msgids_still_match_the_template(self):
        with open(os.path.join(TRANSLATIONS_DIR, 'messages.pot'),
                  encoding='utf-8') as handle:
            template = read_po(handle)
        expected = {message.id for message in template if message.id}
        actual = {message.id for message in _hu_catalogue() if message.id}
        assert actual == expected, (
            f"missing: {sorted(expected - actual)}, "
            f"unexpected: {sorted(actual - expected)}"
        )

    def test_no_entry_was_left_untranslated(self):
        blank = [
            message.id for message in _hu_catalogue()
            if message.id and not message.string
        ]
        assert blank == [], f"untranslated Hungarian entries: {blank}"

    def test_no_entry_was_left_fuzzy(self):
        # pybabel compile skips fuzzy entries, so a fuzzy flag ships as
        # English.
        fuzzy = [
            message.id for message in _hu_catalogue()
            if message.id and message.fuzzy
        ]
        assert fuzzy == [], f"fuzzy Hungarian entries: {fuzzy}"
