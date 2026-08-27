"""Pin the address register of the other T-V catalogues from #340 (#351).

#350 found that the bulk translation fill in #340 had written a handful of
formal-register strings into the Hungarian catalogue, which had been
informal since long before #340. #351 asks whether the same fill did the
same to the other catalogues whose language draws a T-V distinction.

The audit compared each catalogue's pre-#340 strings (``git show
2132f12^``) against the strings #340 added, looking at both the address
pronoun and -- for the pro-drop languages, where the pronoun is usually
absent and the register is carried by the verb -- the imperative
conjugation. Every one of the nine is internally consistent, before and
after the fill:

===  ========  ==================================================
loc  register  what marks it
===  ========  ==================================================
de   formal    Sie / Ihr, and Sie-imperatives ("Prüfen Sie")
fr   formal    vous / votre / vos
es   formal    usted / su, and usted-imperatives ("Compruebe")
nl   formal    u / uw, never je / jouw
it   informal  tu / tuo, and tu-imperatives ("Aggiungi", "Scegli")
pt   informal  você-register: seu / sua, "Adicione", never tu-forms
pl   informal  ty / Ci, with the catalogue's own convention of
               capitalising the possessive ("Twoje konto")
cs   formal    váš / vaše, and vy-imperatives ("Zadejte")
ru   formal    ваш, and вы-imperatives ("Укажите")
===  ========  ==================================================

So nothing needed correcting: Hungarian looks to have been an isolated
slip in that batch rather than a systemic fault. These tests exist only so
that stays true. They record the register each catalogue settled on and
fail if a future bulk fill introduces the other one, which is how #350 got
in and sat there until a native speaker noticed.

Two shapes of check per catalogue: no marker of the wrong register
anywhere, and the settled register still present in quantity, so a fill
cannot quietly flip the catalogue wholesale either.
"""
import os
import re

import pytest
from babel.messages.pofile import read_po

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSLATIONS_DIR = os.path.join(BASE_DIR, 'app', 'translations')

