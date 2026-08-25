import os
import uuid
import requests
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from flask_babel import gettext as _
from werkzeug.utils import secure_filename
from app import db
from app.models import User, AppSettings, USER_ROLES, USER_ROLE_DESCRIPTIONS, ROLE_EDITOR, ROLE_WRITE_SCOPES
from app.security import (
    get_safe_redirect_url, validate_password_strength,
    validate_webhook_url, admin_required
)
from app.services.notifications import NotificationService
from config import APP_VERSION, DISPLAY_VERSION, RELEASE_CHANNEL, GITHUB_REPO

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(get_start_page_url(current_user))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False)

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            # Validate redirect URL to prevent open redirect attacks
            safe_redirect = get_safe_redirect_url(next_page, default=None)
            return redirect(safe_redirect or get_start_page_url(user))

        flash(_('Invalid username or password'), 'error')

    registration_enabled = AppSettings.get('registration_enabled', 'true') == 'true'
    smtp_configured = bool(
        AppSettings.get('smtp_enabled', 'true') == 'true' and
        AppSettings.get('smtp_host') and
        AppSettings.get('smtp_username')
    )
    return render_template('auth/login.html', registration_enabled=registration_enabled, smtp_configured=smtp_configured)


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    smtp_configured = bool(
        AppSettings.get('smtp_enabled', 'true') == 'true' and
        AppSettings.get('smtp_host') and
        AppSettings.get('smtp_username')
    )

    if not smtp_configured:
        flash(_('Password reset by email is not available. Please contact an administrator.'), 'info')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()

        if user:
            token = user.generate_reset_token()
            db.session.commit()

            reset_url = url_for('auth.reset_password', token=token, _external=True)
            branding = AppSettings.get_all_branding()
            app_name = branding.get('app_name', 'May')

            body = f"You requested a password reset for your {app_name} account.\n\nClick the link below to reset your password:\n{reset_url}\n\nThis link expires in 1 hour.\n\nIf you did not request this, you can safely ignore this email."
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #0284c7;">Password Reset</h2>
                <p>You requested a password reset for your {app_name} account.</p>
                <p><a href="{reset_url}" style="display: inline-block; padding: 10px 20px; background-color: #0284c7; color: white; text-decoration: none; border-radius: 5px;">Reset Password</a></p>
                <p style="color: #6b7280; font-size: 12px;">This link expires in 1 hour. If you did not request this, you can safely ignore this email.</p>
            </body>
            </html>
            """
            NotificationService.send_email(user.email, f'{app_name} - Password Reset', body, html_body)

        # Always show the same message to prevent email enumeration
        flash(_('If an account with that email exists, a password reset link has been sent.'), 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    user = User.get_by_reset_token(token)
    if not user:
        flash(_('Invalid or expired reset link. Please request a new one.'), 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if password != confirm_password:
            flash(_('Passwords do not match'), 'error')
            return render_template('auth/reset_password.html', token=token)

        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            flash(error_msg, 'error')
            return render_template('auth/reset_password.html', token=token)

        user.set_password(password)
        user.clear_reset_token()
        db.session.commit()

        flash(_('Your password has been reset. Please log in.'), 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


def get_start_page_url(user):
    """Get the URL for the user's configured start page."""
    start_page = user.start_page or 'dashboard'
    page_routes = {
        'dashboard': 'main.dashboard',
        'vehicles': 'vehicles.index',
        'fuel': 'fuel.index',
        'fuel_quick': 'fuel.quick',
        'expenses': 'expenses.index',
        'reminders': 'reminders.index',
        'maintenance': 'maintenance.index',
        'recurring': 'recurring.index',
        'documents': 'documents.index',
        'stations': 'stations.index',
        'trips': 'trips.index',
        'charging': 'charging.index',
        'notes': 'notes.index',
        'allowance': 'allowance.index',
    }
    route = page_routes.get(start_page, 'main.dashboard')
    return url_for(route)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    # Check if registration is enabled
    if AppSettings.get('registration_enabled', 'true') != 'true':
        flash(_('New account registration is currently disabled.'), 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash(_('Passwords do not match'), 'error')
            return render_template('auth/register.html')

        # Validate password strength
        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            flash(error_msg, 'error')
            return render_template('auth/register.html')

        if User.query.filter_by(username=username).first():
            flash(_('Username already exists'), 'error')
            return render_template('auth/register.html')

        if User.query.filter_by(email=email).first():
            flash(_('Email already registered'), 'error')
            return render_template('auth/register.html')

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash(_('Registration successful! Please log in.'), 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash(_('You have been logged out.'), 'info')
    return redirect(url_for('auth.login'))


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_user.language = request.form.get('language', 'en')
        current_user.distance_unit = request.form.get('distance_unit', 'km')
        current_user.volume_unit = request.form.get('volume_unit', 'L')
        current_user.consumption_unit = request.form.get('consumption_unit', 'L/100km')
        submitted_separator = request.form.get('thousand_separator', 'none')
        if submitted_separator in ('none', 'space', 'comma', 'period'):
            current_user.thousand_separator = submitted_separator
        current_user.round_costs = request.form.get('round_costs') == 'on'
        currency = (request.form.get('currency', 'USD') or 'USD').strip()
        if currency == 'custom':
            custom_currency = (request.form.get('custom_currency') or '').strip()
            currency = custom_currency or 'USD'
        current_user.currency = currency[:10]
        current_user.date_format = request.form.get('date_format', 'DD/MM/YYYY')

        # Update email if provided
        new_email = request.form.get('email', '').strip()
        if new_email and new_email != current_user.email:
            existing = User.query.filter(User.email == new_email, User.id != current_user.id).first()
            if existing:
                flash(_('Email already in use by another account'), 'error')
                branding = AppSettings.get_all_branding() if current_user.is_admin else {}
                return render_template('auth/settings.html', branding=branding)
            current_user.email = new_email

        # Update password if provided
        new_password = request.form.get('new_password')
        if new_password:
            confirm_password = request.form.get('confirm_new_password')
            if new_password != confirm_password:
                flash(_('Passwords do not match'), 'error')
                branding = AppSettings.get_all_branding() if current_user.is_admin else {}
                return render_template('auth/settings.html', branding=branding)
            # Validate password strength
            is_valid, error_msg = validate_password_strength(new_password)
            if not is_valid:
                flash(error_msg, 'error')
                branding = AppSettings.get_all_branding() if current_user.is_admin else {}
                return render_template('auth/settings.html', branding=branding)
            current_user.set_password(new_password)

        db.session.commit()
        flash(_('Settings updated successfully'), 'success')
        return redirect(url_for('auth.settings'))

    branding = AppSettings.get_all_branding() if current_user.is_admin else {}

    # Get SMTP settings for admins
    smtp_settings = {}
    smtp_configured = False
    if current_user.is_admin:
        smtp_settings = {
            'enabled': AppSettings.get('smtp_enabled', 'true'),
            'host': AppSettings.get('smtp_host'),
            'port': AppSettings.get('smtp_port', '587'),
            'username': AppSettings.get('smtp_username'),
            'password': AppSettings.get('smtp_password'),
            'sender': AppSettings.get('smtp_sender'),
            'sender_name': AppSettings.get('smtp_sender_name'),
            'tls': AppSettings.get('smtp_tls', 'true'),
            'ssl': AppSettings.get('smtp_ssl', 'false'),
            'pushover_enabled': AppSettings.get('pushover_enabled', 'false'),
            'pushover_app_token': AppSettings.get('pushover_app_token'),
        }
    smtp_configured = bool(
        AppSettings.get('smtp_enabled', 'true') == 'true' and
        AppSettings.get('smtp_host') and
        AppSettings.get('smtp_username')
    )
    pushover_configured = bool(
        AppSettings.get('pushover_enabled') == 'true' and
        AppSettings.get('pushover_app_token')
    )

    # Get DVLA settings for admins
    dvla_settings = {}
    if current_user.is_admin:
        dvla_settings = {
            'api_key': AppSettings.get('dvla_api_key'),
        }

    # Get Tessie settings for admins
    tessie_settings = {}
    if current_user.is_admin:
        tessie_settings = {
            'api_token': AppSettings.get('tessie_api_token'),
        }

    # Get UK fuel price settings for admins
    uk_fuel_settings = {}
    if current_user.is_admin:
        from app.services.uk_fuel_prices import SETTING_FEEDS, UKFuelPriceService
        uk_fuel_settings = {
            'enabled': UKFuelPriceService.is_enabled(),
            'feed_urls': AppSettings.get(SETTING_FEEDS, ''),
            'retailer_count': len(UKFuelPriceService.get_feeds()),
        }

    # Get registration setting
    registration_enabled = AppSettings.get('registration_enabled', 'true') == 'true'

    return render_template('auth/settings.html',
                           branding=branding,
                           smtp_settings=smtp_settings,
                           smtp_configured=smtp_configured,
                           pushover_configured=pushover_configured,
                           dvla_settings=dvla_settings,
                           tessie_settings=tessie_settings,
                           uk_fuel_settings=uk_fuel_settings,
                           app_version=DISPLAY_VERSION,
                           release_channel=RELEASE_CHANNEL,
                           github_repo=GITHUB_REPO,
                           registration_enabled=registration_enabled)


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/notifications', methods=['POST'])
@login_required
def notifications():
    """Update user notification preferences"""
    # Validate webhook URL to prevent SSRF
    webhook_url = request.form.get('webhook_url') or None
    if webhook_url:
        is_valid, error_msg = validate_webhook_url(webhook_url)
        if not is_valid:
            flash(_('Invalid webhook URL: %(error)s') % {'error': error_msg}, 'error')
            return redirect(url_for('auth.settings') + '#notifications')

    current_user.email_reminders = request.form.get('email_reminders') == 'true'
    current_user.reminder_days_before = int(request.form.get('reminder_days_before', 7))
    current_user.notification_method = request.form.get('notification_method', 'email')
    current_user.webhook_url = webhook_url
    current_user.ntfy_topic = request.form.get('ntfy_topic') or None
    # The saved token is never rendered back to the page; blank means keep (#90)
    if request.form.get('clear_ntfy_token') == 'on':
        current_user.ntfy_token = None
    elif request.form.get('ntfy_token', '').strip():
        current_user.ntfy_token = request.form.get('ntfy_token').strip()
    current_user.pushover_user_key = request.form.get('pushover_user_key') or None
    db.session.commit()
    flash(_('Notification preferences updated'), 'success')
    return redirect(url_for('auth.settings') + '#notifications')


@bp.route('/menu-preferences', methods=['POST'])
@login_required
def menu_preferences():
    """Update user menu preferences"""
    current_user.start_page = request.form.get('start_page', 'dashboard')
    default_vehicle_id = request.form.get('default_vehicle_id')
    current_user.default_vehicle_id = int(default_vehicle_id) if default_vehicle_id else None
    current_user.show_menu_vehicles = request.form.get('show_menu_vehicles') == 'on'
    current_user.show_menu_fuel = request.form.get('show_menu_fuel') == 'on'
    current_user.show_menu_expenses = request.form.get('show_menu_expenses') == 'on'
    current_user.show_menu_reminders = request.form.get('show_menu_reminders') == 'on'
    current_user.show_menu_maintenance = request.form.get('show_menu_maintenance') == 'on'
    current_user.show_menu_recurring = request.form.get('show_menu_recurring') == 'on'
    current_user.show_menu_documents = request.form.get('show_menu_documents') == 'on'
    current_user.show_menu_stations = request.form.get('show_menu_stations') == 'on'
    current_user.show_menu_trips = request.form.get('show_menu_trips') == 'on'
    current_user.show_menu_charging = request.form.get('show_menu_charging') == 'on'
    current_user.show_menu_notes = request.form.get('show_menu_notes') == 'on'
    current_user.show_menu_allowance = request.form.get('show_menu_allowance') == 'on'
    current_user.show_menu_tires = request.form.get('show_menu_tires') == 'on'
    current_user.show_quick_entry = request.form.get('show_quick_entry') == 'on'
    db.session.commit()
    flash(_('Menu preferences updated'), 'success')
    return redirect(url_for('auth.settings') + '#menu')


@bp.route('/smtp-settings', methods=['POST'])
@login_required
@admin_required
def smtp_settings():
    """Update notification service settings (admin only)"""

    # SMTP settings
    AppSettings.set('smtp_enabled', 'true' if request.form.get('smtp_enabled') else 'false')
    AppSettings.set('smtp_host', request.form.get('smtp_host', ''))
    AppSettings.set('smtp_port', request.form.get('smtp_port', '587'))
    AppSettings.set('smtp_username', request.form.get('smtp_username', ''))
    AppSettings.set('smtp_password', request.form.get('smtp_password', ''))
    AppSettings.set('smtp_sender', request.form.get('smtp_sender', ''))
    AppSettings.set('smtp_sender_name', request.form.get('smtp_sender_name', ''))
    AppSettings.set('smtp_tls', 'true' if request.form.get('smtp_tls') else 'false')
    AppSettings.set('smtp_ssl', 'true' if request.form.get('smtp_ssl') else 'false')

    # Pushover settings
    AppSettings.set('pushover_enabled', 'true' if request.form.get('pushover_enabled') else 'false')
    AppSettings.set('pushover_app_token', request.form.get('pushover_app_token', ''))

    flash(_('Notification settings updated'), 'success')
    return redirect(url_for('auth.settings') + '#notifications')


@bp.route('/branding', methods=['POST'])
@login_required
@admin_required
def branding():

    # Save branding settings
    AppSettings.set('app_name', request.form.get('app_name', 'May'))
    AppSettings.set('app_tagline', request.form.get('app_tagline', 'Vehicle Management'))
    AppSettings.set('primary_color', request.form.get('primary_color', '#0284c7'))

    # Handle logo upload
    if 'logo' in request.files:
        file = request.files['logo']
        if file and file.filename and allowed_file(file.filename):
            # Delete old logo
            old_logo = AppSettings.get('logo_filename')
            if old_logo:
                old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], old_logo)
                if os.path.exists(old_path):
                    os.remove(old_path)

            filename = f"logo_{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            AppSettings.set('logo_filename', filename)

    flash(_('Branding settings updated successfully'), 'success')
    return redirect(url_for('auth.settings') + '#branding')


