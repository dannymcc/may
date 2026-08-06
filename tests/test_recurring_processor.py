"""Tests for the recurring-expense auto-generation processor (issue #257)."""
import pytest
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from app import db
from app.models import RecurringExpense, Expense
from app.services.recurring_processor import (
    process_due_recurring_expenses,
    generate_expense_for_period,
    MAX_CATCHUP_PERIODS,
)


def _make_recurring(test_user, sample_vehicle, **overrides):
    defaults = dict(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        name='Monthly Insurance',
        category='insurance',
        frequency='monthly',
        amount=100.0,
        start_date=date.today() - relativedelta(months=1),
        next_due=date.today(),
        auto_create=True,
        is_active=True,
    )
    defaults.update(overrides)
    recurring = RecurringExpense(**defaults)
    db.session.add(recurring)
    db.session.commit()
    return recurring


def _expense_count(recurring):
    return Expense.query.filter_by(
        vehicle_id=recurring.vehicle_id,
        category=recurring.category,
    ).count()


class TestProcessDueRecurring:
    def test_due_auto_create_generates_one_expense(self, app, test_user, sample_vehicle):
        recurring = _make_recurring(test_user, sample_vehicle, next_due=date.today())

        stats = process_due_recurring_expenses()

        assert stats['generated'] == 1
        assert _expense_count(recurring) == 1
        expense = Expense.query.filter_by(vehicle_id=recurring.vehicle_id).first()
        assert expense.cost == 100.0
        assert expense.date == date.today()
        assert 'Monthly Insurance' in expense.description

    def test_advances_next_due(self, app, test_user, sample_vehicle):
        today = date.today()
        recurring = _make_recurring(test_user, sample_vehicle, next_due=today)

        process_due_recurring_expenses()

        db.session.refresh(recurring)
        assert recurring.last_generated == today
        assert recurring.next_due == today + relativedelta(months=1)

    def test_not_due_generates_nothing(self, app, test_user, sample_vehicle):
        recurring = _make_recurring(
            test_user, sample_vehicle, next_due=date.today() + timedelta(days=5)
        )

        stats = process_due_recurring_expenses()

        assert stats['generated'] == 0
        assert _expense_count(recurring) == 0

    def test_auto_create_false_generates_nothing(self, app, test_user, sample_vehicle):
        recurring = _make_recurring(
            test_user, sample_vehicle, next_due=date.today(), auto_create=False
        )

        stats = process_due_recurring_expenses()

        assert stats['generated'] == 0
        assert _expense_count(recurring) == 0

    def test_inactive_generates_nothing(self, app, test_user, sample_vehicle):
        recurring = _make_recurring(
            test_user, sample_vehicle, next_due=date.today(), is_active=False
        )

        stats = process_due_recurring_expenses()

        assert stats['generated'] == 0
        assert _expense_count(recurring) == 0

    def test_no_next_due_generates_nothing(self, app, test_user, sample_vehicle):
        recurring = _make_recurring(test_user, sample_vehicle, next_due=None)

        stats = process_due_recurring_expenses()

        assert stats['generated'] == 0
        assert _expense_count(recurring) == 0

    def test_idempotent_second_run_generates_nothing(self, app, test_user, sample_vehicle):
        recurring = _make_recurring(test_user, sample_vehicle, next_due=date.today())

        first = process_due_recurring_expenses()
        second = process_due_recurring_expenses()

        assert first['generated'] == 1
        assert second['generated'] == 0
        assert _expense_count(recurring) == 1

    def test_multi_period_catch_up(self, app, test_user, sample_vehicle):
        # next_due 3 months in the past -> expect one entry per elapsed month
        # up to and including today (4 entries: -3, -2, -1, 0 months).
        three_months_ago = date.today() - relativedelta(months=3)
        recurring = _make_recurring(
            test_user, sample_vehicle,
            start_date=three_months_ago,
            next_due=three_months_ago,
        )

        stats = process_due_recurring_expenses()

        assert stats['generated'] == 4
        assert _expense_count(recurring) == 4
        db.session.refresh(recurring)
        assert recurring.next_due > date.today()

    def test_catch_up_capped(self, app, test_user, sample_vehicle):
        # Weekly recurrence far in the past would exceed the cap.
        long_ago = date.today() - relativedelta(years=5)
        recurring = _make_recurring(
            test_user, sample_vehicle,
            frequency='weekly',
            start_date=long_ago,
            next_due=long_ago,
        )

        stats = process_due_recurring_expenses()

        assert stats['generated'] == MAX_CATCHUP_PERIODS
        assert _expense_count(recurring) == MAX_CATCHUP_PERIODS

    def test_end_date_deactivates_and_stops(self, app, test_user, sample_vehicle):
        # end_date one month past next_due: generate once, then deactivate.
        start = date.today() - relativedelta(months=2)
        recurring = _make_recurring(
            test_user, sample_vehicle,
            start_date=start,
            next_due=start,
            end_date=start + relativedelta(days=10),
        )

        stats = process_due_recurring_expenses()

        db.session.refresh(recurring)
        assert stats['generated'] == 1
        assert recurring.is_active is False

    def test_biannual_advances_six_months(self, app, test_user, sample_vehicle):
        today = date.today()
        recurring = _make_recurring(
            test_user, sample_vehicle, frequency='biannual', next_due=today,
        )

        process_due_recurring_expenses()

        db.session.refresh(recurring)
        assert recurring.next_due == today + relativedelta(months=6)

    def test_error_isolation(self, app, test_user, sample_vehicle):
        # A recurring expense with a broken frequency must not stop others.
        good = _make_recurring(test_user, sample_vehicle, next_due=date.today())
        # Bad one: unknown frequency never advances next_due; the guard should
        # stop it after a single generation rather than loop forever.
        bad = _make_recurring(
            test_user, sample_vehicle,
            name='Broken', frequency='not-a-real-frequency',
            next_due=date.today(),
        )

        stats = process_due_recurring_expenses()

        # good generates one; bad generates exactly one then bails on the guard.
        assert stats['generated'] == 2
        db.session.refresh(bad)
        # next_due unchanged, but it will only ever emit one per run.
        assert bad.next_due == date.today()


class TestGenerateExpenseForPeriodHelper:
    def test_maps_vendor_and_notes(self, app, test_user, sample_vehicle):
        recurring = _make_recurring(
            test_user, sample_vehicle,
            vendor='Acme Insurers', description='Policy AB123',
            next_due=date.today(),
        )

        generate_expense_for_period(recurring)
        db.session.commit()

        expense = Expense.query.filter_by(vehicle_id=recurring.vehicle_id).first()
        assert expense.vendor == 'Acme Insurers'
        assert expense.notes == 'Policy AB123'
