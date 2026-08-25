"""Tests for language selection — LANGUAGES vs the shipped catalogues (#300)."""
import os
import re

from flask_babel import force_locale, gettext

from app import LANGUAGES, db

TRANSLATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'app', 'translations',
)


def _catalogue_dirs():
    """Language codes that have a directory under app/translations/."""
    return sorted(
        name for name in os.listdir(TRANSLATIONS_DIR)
        if os.path.isdir(os.path.join(TRANSLATIONS_DIR, name))
    )


class TestLanguageCatalogues:
    def test_every_translation_dir_is_listed(self):
        # A merged translation that never reaches LANGUAGES is dead weight:
        # it cannot be picked in settings and Babel never negotiates it.
        missing = [code for code in _catalogue_dirs() if code not in LANGUAGES]
        assert missing == [], (
            f"translation directories not listed in LANGUAGES: {missing}"
        )

    def test_every_language_has_a_catalogue(self):
        # The opposite mismatch: a code offered in the picker with no
        # catalogue behind it falls back to English without saying so.
        # 'en' is the Babel default/source locale and has no catalogue.
        missing = [
            code for code in LANGUAGES
            if code != 'en' and not os.path.isfile(
                os.path.join(TRANSLATIONS_DIR, code, 'LC_MESSAGES', 'messages.mo')
            )
        ]
        assert missing == [], (
            f"languages listed without a compiled catalogue: {missing}"
        )

    def test_hungarian_is_listed(self):
        assert LANGUAGES.get('hu') == 'Magyar'


class TestLanguagePicker:
    def test_hungarian_in_settings_picker(self, auth_client):
        response = auth_client.get('/auth/settings')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'value="hu"' in body
        assert 'Magyar' in body


class TestHungarianStrings:
    def test_hungarian_strings_render(self, app):
        # Assert the translation differs from the English source rather than
        # pinning the exact wording, so revising the catalogue is not a
        # breaking change.
        with force_locale('hu'):
            assert gettext('Dashboard') != 'Dashboard'


class TestUnitsAndValuesTranslation:
    """The Units & Values options on the settings page must go through
    gettext like the rest of the page (#310).

    "Liters (L)" already has a French catalogue entry ("Litres (L)")
    because it is marked for translation in vehicles/part_form.html and
    app/models.py. The settings page reuses the same English wording for
    its volume_unit option, but as a hard-coded literal rather than a
    gettext call, so it never picks up that existing translation no matter
    what language the user has selected.
    """

    def test_volume_unit_options_are_translated(self, client, test_user):
        test_user.language = 'fr'
        db.session.commit()

        client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'TestPass123!',
        }, follow_redirects=True)

        response = client.get('/auth/settings')
        assert response.status_code == 200
        body = response.get_data(as_text=True)

        assert 'Litres (L)' in body, (
            "the volume_unit option 'Liters (L)' is not passed through "
            "gettext() in settings.html, so it is never translated even "
            "though a French translation for it already exists in the "
            "catalogue"
        )

    def _french_settings_page(self, client, test_user):
        test_user.language = 'fr'
        db.session.commit()

        client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'TestPass123!',
        }, follow_redirects=True)

        response = client.get('/auth/settings')
        assert response.status_code == 200
        return response.get_data(as_text=True)

    def test_date_format_options_are_translated(self, client, test_user):
        body = self._french_settings_page(client, test_user)

        assert 'JJ/MM/AAAA (15/01/2024)' in body
        assert 'AAAA-MM-JJ (2024-01-15)' in body

    def test_distance_and_consumption_options_are_translated(
            self, client, test_user):
        body = self._french_settings_page(client, test_user)

        assert 'Kilomètres (km)' in body
        assert 'Gallons impériaux (gal)' in body
        assert 'Gallons américains (gal)' in body

    def test_option_values_stay_untranslated(self, client, test_user):
        # Only the labels are localised — the submitted values are what the
        # user record stores, so they must remain the English/unit codes.
        body = self._french_settings_page(client, test_user)

        for value in ('DD/MM/YYYY', 'YYYY-MM-DD', 'km', 'gal', 'us_gal',
                      'L/100km', 'mpg_us'):
            assert 'value="%s"' % value in body

    def test_every_catalogue_translates_the_unit_options(self, app):
        # Wrapping the options only helps if each shipped catalogue has an
        # entry for them; a missing entry renders as English.
        msgids = [
            'DD/MM/YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD', 'DD.MM.YYYY',
            'Kilometres (km)', 'Liters (L)', 'UK Gallons (gal)',
            'US Gallons (gal)',
        ]
        missing = []
        for code in _catalogue_dirs():
            with force_locale(code):
                missing += [
                    f'{code}: {msgid}' for msgid in msgids
                    if gettext(msgid) == msgid
                ]
        assert missing == [], (
            f"unit option labels with no catalogue entry: {missing}"
        )