@bp.route('/branding/remove-logo', methods=['POST'])
@login_required
@admin_required
def remove_logo():
    """Remove the uploaded logo"""
    logo_filename = AppSettings.get('logo_filename')
    if logo_filename:
        logo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], logo_filename)
        if os.path.exists(logo_path):
            os.remove(logo_path)
        AppSettings.set('logo_filename', '')

    flash(_('Logo removed successfully'), 'success')
    return redirect(url_for('auth.settings') + '#branding')


@bp.route('/dvla-settings', methods=['POST'])
@login_required
@admin_required
def dvla_settings():
    """Update DVLA API settings (admin only)"""

    api_key = request.form.get('dvla_api_key', '').strip()
    AppSettings.set('dvla_api_key', api_key)

    flash(_('DVLA settings updated'), 'success')
    return redirect(url_for('auth.settings') + '#services-dvla')


@bp.route('/uk-fuel-settings', methods=['POST'])
@login_required
@admin_required
def uk_fuel_settings():
    """Update UK fuel price feed settings (admin only)"""
    from app.services.uk_fuel_prices import SETTING_ENABLED, SETTING_FEEDS

    enabled = request.form.get('uk_fuel_prices_enabled') == 'on'
    AppSettings.set(SETTING_ENABLED, 'true' if enabled else 'false')
    AppSettings.set(SETTING_FEEDS, request.form.get('uk_fuel_feed_urls', '').strip())

    flash(_('UK fuel price settings updated'), 'success')
    return redirect(url_for('auth.settings') + '#services-uk-fuel')


