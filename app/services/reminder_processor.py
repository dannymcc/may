"""Background reminder processor that checks and sends due notifications."""
import logging
from datetime import date, timedelta
from app import db
from app.models import MaintenanceSchedule, Reminder, User
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)


def create_maintenance_reminders(today=None):
    """Create reminders for maintenance schedules that have entered their window.

    Covers schedules with "Automatically create reminder when due" ticked,
    which was stored but never acted on before 0.46.2. Each service cycle
    (identified by the schedule's next-due point) gets at most one reminder,
    and none is created while an open reminder with the same name already
    exists for the vehicle, such as one the user made by hand or restored
    from a backup.

    Returns:
        dict with counts of created/skipped reminders and any errors
    """
    today = today or date.today()
    stats = {'created': 0, 'skipped': 0, 'errors': []}
    schedules = MaintenanceSchedule.query.filter_by(is_active=True, auto_remind=True).all()

    for schedule in schedules:
        try:
            vehicle = schedule.vehicle
            if vehicle is None or vehicle.is_active is False:  # archived
                stats['skipped'] += 1
                continue
            due = schedule.reminder_due_date(vehicle.get_last_odometer(), today)
            if due is None:
                stats['skipped'] += 1
                continue
            key = schedule.due_key
            already = Reminder.query.filter_by(
                maintenance_schedule_id=schedule.id, maintenance_due_key=key).first()
            open_same_name = Reminder.query.filter_by(
                vehicle_id=vehicle.id, title=schedule.name[:100], is_completed=False).first()
            if already or open_same_name:
                stats['skipped'] += 1
                continue

            description = None
            if schedule.next_due_odometer:
                description = (f"Due at {schedule.next_due_odometer:,.0f} "
                               f"{vehicle.get_reading_unit()}")
            db.session.add(Reminder(
                vehicle_id=vehicle.id,
                user_id=schedule.user_id,
                title=schedule.name[:100],
                description=description,
                reminder_type='oil_change' if schedule.maintenance_type == 'oil_change' else 'service',
                due_date=due,
                # The schedule's own lead time has already passed, so notify
                # on the next run rather than waiting a further lead period.
                notify_days_before=max((due - today).days, 1),
                maintenance_schedule_id=schedule.id,
                maintenance_due_key=key,
            ))
            db.session.commit()
            stats['created'] += 1
        except Exception as e:  # one bad schedule must not stop the rest
            db.session.rollback()
            stats['errors'].append(f"Schedule #{schedule.id}: {e}")
            logger.error(f"Error creating reminder for schedule #{schedule.id}: {e}")

    return stats


def process_due_reminders():
    """Check all reminders and send notifications for those that are due.

    This should be called periodically (e.g., daily via cron or background thread).
    It checks each user's reminders against their notification preferences.

    Returns:
        dict with counts of processed/sent/failed notifications
    """
    stats = {'checked': 0, 'sent': 0, 'failed': 0, 'skipped': 0, 'errors': []}

    # Get all active (not completed) reminders
    reminders = Reminder.query.filter_by(
        is_completed=False,
        notification_sent=False
    ).all()

    today = date.today()

    for reminder in reminders:
        stats['checked'] += 1

        # Get the user who owns this reminder
        user = db.session.get(User, reminder.user_id)
        if not user:
            stats['skipped'] += 1
            continue

        # Check if user has notifications enabled
        if not user.email_reminders:
            stats['skipped'] += 1
            continue

        # Check if the notification method is 'none'
        if user.notification_method == 'none':
            stats['skipped'] += 1
            continue

        # Calculate notification date based on user's or reminder's lead time
        notify_days = reminder.notify_days_before or user.reminder_days_before or 7
        notification_date = reminder.due_date - timedelta(days=notify_days)

        # Should we send the notification?
        if today < notification_date:
            stats['skipped'] += 1
            continue

        # Build notification message
        vehicle_name = reminder.vehicle.name if reminder.vehicle else 'Unknown Vehicle'
        days_until = (reminder.due_date - today).days

        if days_until < 0:
            time_msg = f"{abs(days_until)} days overdue"
        elif days_until == 0:
            time_msg = "due today"
        elif days_until == 1:
            time_msg = "due tomorrow"
        else:
            time_msg = f"due in {days_until} days"

        title = f"Reminder: {reminder.title} ({time_msg})"
        message = (
            f"Vehicle: {vehicle_name}\n"
            f"Reminder: {reminder.title}\n"
            f"Due: {reminder.due_date.strftime('%B %d, %Y')} ({time_msg})\n"
        )
        if reminder.description:
            message += f"Details: {reminder.description}\n"

        # Send notification
        try:
            success, error = NotificationService.send_notification(
                user, title, message, reminder=reminder
            )

            if success:
                reminder.notification_sent = True
                db.session.commit()
                stats['sent'] += 1
                logger.info(f"Sent notification for reminder #{reminder.id} to {user.username}")
            else:
                stats['failed'] += 1
                stats['errors'].append(f"Reminder #{reminder.id}: {error}")
                logger.warning(f"Failed to send notification for reminder #{reminder.id}: {error}")
        except Exception as e:
            stats['failed'] += 1
            stats['errors'].append(f"Reminder #{reminder.id}: {str(e)}")
            logger.error(f"Error processing reminder #{reminder.id}: {e}")

    return stats
