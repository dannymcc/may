"""Background reminder processor that checks and sends due notifications."""
import logging
from datetime import date, datetime, timedelta
from app import db
from app.models import CalendarAlarm, CalendarEvent, Reminder, User
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
        user = User.query.get(reminder.user_id)
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

        # Build notification message — a reminder is about a vehicle or a person
        if reminder.person:
            subject_label = 'Person'
            subject_name = reminder.person.display_name
        elif reminder.vehicle:
            subject_label = 'Vehicle'
            subject_name = reminder.vehicle.name
        else:
            subject_label = 'Vehicle'
            subject_name = 'Unknown Vehicle'

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
            f"{subject_label}: {subject_name}\n"
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


def process_due_calendar_alarms():
    """Send due notifications for portable calendar event alarms."""
    stats = {'checked': 0, 'sent': 0, 'failed': 0, 'skipped': 0, 'errors': []}
    now = datetime.utcnow()

    alarms = (
        CalendarAlarm.query
        .join(CalendarEvent)
        .filter(
            CalendarAlarm.is_enabled == True,
            CalendarAlarm.notification_sent == False,
            CalendarAlarm.action.in_(('email', 'smtp', 'webhook')),
        )
        .all()
    )

    for alarm in alarms:
        stats['checked'] += 1
        event = alarm.event
        user = event.user if event else None
        if not event or not user:
            stats['skipped'] += 1
            continue

        trigger_at = alarm.trigger_at()
        if not trigger_at or now < trigger_at:
            stats['skipped'] += 1
            continue

        title = alarm.summary or f"Calendar event: {event.title}"
        message = alarm.description or (
            f"Event: {event.title}\n"
            f"Starts: {event.start_at.isoformat() if event.start_at else 'unknown'}\n"
        )
        if event.person:
            message += f"Person: {event.person.display_name}\n"
        if event.location:
            message += f"Location: {event.location}\n"

        try:
            if alarm.action in ('email', 'smtp'):
                if not user.email_reminders:
                    stats['skipped'] += 1
                    continue
                to_email = alarm.attendee_email or user.email
                success, error = NotificationService.send_email(to_email, title, message)
            elif alarm.action == 'webhook':
                payload = {
                    'title': title,
                    'message': message,
                    'event': event.to_dict(include_alarms=False),
                    'alarm': alarm.to_dict(),
                }
                success, error = NotificationService.send_webhook(user.webhook_url, payload)
            else:
                stats['skipped'] += 1
                continue

            if success:
                alarm.notification_sent = True
                alarm.sent_at = now
                db.session.commit()
                stats['sent'] += 1
                logger.info(f"Sent calendar alarm #{alarm.id} to {user.username}")
            else:
                stats['failed'] += 1
                stats['errors'].append(f"Calendar alarm #{alarm.id}: {error}")
                logger.warning(f"Failed to send calendar alarm #{alarm.id}: {error}")
        except Exception as e:
            stats['failed'] += 1
            stats['errors'].append(f"Calendar alarm #{alarm.id}: {str(e)}")
            logger.error(f"Error processing calendar alarm #{alarm.id}: {e}")

    return stats