@bp.route('/tessie-settings', methods=['POST'])
@login_required
@admin_required
def tessie_settings():
    """Update Tessie API settings (admin only)"""

    api_token = request.form.get('tessie_api_token', '').strip()
    AppSettings.set('tessie_api_token', api_token)

    flash(_('Tessie settings updated'), 'success')
    return redirect(url_for('auth.settings') + '#services-tessie')


@bp.route('/registration-settings', methods=['POST'])
@login_required
@admin_required
def registration_settings():
    """Update registration settings (admin only)"""

    enabled = 'true' if request.form.get('registration_enabled') else 'false'
    AppSettings.set('registration_enabled', enabled)

    flash(_('Registration settings updated'), 'success')
    return redirect(url_for('auth.settings') + '#account')


@bp.route('/users')
@login_required
@admin_required
def users():
    users = User.query.all()
    return render_template('auth/users.html', users=users)


@bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        return redirect(url_for('auth.users'))

    # Prevent removing admin from the last admin account
    if user.is_admin:
        admin_count = User.query.filter_by(is_admin=True).count()
        if admin_count <= 1:
            flash(_('Cannot remove admin status from the last administrator.'), 'error')
            return redirect(url_for('auth.users'))

    user.is_admin = not user.is_admin
    db.session.commit()
    flash(_('Admin status updated for %(username)s') % {'username': user.username}, 'success')

    return redirect(url_for('auth.users'))