# The languages named in #351: those among #340's nineteen catalogues that
# draw a T-V distinction. Hungarian is handled by test_i18n_issue_350.
AUDITED = ['de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'cs', 'ru']

# Markers of the register the catalogue did *not* choose. Each entry is
# (pattern, what to write instead), so a failure says what the fix is.
# Only patterns that cannot fire on the settled register are listed: a
# blunter net would catch homographs (Italian "sua" is an ordinary
# third-person possessive, Polish "Proszę" is an impersonal "please" that
# sits happily beside informal address) and the test would cry wolf.
WRONG_REGISTER = {
    'de': [
        (r'\b[Dd]u\b', 'Sie'),
        (r'\b[Dd]ein\w*\b', 'Ihr / Ihre / Ihren'),
        (r'\b[Dd]ich\b', 'Sie'),
        (r'\b[Dd]ir\b', 'Ihnen'),
        (r'\b[Ee]uer\b', 'Ihr'),
        (r'\b[Ee]ure\w*\b', 'Ihre'),
    ],
    'fr': [
        (r'\b[Tt]u\b', 'vous'),
        (r'\b[Tt]on\b', 'votre'),
        (r'\b[Tt]es\b', 'vos'),
        (r'\btoi\b', 'vous'),
    ],
    'es': [
        (r'\b[Tt][uú]\b', 'usted / su'),
        (r'\b[Tt]us\b', 'sus'),
        (r'\bti\b', 'usted'),
        (r'\bcontigo\b', 'con usted'),
    ],
    'nl': [
        (r'\b[Jj]e\b', 'u / uw'),
        (r'\b[Jj]ij\b', 'u'),
        (r'\b[Jj]ouw\w*\b', 'uw'),
    ],
    # Czech and Russian drop the pronoun, so the register lives in the
    # imperative ending: informal -ej/-i against formal -ejte/-ите. The
    # informal counterparts of the verbs these catalogues actually use are
    # listed rather than a general ending pattern, which would misfire on
    # ordinary indicatives.
    'cs': [
        (r'\b[Tt]v[ůu]j\b', 'váš'),
        (r'\b[Tt]voj\w+\b', 'vaše / vašeho / vašem'),
        (r'\b[Tt]vého\b', 'vašeho'),
        (r'\bMůžeš\b', 'Můžete'),
        (r'\bpotřebuješ\b', 'potřebujete'),
        (r'\buvidíš\b', 'uvidíte'),
        (r'\bZadej\b', 'Zadejte'),
        (r'\bZkontroluj\b', 'Zkontrolujte'),
        (r'\bPřidej\b', 'Přidejte'),
        (r'\bNahraj\b', 'Nahrajte'),
        (r'\bPonech\b', 'Ponechte'),
        (r'\bSleduj\b', 'Sledujte'),
        (r'\bDoplň\b', 'Doplňte'),
        (r'\bObnov\b', 'Obnovte'),
    ],
    'ru': [
        (r'\b[Тт]вой\b', 'ваш'),
        (r'\b[Тт]во[яеёию]\w*\b', 'ваша / ваше / вашу'),
        (r'\b[Тт]ы\b', 'вы'),
        (r'\bПроверь\b', 'Проверьте'),
        (r'\bУкажи\b', 'Укажите'),
        (r'\bЗагрузи\b', 'Загрузите'),
        (r'\bОставь\b', 'Оставьте'),
        (r'\bДобавь\b', 'Добавьте'),
        (r'\bОтслеживай\b', 'Отслеживайте'),
        (r'\bОбратись\b', 'Обратитесь'),
        (r'\bсможешь\b', 'сможете'),
    ],
    # Italian and Polish went the other way: informal throughout, so it is
    # the formal forms that must not appear. Italian formal address
    # capitalises ("Lei", "Suo") to separate itself from the third person,
    # which is what makes it safe to match here.
    'it': [
        (r'\bLei\b', 'tu'),
        (r'\bSuo\b', 'tuo'),
        (r'\bSua\b', 'tua'),
        (r'\bSuoi\b', 'tuoi'),
        (r'\bSue\b', 'tue'),
        (r'\bLa preghiamo\b', 'a plain informal imperative'),
        (r'\bVoglia\b', 'a plain informal imperative'),
    ],
    'pl': [
        # Polish formal address declines, so catch the cases too.
        (r'\bPan(a|u|em|ie)?\b', 'ty-forms'),
        (r'\bPani(ą|ę)?\b', 'ty-forms'),
        (r'\bPaństw\w+\b', 'ty-forms'),
        (r'\bPańsk\w+\b', 'Twój / Twoje'),
    ],
    # Portuguese here is the você register (third-person forms addressed to
    # the reader), not tu; the tu-conjugated imperatives are the tell.
    'pt': [
        (r'\b[Tt]eu\b', 'seu'),
        (r'\b[Tt]ua\b', 'sua'),
        (r'\b[Tt]eus\b', 'seus'),
        (r'\b[Tt]uas\b', 'suas'),
        (r'\b[Tt]u\b', 'você'),
        (r'\bcontigo\b', 'com você'),
        (r'\bAdiciona\b', 'Adicione'),
        (r'\bEscolhe\b', 'Escolha'),
        (r'\bVerifica\b', 'Verifique'),
    ],
}

# The settled register, and a floor on how many strings carry it. The
# floors sit at roughly half the present count: loose enough that ordinary
# translation work does not trip them, tight enough that a bulk fill which
# flipped the catalogue wholesale would.
SETTLED_REGISTER = {
    'de': ('formal (Sie/Ihr)', r'\bSie\b|\bIhre?\w*\b|\bIhnen\b', 60),
    'fr': ('formal (vous/votre)', r'\b[Vv]ous\b|\b[Vv]otre\b|\b[Vv]os\b', 45),
    'es': ('formal (usted/su)', r'\busted\b|\b[Ss]us?\b', 35),
    'nl': ('formal (u/uw)', r'\b[Uu]\b|\b[Uu]w\b', 45),
    'cs': ('formal (váš, -ejte imperatives)', r'\b[Vv]áš\b|\b[Vv]aš\w+\b', 12),
    'ru': ('formal (ваш, -ите imperatives)', r'\b[Вв]аш\w*\b|\b[Вв]ы\b', 12),
    'it': ('informal (tu/tuo)', r'\btuo\b|\btua\b|\btuoi\b|\btue\b|\bPuoi\b|\bti\b', 30),
    'pl': ('informal (ty/Ci, capitalised possessive)',
           r'\bTw[oó]j\w*\b|\bTwoj\w+\b|\bMożesz\b|\bCi\b', 8),
    'pt': ('informal você-register (seu/sua)',
           r'\bvocê\b|\b[Ss]eus?\b|\b[Ss]uas?\b', 30),
}


def _catalogue(locale):
    path = os.path.join(TRANSLATIONS_DIR, locale, 'LC_MESSAGES', 'messages.po')
    with open(path, encoding='utf-8') as handle:
        return read_po(handle)


def _messages(locale):
    """Every translated (msgid, msgstr) pair in a catalogue."""
    return [
        (message.id, message.string)
        for message in _catalogue(locale)
        if message.id and message.string and isinstance(message.id, str)
    ]


def _wrong_register_cases():
    for locale, entries in WRONG_REGISTER.items():
        for pattern, instead in entries:
            yield pytest.param(
                locale, pattern, instead, id=f'{locale}-{pattern}'
            )


class TestTheAuditedCataloguesKeepTheirRegister:
    """Acceptance criterion: the register #351 recorded for each catalogue
    is the register it still uses."""

    @pytest.mark.parametrize(
        'locale,pattern,instead', list(_wrong_register_cases())
    )
    def test_no_string_uses_the_other_register(self, locale, pattern,
                                               instead):
        compiled = re.compile(pattern)
        offenders = [
            f'{msgid!r} -> {msgstr!r}'
            for msgid, msgstr in _messages(locale)
            if compiled.search(msgstr)
        ]
        settled = SETTLED_REGISTER[locale][0]
        assert offenders == [], (
            f"{locale} strings addressing the reader in the wrong register "
            f"({pattern}); the catalogue is {settled} throughout, so use "
            f"{instead!r} instead (#351):\n" + '\n'.join(offenders)
        )

    @pytest.mark.parametrize('locale', AUDITED)
    def test_the_settled_register_is_still_used_throughout(self, locale):
        # The mirror of the check above: a fill that translated everything
        # afresh in the other register would leave no wrong-register marker
        # to catch, because it would have replaced the right ones too.
        register, pattern, floor = SETTLED_REGISTER[locale]
        compiled = re.compile(pattern)
        carrying = [
            msgid for msgid, msgstr in _messages(locale)
            if compiled.search(msgstr)
        ]
        assert len(carrying) >= floor, (
            f"only {len(carrying)} {locale} strings still address the "
            f"reader as {register}, expected at least {floor}; the "
            f"catalogue looks to have been rewritten in the other "
            f"register (#351)"
        )


class TestTheAuditedCataloguesAreComplete:
    """Acceptance criterion, and the condition under which the register
    checks above mean anything: a catalogue that has gone blank or fuzzy
    ships English regardless of what register it was written in."""

    @pytest.mark.parametrize('locale', AUDITED)
    def test_msgids_still_match_the_template(self, locale):
        with open(os.path.join(TRANSLATIONS_DIR, 'messages.pot'),
                  encoding='utf-8') as handle:
            template = read_po(handle)
        expected = {message.id for message in template if message.id}
        actual = {message.id for message in _catalogue(locale) if message.id}
        assert actual == expected, (
            f"{locale} missing: {sorted(expected - actual)}, "
            f"unexpected: {sorted(actual - expected)}"
        )

    @pytest.mark.parametrize('locale', AUDITED)
    def test_no_entry_was_left_untranslated(self, locale):
        blank = [
            message.id for message in _catalogue(locale)
            if message.id and not message.string
        ]
        assert blank == [], f"untranslated {locale} entries: {blank}"

    @pytest.mark.parametrize('locale', AUDITED)
    def test_no_entry_was_left_fuzzy(self, locale):
        # pybabel compile skips fuzzy entries, so a fuzzy flag ships as
        # English.
        fuzzy = [
            message.id for message in _catalogue(locale)
            if message.id and message.fuzzy
        ]
        assert fuzzy == [], f"fuzzy {locale} entries: {fuzzy}"
