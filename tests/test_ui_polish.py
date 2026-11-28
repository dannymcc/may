"""Navigation, accessibility and layout refinements to the shared page shell."""
import re

import pytest


@pytest.mark.parametrize('path', ['/tires/', '/charging/', '/notes/', '/allowance/',
                                  '/maintenance/', '/recurring/', '/documents/', '/stations/'])
def test_more_menu_is_highlighted_for_every_page_it_holds(auth_client, path):
    body = auth_client.get(path).get_data(as_text=True)
    button = re.search(r'<button[^>]*id="more-menu-button"[^>]*>', body, re.S).group(0)
    assert 'border-primary-600' in button


def test_more_menu_is_not_highlighted_on_top_level_pages(auth_client):
    body = auth_client.get('/fuel/').get_data(as_text=True)
    button = re.search(r'<button[^>]*id="more-menu-button"[^>]*>', body, re.S).group(0)
    assert 'border-primary-600' not in button


def test_menu_buttons_are_announced_to_screen_readers(auth_client):
    body = auth_client.get('/dashboard').get_data(as_text=True)
    mobile = re.search(r'<button[^>]*id="mobile-menu-button"[^>]*>', body, re.S).group(0)
    assert 'aria-label="Menu"' in mobile
    assert 'aria-expanded="false"' in mobile and 'aria-controls="mobile-menu"' in mobile
    more = re.search(r'<button[^>]*id="more-menu-button"[^>]*>', body, re.S).group(0)
    assert 'aria-haspopup="true"' in more and 'aria-expanded="false"' in more
    for label in ('Search', 'Settings', 'Logout'):
        assert f'title="{label}" aria-label="{label}"' in body


def test_menu_label_is_translated(client, test_user):
    from app import db
    test_user.language = 'de'
    db.session.commit()
    client.post('/auth/login', data={'username': 'testuser', 'password': 'TestPass123!'})
    assert 'aria-label="Menü"' in client.get('/dashboard').get_data(as_text=True)


def test_shell_styles_cover_figures_focus_contrast_and_motion(auth_client):
    body = auth_client.get('/dashboard').get_data(as_text=True)
    assert 'font-variant-numeric: tabular-nums' in body
    assert ':focus-visible { outline: 2px solid var(--primary-500)' in body
    assert 'html.dark :where(.text-primary-600) { color: var(--primary-400); }' in body
    assert '@media (prefers-reduced-motion: reduce)' in body
    assert 'Chart.defaults.animation = false' in body


def test_dashboard_stat_cards_pair_up_on_phones(auth_client):
    body = auth_client.get('/dashboard').get_data(as_text=True)
    assert '<div class="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4 mb-8">' in body
    stats = body.split('<!-- Stats Cards -->')[1].split('lg:grid-cols-3 gap-8')[0]
    # Labels wrap on narrow cards instead of being cut off, and the icons,
    # which repeat the label, step aside on phones.
    assert ' truncate"' not in stats
    assert 'class="hidden sm:block flex-shrink-0" aria-hidden="true"' in stats