@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id != current_user.id:
        db.session.delete(user)
        db.session.commit()
        flash(_('User %(username)s deleted') % {'username': user.username}, 'success')

    return redirect(url_for('auth.users'))


@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Edit a user's details (admin only)"""
    user = db.get_or_404(User, user_id)

    if request.method == 'POST':
        new_email = request.form.get('email', '').strip()
        if new_email and new_email != user.email:
            existing = User.query.filter(User.email == new_email, User.id != user.id).first()
            if existing:
                flash(_('Email already in use by another account'), 'error')
                return render_template('auth/edit_user.html', user=user, roles=USER_ROLES,
                                       role_descriptions=USER_ROLE_DESCRIPTIONS)
            user.email = new_email

        new_password = request.form.get('new_password', '').strip()
        if new_password:
            confirm_password = request.form.get('confirm_new_password', '')
            if new_password != confirm_password:
                flash(_('Passwords do not match'), 'error')
                return render_template('auth/edit_user.html', user=user, roles=USER_ROLES,
                                       role_descriptions=USER_ROLE_DESCRIPTIONS)
            is_valid, error_msg = validate_password_strength(new_password)
            if not is_valid:
                flash(error_msg, 'error')
                return render_template('auth/edit_user.html', user=user, roles=USER_ROLES,
                                       role_descriptions=USER_ROLE_DESCRIPTIONS)
            user.set_password(new_password)

        is_admin = request.form.get('is_admin') == 'on'
        if user.id != current_user.id:
            user.is_admin = is_admin

        role = request.form.get('role', ROLE_EDITOR)
        if role in ROLE_WRITE_SCOPES:
            user.role = role

        db.session.commit()
        flash(_('User %(username)s updated successfully') % {'username': user.username}, 'success')
        return redirect(url_for('auth.users'))

    return render_template('auth/edit_user.html', user=user, roles=USER_ROLES,
                           role_descriptions=USER_ROLE_DESCRIPTIONS)


@bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    """Create a new user (admin only)"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        is_admin = request.form.get('is_admin') == 'on'
        role = request.form.get('role', ROLE_EDITOR)
        if role not in ROLE_WRITE_SCOPES:
            role = ROLE_EDITOR

        if not username or not email or not password:
            flash(_('Username, email, and password are required'), 'error')
            return render_template('auth/create_user.html', roles=USER_ROLES,
                                   role_descriptions=USER_ROLE_DESCRIPTIONS)

        if password != confirm_password:
            flash(_('Passwords do not match'), 'error')
            return render_template('auth/create_user.html', roles=USER_ROLES,
                                   role_descriptions=USER_ROLE_DESCRIPTIONS)

        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            flash(error_msg, 'error')
            return render_template('auth/create_user.html', roles=USER_ROLES,
                                   role_descriptions=USER_ROLE_DESCRIPTIONS)

        if User.query.filter_by(username=username).first():
            flash(_('Username already exists'), 'error')
            return render_template('auth/create_user.html', roles=USER_ROLES,
                                   role_descriptions=USER_ROLE_DESCRIPTIONS)

        if User.query.filter_by(email=email).first():
            flash(_('Email already in use'), 'error')
            return render_template('auth/create_user.html', roles=USER_ROLES,
                                   role_descriptions=USER_ROLE_DESCRIPTIONS)

        user = User(username=username, email=email, is_admin=is_admin, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash(_('User %(username)s created successfully') % {'username': username}, 'success')
        return redirect(url_for('auth.users'))

    return render_template('auth/create_user.html', roles=USER_ROLES,
                           role_descriptions=USER_ROLE_DESCRIPTIONS)


@bp.route('/check-updates')
@login_required
def check_updates():
    """Check GitHub for newer releases"""
    try:
        response = requests.get(
            f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest',
            timeout=10,
            headers={
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': f'May/{APP_VERSION}'
            }
        )
        if response.status_code == 200:
            data = response.json()
            latest_version = data.get('tag_name', '').lstrip('v')

            # Compare versions properly (semver-style)
            def parse_version(v):
                try:
                    return tuple(int(x) for x in v.split('.'))
                except (ValueError, AttributeError):
                    return (0, 0, 0)

            current_tuple = parse_version(APP_VERSION)
            latest_tuple = parse_version(latest_version)
            update_available = latest_tuple > current_tuple

            return jsonify({
                'success': True,
                'latest_version': latest_version,
                'current_version': APP_VERSION,
                'update_available': update_available,
                'release_url': data.get('html_url'),
                'release_notes': data.get('body', ''),
                'published_at': data.get('published_at')
            })
        else:
            return jsonify({'success': False, 'error': 'Could not fetch release info'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
