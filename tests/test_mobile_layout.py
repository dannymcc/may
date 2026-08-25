"""Checks that guard against horizontal overflow on narrow (mobile) screens.

Issue #314: several pages ran off the right-hand side on a phone. There is no
browser in the test environment, so instead of measuring pixels we assert the
two structural invariants that caused it:

1. Every ``<table>`` sits inside an element that can scroll horizontally.
   Data tables are far wider than a phone, so without a scroll wrapper they
   either push the page sideways or get clipped by the card around them.

2. Every flex row holding two or more buttons is allowed to wrap. A row of
   action buttons cannot shrink below its content, so a row that cannot wrap
   drags the page wider than the viewport.

Elements hidden at phone width (``hidden`` with a breakpoint prefix to reveal
them, such as the desktop nav bar) are ignored — they are not on screen.
"""

import re
from datetime import date
from html.parser import HTMLParser

import pytest

from app import db
from app.models import (
    ChargingSession,
    Document,
    Expense,
    FuelLog,
    MaintenanceSchedule,
    Note,
    Reminder,
    TireFitment,
    TireSet,
    Trip,
)


# Tailwind classes that let a box scroll sideways rather than overflow the page.
SCROLLABLE = {'overflow-x-auto', 'overflow-x-scroll', 'overflow-auto', 'overflow-scroll'}

# A button-shaped link or button: inline-flex with horizontal padding.
BUTTON_PADDING = re.compile(r'\bpx-\d')


def _classes(attrs):
    for name, value in attrs:
        if name == 'class':
            return set((value or '').split())
    return set()


def _is_flex_row(classes):
    """True for an element laying its children out in a horizontal flex row."""
    if 'flex' not in classes or 'hidden' in classes:
        return False
    return 'flex-col' not in classes


def _is_button_like(tag, classes):
    if tag not in ('a', 'button'):
        return False
    if 'inline-flex' not in classes:
        return False
    return bool(BUTTON_PADDING.search(' '.join(classes)))


class LayoutScanner(HTMLParser):
    """Collects tables without a scroll wrapper and button rows that cannot wrap."""

    VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'path', 'area', 'col'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []
        self.unscrollable_tables = []
        self._flex_rows = {}

    def handle_starttag(self, tag, attrs):
        classes = _classes(attrs)

        # `hidden` with a breakpoint prefix to reveal it (e.g. the desktop nav
        # bar) means the element is not on screen at phone width at all.
        hidden = 'hidden' in classes or any('hidden' in c for _, c, _ in self._stack)

        if tag == 'table' and not hidden and not any(
            c & SCROLLABLE for _, c, _ in self._stack
        ):
            self.unscrollable_tables.append(self.getpos()[0])

        if not hidden and _is_button_like(tag, classes):
            for entry in reversed(self._stack):
                if _is_flex_row(entry[1]):
                    entry[2].append(tag)
                    break

        if tag not in self.VOID:
            entry = [tag, classes, []]
            self._stack.append(entry)
            if _is_flex_row(classes):
                self._flex_rows[id(entry)] = entry

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                return

    @property
    def rigid_button_rows(self):
        """Flex rows holding 2+ buttons that neither wrap nor scroll."""
        rows = []
        for _tag, classes, buttons in self._flex_rows.values():
            if len(buttons) < 2:
                continue
            if 'flex-wrap' in classes or classes & SCROLLABLE:
                continue
            rows.append(' '.join(sorted(classes)))
        return rows


def scan(html):
    scanner = LayoutScanner()
    scanner.feed(html)
    return scanner


