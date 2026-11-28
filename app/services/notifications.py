"""Notification service for sending reminders via various methods."""
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from app.models import AppSettings
from app.security import validate_webhook_url
from app.utils import utcnow


#: How outgoing email is delivered. Chosen by an administrator; SMTP remains
#: the default so existing installations behave exactly as before.
EMAIL_PROVIDERS = ('smtp', 'resend')

RESEND_API_URL = 'https://api.resend.com/emails'


class NotificationService:
    """Service for sending notifications through various channels."""

    @staticmethod
    def email_provider():
        """The configured email provider: 'smtp' (default) or 'resend'."""
        provider = AppSettings.get('email_provider', 'smtp')
        return provider if provider in EMAIL_PROVIDERS else 'smtp'

    @staticmethod
    def get_resend_config():
        """Get Resend configuration from app settings."""
        return {
            'api_key': AppSettings.get('resend_api_key'),
            'sender': AppSettings.get('resend_sender'),
            'sender_name': AppSettings.get('resend_sender_name') or 'May',
        }

    @staticmethod
    def email_configured():
        """Whether email can be sent with the selected provider.

        Drives the email notification option, password reset by email and
        the "not configured" hints, whichever provider is in use.
        """
        if NotificationService.email_provider() == 'resend':
            config = NotificationService.get_resend_config()
            return bool(config['api_key'] and config['sender'])
        return bool(
            AppSettings.get('smtp_enabled', 'true') == 'true' and
            AppSettings.get('smtp_host') and
            AppSettings.get('smtp_username')
        )

    @staticmethod
    def send_resend(to_email, subject, body, html_body=None, config=None):
        """Send an email through the Resend API (https://resend.com).

        ``config`` lets the admin test unsaved settings; otherwise the saved
        configuration is used. Returns ``(success, error)`` like every other
        sender here.
        """
        config = config or NotificationService.get_resend_config()
        if not config.get('api_key') or not config.get('sender'):
            return False, "Resend not configured"

        sender_name = (config.get('sender_name') or 'May').replace('<', '').replace('>', '').strip()
        payload = {
            'from': f"{sender_name} <{config['sender']}>",
            'to': [to_email],
            'subject': subject,
            'text': body,
        }
        if html_body:
            payload['html'] = html_body

        req = Request(
            RESEND_API_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': f"Bearer {config['api_key']}",
                'Content-Type': 'application/json',
                'User-Agent': 'May-Vehicle-Manager/1.0',
            },
            method='POST',
        )
        try:
            with urlopen(req, timeout=10):
                return True, None
        except HTTPError as e:
            # Resend explains failures in a JSON body, e.g. an unverified
            # sending domain or an invalid API key; pass that on.
            detail = None
            try:
                detail = json.loads(e.read().decode('utf-8')).get('message')
            except Exception:
                pass
            return False, f"Resend HTTP {e.code}: {detail or e.reason}"
        except URLError as e:
            return False, f"URL Error: {e.reason}"
        except Exception as e:
            return False, str(e)

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
        """Send an email with the configured provider (SMTP or Resend)."""
        if NotificationService.email_provider() == 'resend':
            return NotificationService.send_resend(to_email, subject, body, html_body)

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

        is_valid, error_msg = validate_webhook_url(webhook_url)
        if not is_valid:
            return False, error_msg

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
    def send_ntfy(topic, title, message, priority='default', token=None):
        """Send a notification via ntfy.sh or self-hosted ntfy server.

        ``token`` is an optional ntfy access token for self-hosted servers
        with authentication enabled (#90), sent as a Bearer header.
        """
        if not topic:
            return False, "ntfy topic not configured"

        # Never leak the access token over an unencrypted connection.
        if token and topic.startswith('http://'):
            return False, "Refusing to send the ntfy access token over plain HTTP - use an https:// server URL"

        try:
            # Determine URL - if it looks like a URL, use it directly
            if topic.startswith('http://') or topic.startswith('https://'):
                url = topic
            else:
                url = f"https://ntfy.sh/{topic}"

            data = message.encode('utf-8')
            headers = {
                'Title': title,
                'Priority': priority,
                'Tags': 'car',
                'User-Agent': 'May-Vehicle-Manager/1.0',
            }
            if token:
                headers['Authorization'] = f'Bearer {token}'
            req = Request(url, data=data, headers=headers)
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
            'timestamp': utcnow().isoformat(),
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
            return NotificationService.send_ntfy(user.ntfy_topic, title, message, token=user.ntfy_token)

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
