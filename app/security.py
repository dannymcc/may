"""
Security utilities for the May application.
"""
import re
import ipaddress
from urllib.parse import urlparse, urljoin
from functools import wraps
from flask import request, redirect, url_for, flash
from flask_login import current_user

# File signature (magic bytes) mappings
FILE_SIGNATURES = {
    'image/jpeg': [b'\xff\xd8\xff'],
    'image/png': [b'\x89PNG\r\n\x1a\n'],
    'image/gif': [b'GIF87a', b'GIF89a'],
    'image/webp': [b'RIFF', b'WEBP'],  # RIFF....WEBP
    'application/pdf': [b'%PDF'],
    'image/svg+xml': [b'<?xml', b'<svg'],  # SVG files
}

ALLOWED_MIME_TYPES = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'pdf': 'application/pdf',
    'svg': 'image/svg+xml',
}


def is_safe_url(target):
    """
    Validate that a redirect URL is safe (not an open redirect vulnerability).

    A URL is considered safe if:
    - It's a relative URL (no scheme or netloc)
    - It's an absolute URL pointing to the same host

    Args:
        target: The URL to validate

    Returns:
        bool: True if the URL is safe for redirect, False otherwise
    """
    if not target:
        return False

    # Parse the target URL
    target_url = urlparse(target)

    # If there's no netloc, it's a relative URL (safe)
    if not target_url.netloc:
        # But make sure it doesn't start with // (protocol-relative URL)
        if target.startswith('//'):
            return False
        return True

    # If there is a netloc, it must match the request host
    request_url = urlparse(request.host_url)
    return target_url.netloc == request_url.netloc


def get_safe_redirect_url(target, default='main.dashboard'):
    """
    Get a safe redirect URL, falling back to default if target is unsafe.

    Args:
        target: The requested redirect URL
        default: The default route name to use if target is unsafe

    Returns:
        str: A safe URL to redirect to
    """
    if target and is_safe_url(target):
        return target
    if default:
        return url_for(default)
    return None


def validate_password_strength(password):
    """
    Validate password meets minimum security requirements.

    Requirements:
    - At least 8 characters long
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one digit

    Args:
        password: The password to validate

    Returns:
        tuple: (is_valid, error_message)
    """
    if not password:
        return False, "Password is required"

    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"

    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"

    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit"

    return True, None


def validate_webhook_url(url):
    """
    Validate a webhook URL to prevent SSRF attacks.

    Checks:
    - Must be http or https scheme
    - Cannot point to private/internal IP ranges
    - Cannot point to localhost

    Args:
        url: The webhook URL to validate

    Returns:
        tuple: (is_valid, error_message)
    """
    if not url:
        return True, None  # Empty URL is OK (disables webhook)

    try:
        parsed = urlparse(url)

        # Check scheme
        if parsed.scheme not in ('http', 'https'):
            return False, "Webhook URL must use http or https"

        # Check for localhost
        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid webhook URL"

        if hostname in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
            return False, "Webhook URL cannot point to localhost"

        # Check for private IP ranges
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "Webhook URL cannot point to private or reserved IP addresses"
        except ValueError:
            # Not an IP address, it's a hostname - that's OK
            # But check for common internal hostnames
            if hostname.endswith('.local') or hostname.endswith('.internal'):
                return False, "Webhook URL cannot point to internal hostnames"

        return True, None

    except Exception as e:
        return False, f"Invalid webhook URL: {str(e)}"


def validate_positive_number(value, field_name, max_value=None, allow_zero=True):
    """
    Validate that a value is a positive number.

    Args:
        value: The value to validate
        field_name: Name of the field for error messages
        max_value: Maximum allowed value (optional)
        allow_zero: Whether zero is allowed

    Returns:
        tuple: (validated_value, error_message)
    """
    if value is None or value == '':
        return None, None  # Empty is OK

    try:
        num = float(value)
    except (ValueError, TypeError):
        return None, f"{field_name} must be a valid number"

    if not allow_zero and num == 0:
        return None, f"{field_name} cannot be zero"

    if num < 0:
        return None, f"{field_name} cannot be negative"

    if max_value is not None and num > max_value:
        return None, f"{field_name} cannot exceed {max_value}"

    return num, None


def admin_required(f):
    """
    Decorator to require admin privileges for a route.

    Usage:
        @bp.route('/admin-only')
        @login_required
        @admin_required
        def admin_only_route():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_admin:
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def validate_file_upload(file, allowed_extensions=None):
    """
    Validate an uploaded file for security.

    Performs multiple checks:
    1. Filename has an allowed extension
    2. File content matches expected type (magic bytes)
    3. Filename is sanitized

    Args:
        file: The uploaded file object (from request.files)
        allowed_extensions: Set of allowed extensions (default: images + PDF)

    Returns:
        tuple: (is_valid, error_message, detected_type)
    """
    if allowed_extensions is None:
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}

    if not file or not file.filename:
        return False, "No file provided", None

    filename = file.filename

    # Check for path traversal attempts
    if '..' in filename or '/' in filename or '\\' in filename:
        return False, "Invalid filename", None

    # Check extension
    if '.' not in filename:
        return False, "File must have an extension", None

    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in allowed_extensions:
        return False, f"File type '.{ext}' not allowed", None

    # Get expected MIME type
    expected_mime = ALLOWED_MIME_TYPES.get(ext)
    if not expected_mime:
        return False, f"Unknown file type '.{ext}'", None

    # Read file header for magic bytes check
    file.seek(0)
    header = file.read(32)
    file.seek(0)  # Reset for later use

    if len(header) < 4:
        return False, "File is too small or empty", None

    # Check magic bytes
    signatures = FILE_SIGNATURES.get(expected_mime, [])
    content_valid = False

    for sig in signatures:
        if expected_mime == 'image/webp':
            # WEBP has RIFF at start and WEBP at offset 8
            if header[:4] == b'RIFF' and len(header) >= 12 and header[8:12] == b'WEBP':
                content_valid = True
                break
        elif header.startswith(sig):
            content_valid = True
            break

    if not content_valid:
        return False, "File content does not match its extension", None

    return True, None, expected_mime


def secure_filename_with_uuid(filename):
    """
    Generate a secure filename with UUID prefix.

    Args:
        filename: Original filename

    Returns:
        str: Secure filename with UUID prefix
    """
    import uuid
    from werkzeug.utils import secure_filename

    # Get secure base filename
    secure_name = secure_filename(filename)
    if not secure_name:
        secure_name = 'file'

    # Add UUID prefix
    return f"{uuid.uuid4().hex}_{secure_name}"