@pytest.fixture
def populated(app, test_user, sample_vehicle, sample_fuel_log, sample_expense,
              sample_trip, sample_charging_session):
    """A user with at least one row on every list page worth checking."""
    db.session.add_all([
        FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                date=date(2024, 2, 15), odometer=10500.0, volume=42.0,
                price_per_unit=1.55, total_cost=65.1, is_full_tank=True),
        Expense(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                date=date(2024, 2, 20), category='service',
                description='Annual service', vendor='A Very Long Garage Name Ltd',
                cost=350.0),
        ChargingSession(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                        date=date(2024, 2, 25), odometer=10600.0, kwh_added=35.0,
                        cost_per_kwh=0.28, total_cost=9.8, charger_type='public'),
        Trip(vehicle_id=sample_vehicle.id, user_id=test_user.id,
             date=date(2024, 2, 26), start_odometer=10600.0, end_odometer=10700.0,
             purpose='business', description='Site visit'),
        Note(vehicle_id=sample_vehicle.id, user_id=test_user.id,
             date=date(2024, 2, 27), title='Winter check',
             content='Check the tyre pressures.'),
        Reminder(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                 title='MOT', reminder_type='mot', due_date=date(2024, 6, 1),
                 recurrence='none'),
        MaintenanceSchedule(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                            name='Oil change', maintenance_type='oil_change',
                            interval_months=6, estimated_cost=50.0),
        Document(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                 title='Insurance certificate', document_type='insurance',
                 filename='cert.pdf', original_filename='cert.pdf',
                 file_type='pdf', file_size=20),
    ])

    tire_set = TireSet(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       name='Winter set', tire_type='winter', size='205/55 R16')
    db.session.add(tire_set)
    db.session.commit()

    db.session.add(TireFitment(tire_set_id=tire_set.id,
                               fitted_date=date(2024, 1, 1), fitted_odometer=10000.0,
                               removed_date=date(2024, 3, 1), removed_odometer=10800.0))
    db.session.commit()

    return sample_vehicle


def _pages(vehicle):
    document = Document.query.filter_by(vehicle_id=vehicle.id).first()
    return [
        '/dashboard',
        '/vehicles/',
        f'/vehicles/{vehicle.id}',
        f'/documents/{document.id}',
        '/fuel/',
        '/expenses/',
        '/trips/',
        '/trips/report',
        '/charging/',
        '/maintenance/',
        '/reminders/',
        '/documents/',
        '/notes/',
        '/tires/',
        '/allowance/',
        '/stations/',
        '/recurring/',
        f'/timeline/{vehicle.id}',
        '/auth/settings',
        '/api/docs',
    ]


def test_every_table_can_scroll_sideways(auth_client, populated):
    """A table wider than the phone must scroll, not overflow or get clipped."""
    offenders = {}
    for path in _pages(populated):
        response = auth_client.get(path)
        assert response.status_code == 200, path
        lines = scan(response.get_data(as_text=True)).unscrollable_tables
        if lines:
            offenders[path] = lines
    assert not offenders, f'tables with no horizontal scroll wrapper: {offenders}'


def test_button_rows_can_wrap(auth_client, populated):
    """A row of action buttons must wrap rather than widen the page."""
    offenders = {}
    for path in _pages(populated):
        response = auth_client.get(path)
        assert response.status_code == 200, path
        rows = scan(response.get_data(as_text=True)).rigid_button_rows
        if rows:
            offenders[path] = rows
    assert not offenders, f'button rows that cannot wrap: {offenders}'


def test_admin_user_table_can_scroll_sideways(admin_client):
    response = admin_client.get('/auth/users')
    assert response.status_code == 200
    assert not scan(response.get_data(as_text=True)).unscrollable_tables


def test_scanner_spots_a_bare_table():
    """The scanner itself: a table with no scrollable ancestor is reported."""
    assert scan('<div class="p-6"><table><tr><td>x</td></tr></table></div>').unscrollable_tables
    assert not scan(
        '<div class="overflow-x-auto"><table><tr><td>x</td></tr></table></div>'
    ).unscrollable_tables
    assert not scan(
        '<div class="hidden sm:block"><table><tr><td>x</td></tr></table></div>'
    ).unscrollable_tables


def test_scanner_spots_a_rigid_button_row():
    """The scanner itself: two buttons in a row that cannot wrap is reported."""
    row = (
        '<div class="{cls}">'
        '<a class="inline-flex items-center px-4 py-2">One</a>'
        '<a class="inline-flex items-center px-4 py-2">Two</a>'
        '</div>'
    )
    assert scan(row.format(cls='flex gap-2')).rigid_button_rows
    assert not scan(row.format(cls='flex flex-wrap gap-2')).rigid_button_rows
    assert not scan(row.format(cls='flex flex-col gap-2')).rigid_button_rows
    assert not scan(row.format(cls='flex gap-2 overflow-x-auto')).rigid_button_rows
