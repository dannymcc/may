"""Background processor that auto-generates expenses from due recurring expenses."""
import logging
from datetime import date
from app import db
from app.models import RecurringExpense, Expense

logger = logging.getLogger(__name__)

# Defensive cap on how many periods a single recurring expense may catch up in
# one run. Protects against a very old (or non-advancing) next_due date spinning
# out a huge number of entries.
MAX_CATCHUP_PERIODS = 60


def generate_expense_for_period(recurring, on_date=None):
    """Create one Expense from a recurring expense and advance its schedule.

    Maps the recurring expense's fields onto a new Expense dated at the period
    being generated, stamps ``last_generated`` and advances ``next_due`` using
    the model's own recurrence logic (:meth:`RecurringExpense.calculate_next_due`).

    The caller is responsible for committing the session.

    Args:
        recurring: the RecurringExpense to generate from.
        on_date: the date to stamp the expense with. Defaults to the recurring
            expense's ``next_due`` (or today, if it has never been scheduled).

    Returns:
        The created (uncommitted) Expense.
    """
    period_date = on_date or recurring.next_due or date.today()

    expense = Expense(
        vehicle_id=recurring.vehicle_id,
        user_id=recurring.user_id,
        date=period_date,
        category=recurring.category,
        description=f"{recurring.name} (auto-generated)",
        cost=recurring.amount or 0,
        vendor=recurring.vendor,
        notes=recurring.description,
    )
    db.session.add(expense)

    # Advance the schedule from the period we just generated so the same period
    # is never generated twice (idempotency) and catch-up loops make progress.
    recurring.last_generated = period_date
    recurring.calculate_next_due()

    return expense


def process_due_recurring_expenses():
    """Generate expenses for every due, active, auto-create recurring expense.

    For each active :class:`RecurringExpense` with ``auto_create`` enabled and
    a ``next_due`` on or before today, one Expense is generated per elapsed
    period up to today (catch-up), capped at ``MAX_CATCHUP_PERIODS`` per run.

    Idempotent: generating advances ``next_due`` beyond today, so a second run
    in the same period generates nothing. Each recurring expense is processed in
    isolation so that an error on one does not abort the others.

    Returns:
        dict with counts of checked/generated/skipped and any errors.
    """
    stats = {'checked': 0, 'generated': 0, 'skipped': 0, 'errors': []}
    today = date.today()

    recurring_expenses = RecurringExpense.query.filter(
        RecurringExpense.is_active.is_(True),
        RecurringExpense.auto_create.is_(True),
        RecurringExpense.next_due.isnot(None),
        RecurringExpense.next_due <= today,
    ).all()

    for recurring in recurring_expenses:
        stats['checked'] += 1
        try:
            count = 0
            while (recurring.is_active
                   and recurring.next_due
                   and recurring.next_due <= today
                   and count < MAX_CATCHUP_PERIODS):
                previous_due = recurring.next_due
                generate_expense_for_period(recurring, on_date=previous_due)
                count += 1

                # Guard against a frequency that fails to advance next_due
                # (e.g. legacy/unknown value), which would otherwise spin until
                # the cap generating duplicate entries for the same date.
                if recurring.next_due == previous_due:
                    logger.warning(
                        "Recurring expense #%s (%s) did not advance next_due "
                        "(frequency=%s); stopping to avoid duplicates.",
                        recurring.id, recurring.name, recurring.frequency,
                    )
                    break

            if count:
                db.session.commit()
                stats['generated'] += count
                logger.info(
                    "Generated %s expense(s) for recurring #%s (%s)",
                    count, recurring.id, recurring.name,
                )
            else:
                stats['skipped'] += 1
        except Exception as e:  # noqa: BLE001 - isolate per-item failures
            db.session.rollback()
            stats['errors'].append(f"Recurring #{recurring.id}: {e}")
            logger.error(
                "Error processing recurring expense #%s: %s", recurring.id, e
            )

    return stats
