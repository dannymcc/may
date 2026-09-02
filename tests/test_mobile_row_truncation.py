"""Mobile list rows must not crush the name column to a single letter (#347).

Both the Recurring Expenses list (`recurring/index.html`) and the Upcoming
Reminders row (`reminders/_reminder_row.html`) lay each entry out as a flex row:
a name/title block on the left and a cluster of metadata plus action buttons on
the right. The right cluster had no `flex-shrink-0`, so on a narrow (mobile)
viewport flexbox shrank *both* sides to fit, and the `truncate` on the name then
collapsed it to the first letter ("R..." for "Roadside Assistance").

The fix pins the right cluster with `flex-shrink-0` and gives the name column a
`min-w-0` ancestor so it truncates gracefully with room, rather than vanishing.
These tests assert that structure survives, and that the full name is still in
the DOM (truncation is visual only, so nothing is actually lost).
"""

from datetime import date

from app import db
from app.models import RecurringExpense, Reminder


LONG_NAME = 'Roadside Assistance And Breakdown Cover Premium Plan'


class TestRecurringRowLayout:
    def _make(self, test_user, sample_vehicle):
        rec = RecurringExpense(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            name=LONG_NAME, category='insurance', frequency='monthly',
            amount=12.50, start_date=date(2024, 1, 1), next_due=date(2024, 2, 1),
            is_active=True,
        )
        db.session.add(rec)
        db.session.commit()
        return rec

    def test_recurring_row_protects_the_name_column(self, auth_client, test_user, sample_vehicle):
        self._make(test_user, sample_vehicle)
        resp = auth_client.get('/recurring/')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # The full name survives in the DOM — truncation is CSS-only.
        assert LONG_NAME in body
        # The action/metadata cluster must not shrink and steal the name's width.
        assert 'flex flex-shrink-0 items-center gap-4' in body
        # The name still truncates gracefully when there genuinely isn't room.
        assert 'truncate' in body


class TestReminderRowLayout:
    def _make(self, test_user, sample_vehicle):
        rem = Reminder(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            title=LONG_NAME, reminder_type='insurance',
            due_date=date(2024, 6, 1), recurrence='none',
        )
        db.session.add(rem)
        db.session.commit()
        return rem

    def test_reminder_row_protects_the_title_column(self, auth_client, test_user, sample_vehicle):
        self._make(test_user, sample_vehicle)
        resp = auth_client.get('/reminders/')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert LONG_NAME in body
        # Right cluster (due date + actions) pinned so it can't crush the title.
        assert 'flex flex-shrink-0 items-center space-x-4' in body
        # Left block carries min-w-0 so the truncate on the title actually engages.
        assert 'flex items-center space-x-4 min-w-0' in body
        assert 'truncate' in body