class TestConsumptionUnitTranslation:
    """The Fuel Consumption dropdown's 'L/100km' option is still a bare
    literal in settings.html, unlike its siblings (distance_unit,
    volume_unit, date_format) which #310 already routed through gettext —
    this one option was missed. Because it never reaches _(), no catalogue
    can translate it, e.g. the Hungarian convention of a space between the
    number and the unit, "L/100 km" rather than "L/100km" (#328).
    """

    def _settings_source(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'app', 'templates', 'auth', 'settings.html',
        )
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_L100km_option_label_uses_gettext(self):
        source = self._settings_source()
        match = re.search(r'<option value="L/100km"[^>]*>(.*?)</option>', source)
        assert match is not None, (
            "could not find the L/100km option in settings.html — has it moved?"
        )
        assert '_(' in match.group(1), (
            "the L/100km option label in the Fuel Consumption dropdown is a "
            "bare literal rather than passed through gettext(), so it can "
            "never be translated no matter what language is selected (#328)"
        )

    def test_kmL_option_label_uses_gettext(self):
        # The same dropdown's other metric option was missed by #310 too.
        source = self._settings_source()
        match = re.search(r'<option value="km/L"[^>]*>(.*?)</option>', source)
        assert match is not None, (
            "could not find the km/L option in settings.html — has it moved?"
        )
        assert '_(' in match.group(1), (
            "the km/L option label in the Fuel Consumption dropdown is a "
            "bare literal rather than passed through gettext()"
        )

    def test_every_catalogue_carries_the_consumption_options(self):
        # Wrapping the labels only helps if each shipped catalogue has an
        # entry to translate them with. The wording itself is left to the
        # catalogues — several locales keep the source form — so assert the
        # entry exists and is filled in rather than pinning the text.
        missing = []
        for code in _catalogue_dirs():
            path = os.path.join(
                TRANSLATIONS_DIR, code, 'LC_MESSAGES', 'messages.po')
            with open(path, encoding='utf-8') as f:
                catalogue = f.read()
            for msgid in ('L/100km', 'km/L'):
                entry = re.search(
                    r'^msgid "%s"\nmsgstr "(.*)"$' % re.escape(msgid),
                    catalogue, re.MULTILINE,
                )
                if entry is None or not entry.group(1):
                    missing.append(f'{code}: {msgid}')
        assert missing == [], (
            f"consumption unit labels with no catalogue entry: {missing}"
        )

    def test_hungarian_consumption_label_renders_translated(
            self, client, test_user):
        # The reported case: Hungarian spaces the unit, "L/100 km". Read the
        # expected wording from the catalogue so revising it is not a
        # breaking change — what matters is that the page shows it at all.
        test_user.language = 'hu'
        db.session.commit()

        client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'TestPass123!',
        }, follow_redirects=True)

        response = client.get('/auth/settings')
        assert response.status_code == 200
        body = response.get_data(as_text=True)

        with force_locale('hu'):
            translated = gettext('L/100km')
        assert translated != 'L/100km', (
            "the Hungarian catalogue no longer distinguishes the L/100km "
            "label, so this test can no longer tell English from Hungarian"
        )
        assert '>%s</option>' % translated in body, (
            "the Fuel Consumption dropdown still renders the English "
            "'L/100km' for a Hungarian user (#328)"
        )
        # The submitted value is what the user record stores and must stay
        # in its English/unit-code form.
        assert 'value="L/100km"' in body
