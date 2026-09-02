"""Re-land the still-valid corrections from #339 against the current
Hungarian catalogue (#352).

#339 (burgatshow) forked at v0.41.1 and cannot be merged as-is: the bulk
fill in #340, the register fix in #350 and the pinning tests in #351 have
rewritten `messages.po` underneath it. But several of the individual fixes
it made are still genuine and still missing from the catalogue as it
stands on `dev` -- confirmed here by cross-checking each one against
translations the catalogue already uses *elsewhere* for the same or an
analogous English string:

- "Kilometres (km)" is missing its accent: "Kilometer" instead of
  "Kilométer".
- The ntfy hint has a doubled-letter typo, "toppic-ot" for "topic-ot".
- The Odometer family does not agree with itself: "Odometer when bought"
  says "Kilométeróra", but the bare "Odometer" is lowercase, "Odometer
  Unit" splits the compound in two ("Kilométer óra"), and "Last Odometer"
  reaches for a different word altogether ("futásteljesítmény", mileage
  covered, rather than the reading on the instrument). All four should say
  "Kilométeróra".
- "SMTP Host" is left as the untranslated English word "host", while the
  catalogue uses "szerver" for "server" throughout the same settings
  section (including two lines above it, in the ntfy hint).
- "Cost per" / "Price per" / "Discount per" use the English loanword
  "per", while the same catalogue already renders the near-identical
  "Cost per kWh" as "Költség / kWh" -- the "/" is the catalogue's own
  established convention for a per-unit label.

These are corrections #339 made and are still true on `dev`; they are not
superseded by #340's bulk fill (which only added new msgids) or #350's
register fix (these strings carry no imperative, so register was never the
issue). This module pins them so the fix lands and stays landed.

It also guards the trap noted against #339 specifically: the stray „…"
typographic quotes wrapped around four whole-sentence msgstrs, which must
not be reintroduced by copying #339's text verbatim.

One correction #339 made is deliberately *not* re-landed: its change of
the bare msgid "Registration" to "Rendszám" (number plate). That was right
against #339's base (v0.41.1), where the msgid was shared by the vehicle
detail page and the expense category, but #342 has since split the plate
label out into its own msgid, so "Registration" now carries only the
registration-fee expense category. Applying #339's change today would put
"number plate" in the expenses dropdown. That msgid is pinned below in the
sense it actually has instead.
"""
import os

from babel.messages.pofile import read_po

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HU_PO = os.path.join(BASE_DIR, 'app', 'translations', 'hu', 'LC_MESSAGES', 'messages.po')


def _hu_catalogue():
    with open(HU_PO, encoding='utf-8') as handle:
        return read_po(handle)


def _hu_messages():
    return {
        message.id: message.string
        for message in _hu_catalogue()
        if message.id and message.string and isinstance(message.id, str)
    }


class TestStillOutstandingCorrectionsFrom339:
    """Fixes #339 made that are still missing from the catalogue as it
    stands on dev, confirmed against how the catalogue already translates
    the same or an analogous string elsewhere."""

    def test_the_plate_and_the_expense_category_keep_their_own_senses(self):
        messages = _hu_messages()
        # The two plate msgids agree with each other, and always did:
        assert messages['Registration / License Plate'] == 'Rendszám'
        assert messages['Registration plate'] == 'Rendszám'
        # The bare "Registration" is *not* one of them. #339 changed it to
        # "Rendszám" too, which was right against its base (v0.41.1), where
        # the one msgid was shared by the vehicle detail page and the
        # expense category. #342 (9676dfe) has since given the plate label
        # its own string, so `_l('Registration')` now occurs once only, at
        # models.py:1383 in EXPENSE_CATEGORIES -- the registration/road-tax
        # fee. Re-landing #339's change here would read "number plate" in
        # the expenses dropdown, and would part hu from the other
        # catalogues, which all keep the two senses apart (de
        # Registrierung/Kennzeichen, fr Immatriculation, cs
        # Registrace/Registrační značka).
        assert messages['Registration'] == 'Regisztráció', messages['Registration']
        assert messages['Registration'] != messages['Registration plate']

    def test_kilometres_km_is_spelt_correctly(self):
        messages = _hu_messages()
        assert messages['Kilometres (km)'] == 'Kilométer (km)', messages['Kilometres (km)']

    def test_the_ntfy_hint_has_no_doubled_letter_typo(self):
        messages = _hu_messages()
        hint = messages[
            'For ntfy.sh, just enter your topic name. For self-hosted, enter the full URL.'
        ]
        assert 'toppic' not in hint, hint

    def test_the_odometer_family_uses_one_word_for_the_odometer(self):
        messages = _hu_messages()
        for msgid in ('Odometer Unit', 'Odometer when bought', 'Last Odometer'):
            assert 'Kilométeróra' in messages[msgid], (
                f'{msgid!r} -> {messages[msgid]!r}'
            )
        assert messages['Odometer'] == 'Kilométeróra', messages['Odometer']

    def test_smtp_host_is_translated_not_left_in_english(self):
        messages = _hu_messages()
        assert messages['SMTP Host'] != 'SMTP host'
        assert 'host' not in messages['SMTP Host'].lower(), messages['SMTP Host']

    def test_per_unit_labels_use_the_catalogues_own_slash_convention(self):
        messages = _hu_messages()
        # The catalogue's own precedent for a per-unit label:
        assert messages['Cost per kWh'] == 'Költség / kWh'
        # The generic "per" labels should follow the same convention
        # rather than the English loanword "per".
        for msgid in ('Cost per', 'Price per', 'Discount per'):
            assert 'per' not in messages[msgid].lower().split(), (
                f'{msgid!r} -> {messages[msgid]!r} still uses the English '
                f"loanword instead of the catalogue's own \"/\" convention"
            )


class TestNoStrayTypographicQuotes:
    """#339 review flagged four whole-sentence msgstrs wrapped in stray
    „…" quotation marks that must not be carried over into the catalogue."""

    def test_no_msgstr_is_wrapped_in_typographic_quotes(self):
        offenders = [
            f'{msgid!r} -> {msgstr!r}'
            for msgid, msgstr in _hu_messages().items()
            if msgstr.strip().startswith('„') and msgstr.strip().endswith('”')
        ]
        assert offenders == [], (
            'Hungarian msgstrs wrapped in stray „…" quotes (flagged in review '
            'of #339):\n' + '\n'.join(offenders)
        )
