"""Notification service for sending reminders via various methods."""
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from app.models import AppSettings


class NotificationService:
    """Service for sending notifications through various channels."""

    @staticmethod
    def get_smtp_config():
        """Get SMTP configuration from app settings."""
        return {
            'host': AppSettings.get('smtp_host'),
            'port': int(AppSettings.get('smtp_port', '587')),
            'username': AppSettings.get('smtp_username'),
            'password': AppSettings.get('smtp_password'),
            'sender': AppSettings.get('smtp_sender'),
            'sender_name': AppSettings.get('smtp_sender_name', 'May'),
            'use_tls': AppSettings.get('smtp_tls', 'true') == 'true',
            'use_ssl': AppSettings.get('smtp_ssl', 'false') == 'true',
        }

    @staticmethod
    def send_email(to_email, subject, body, html_body=None):
        """Send an email using configured SMTP settings."""
        config = NotificationService.get_smtp_config()

        if not config['host'] or not config['username']:
            return False, "SMTP not configured"

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{config['sender_name']} <{config['sender']}>"
            msg['To'] = to_email

            # Attach plain text
            msg.attach(MIMEText(body, 'plain'))

            # Attach HTML if provided
            if html_body:
                msg.attach(MIMEText(html_body, 'html'))

            # Connect to SMTP server
            if config['use_ssl']:
                server = smtplib.SMTP_SSL(config['host'], config['port'])
            else:
                server = smtplib.SMTP(config['host'], config['port'])
                if config['use_tls']:
                    server.starttls()

            server.login(config['username'], config['password'])
            server.sendmail(config['sender'], to_email, msg.as_string())
            server.quit()

            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def send_webhook(webhook_url, payload):
        """Send a notification via webhook (HTTP POST with JSON)."""
        if not webhook_url:
            return False, "Webhook URL not configured"

        try:
            data = json.dumps(payload).encode('utf-8')
            req = Request(webhook_url, data=data, headers={
                'Content-Type': 'application/json',
                'User-Agent': 'May-Vehicle-Manager/1.0'
            })
            with urlopen(req, timeout=10) as response:
                return True, None
        except HTTPError as e:
            return False, f"HTTP {e.code}: {e.reason}"
        except URLError as e:
            return False, f"URL Error: {e.reason}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def send_ntfy(topic, title, message, priority='default'):
        """Send a notification via ntfy.sh or self-hosted ntfy server."""
        if not topic:
            return False, "ntfy topic not configured"

        try:
            # Determine URL - if it looks like a URL, use it directly
            if topic.startswith('http://') or topic.startswith('https://'):
                url = topic
            else:
                url = f"https://ntfy.sh/{topic}"

            data = message.encode('utf-8')
            req = Request(url, data=data, headers={
                'Title': title,
                'Priority': priority,
                'Tags': 'car',
                'User-Agent': 'May-Vehicle-Manager/1.0',
            })
            with urlopen(req, timeout=10) as response:
                return True, None
        except HTTPError as e:
            return False, f"HTTP {e.code}: {e.reason}"
        except URLError as e:
            return False, f"URL Error: {e.reason}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def send_pushover(user_key, title, message, priority=0):
        """Send a notification via Pushover."""
        app_token = AppSettings.get('pushover_app_token')

        if not app_token:
            return False, "Pushover app token not configured by administrator"
        if not user_key:
            return False, "Pushover user key not configured"

        try:
            data = {
                'token': app_token,
                'user': user_key,
                'title': title,
                'message': message,
                'priority': priority,
            }
            encoded_data = json.dumps(data).encode('utf-8')
            req = Request(
                'https://api.pushover.net/1/messages.json',
                data=encoded_data,
                headers={'Content-Type': 'application/json'}
            )
            with urlopen(req, timeout=10) as response:
                return True, None
        except HTTPError as e:
            return False, f"HTTP {e.code}: {e.reason}"
        except URLError as e:
            return False, f"URL Error: {e.reason}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def send_notification(user, title, message, reminder=None):
        """
        Send a notification to a user using their preferred method.

        Args:
            user: User object with notification preferences
            title: Notification title
            message: Notification message body
            reminder: Optional Reminder object for additional context
        """
        method = user.notification_method or 'email'

        # Build payload for webhook
        payload = {
            'title': title,
            'message': message,
            'user_email': user.email,
            'timestamp': __import__('datetime').datetime.utcnow().isoformat(),
        }
        if reminder:
            payload.update({
                'reminder_id': reminder.id,
                'reminder_title': reminder.title,
                'vehicle_name': reminder.vehicle.name if reminder.vehicle else None,
                'due_date': reminder.due_date.isoformat() if reminder.due_date else None,
                'reminder_type': reminder.reminder_type,
            })

        if method == 'email':
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #0284c7;">{title}</h2>
                <p>{message}</p>
                {"<p><strong>Vehicle:</strong> " + reminder.vehicle.name + "</p>" if reminder and reminder.vehicle else ""}
                {"<p><strong>Due Date:</strong> " + reminder.due_date.strftime('%B %d, %Y') + "</p>" if reminder and reminder.due_date else ""}
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                <p style="color: #6b7280; font-size: 12px;">This notification was sent by May Vehicle Manager.</p>
            </body>
            </html>
            """
            return NotificationService.send_email(user.email, title, message, html_body)

        elif method == 'webhook':
            return NotificationService.send_webhook(user.webhook_url, payload)

        elif method == 'ntfy':
            return NotificationService.send_ntfy(user.ntfy_topic, title, message)

        elif method == 'pushover':
            return NotificationService.send_pushover(user.pushover_user_key, title, message)

        else:
            return False, f"Unknown notification method: {method}"

    @staticmethod
    def send_test_notification(user):
        """Send a test notification to verify user's settings."""
        return NotificationService.send_notification(
            user,
            "Test Notification from May",
            "This is a test notification to verify your notification settings are working correctly.",
        )

    @staticmethod
    def test_smtp(config):
        """Test SMTP settings with the provided configuration."""
        try:
            if config.get('use_ssl') == 'true' or config.get('use_ssl') is True:
                server = smtplib.SMTP_SSL(config['host'], int(config['port']))
            else:
                server = smtplib.SMTP(config['host'], int(config['port']))
                if config.get('use_tls') == 'true' or config.get('use_tls') is True:
                    server.starttls()

            server.login(config['username'], config['password'])
            server.quit()
            return True, "SMTP connection successful"
        except Exception as e:
            return False, str(e)
