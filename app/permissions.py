"""Per-user permission enforcement (#285).

Every account carries a role (see ``app.models``). Administrators and editors
may change anything they can see; contributors may only record fuel and
charging; viewers may change nothing.

Rather than sprinkle a decorator through every route module, the rules are
applied in one place: a ``before_request`` hook that works out which area of
the application the request is about to write to and refuses the request when
the account's role does not cover it. Read requests are never blocked here —
what an account can *see* is still governed by vehicle ownership and sharing.

The mapping is by blueprint by default, so a new route in, say, ``fuel.py``
is covered the moment it is added. Endpoints that do not fit their
blueprint's scope (the API and Home Assistant blueprints, which span every
area) are listed individually, and any unrecognised write endpoint is refused
for restricted roles rather than allowed.
"""
from flask import request, redirect, url_for, flash, jsonify
from flask_login import current_user
from flask_babel import gettext as _

WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

# Blueprint name -> write scope. Routes in these blueprints only ever write
# data belonging to that area.
BLUEPRINT_SCOPES = {
    'vehicles': 'vehicles',
    'fuel': 'fuel',
    'charging': 'charging',
    'expenses': 'expenses',
    'maintenance': 'maintenance',
    'trips': 'trips',
    'reminders': 'reminders',
    'documents': 'documents',
    'notes': 'notes',
    'stations': 'stations',
    'recurring': 'recurring',
    'allowance': 'allowance',
    'tires': 'tires',
}

# Endpoints whose scope cannot be inferred from their blueprint.
ENDPOINT_SCOPES = {
    'api.api_create_vehicle': 'vehicles',
    'api.api_update_vehicle': 'vehicles',
    'api.api_delete_vehicle': 'vehicles',
    'api.refresh_vehicle_dvla': 'vehicles',
    'api.refresh_vehicle_tessie': 'vehicles',
    'api.dvla_lookup': 'vehicles',
    'api.api_create_fuel_log': 'fuel',
    'api.api_update_fuel_log': 'fuel',
    'api.api_delete_fuel_log': 'fuel',
    'api.api_create_charging_session': 'charging',
    'api.api_update_charging_session': 'charging',
    'api.api_delete_charging_session': 'charging',
    'api.api_create_expense': 'expenses',
    'api.api_update_expense': 'expenses',
    'api.api_delete_expense': 'expenses',
    'api.api_create_trip': 'trips',
    'api.api_update_trip': 'trips',
    'api.api_delete_trip': 'trips',
    'api.csv_import_preview': 'import',
    'api.csv_import_execute': 'import',
    'api.backup_restore_preview': 'import',
    'api.backup_restore_execute': 'import',
    'api.import_clarkson': 'import',
    'api.import_fuelly': 'import',
    'api.import_hammond': 'import',
    'api.import_tessie_charges': 'import',
    'homeassistant.add_fuel': 'fuel',
}

# Writes that concern the account itself rather than vehicle data, and so are
# open to every signed-in user whatever their role.
ACCOUNT_ENDPOINTS = {
    'auth.login',
    'auth.logout',
    'auth.register',
    'auth.forgot_password',
    'auth.reset_password',
    'auth.settings',
    'auth.notifications',
    'auth.menu_preferences',
    'api.toggle_dark_mode',
    'api.generate_api_key',
    'api.revoke_api_key',
    'api.test_notification',
}


def scope_for_endpoint(endpoint):
    """The write scope an endpoint belongs to, or None if it has no mapping."""
    if not endpoint:
        return None
    if endpoint in ENDPOINT_SCOPES:
        return ENDPOINT_SCOPES[endpoint]
    blueprint = endpoint.rsplit('.', 1)[0] if '.' in endpoint else ''
    return BLUEPRINT_SCOPES.get(blueprint)


def _acting_user():
    """The user this request acts as: the signed-in user or an API key holder."""
    if current_user and current_user.is_authenticated:
        return current_user

    from app.models import User

    api_key = None
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.lower().startswith('bearer '):
        api_key = auth_header[7:]
    if not api_key:
        api_key = request.headers.get('X-API-Key')
    return User.get_by_api_key(api_key) if api_key else None


def _wants_json():
    if request.path.startswith('/api/'):
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.accept_mimetypes
    return accept.best == 'application/json'


def _refuse():
    message = _('Your account does not have permission to change this data.')
    if _wants_json():
        return jsonify({'error': message, 'code': 'permission_denied'}), 403
    flash(message, 'error')
    return redirect(url_for('main.dashboard'))


def check_request_permission():
    """``before_request`` hook enforcing the acting user's role."""
    endpoint = request.endpoint
    if not endpoint or endpoint in ACCOUNT_ENDPOINTS:
        return None

    scope = scope_for_endpoint(endpoint)
    is_write = request.method in WRITE_METHODS
    # A GET on a route that also accepts POST is a form page; there is no
    # point letting a restricted user fill in a form that will be refused.
    is_form_page = (
        not is_write
        and scope is not None
        and request.url_rule is not None
        and bool(WRITE_METHODS & set(request.url_rule.methods or ()))
    )
    if not is_write and not is_form_page:
        return None

    user = _acting_user()
    if user is None:
        # Not signed in — leave the refusal to login_required / API auth.
        return None
    if user.is_admin:
        return None

    if scope is None:
        # An unmapped write endpoint: allow it only for accounts that may
        # write everywhere anyway, so new routes fail closed.
        return None if user.has_full_write_access else _refuse()

    return None if user.can_write(scope) else _refuse()


def register_permission_hooks(app):
    """Install the permission guard and the ``can_write`` template helper."""
    app.before_request(check_request_permission)

    @app.context_processor
    def inject_permissions():
        def can_write(scope):
            if not (current_user and current_user.is_authenticated):
                return False
            return current_user.can_write(scope)

        return {'can_write': can_write}
