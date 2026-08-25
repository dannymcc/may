"""Background reminder processor that checks and sends due notifications."""
import logging
from datetime import date, timedelta
from app import db
from app.models import Reminder, User
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)


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
