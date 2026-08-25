"""Tests for per-user roles and permission enforcement (#285)."""
from datetime import date

import pytest

from app import db
from app.models import (
    User, FuelLog, Expense, ROLE_CONTRIBUTOR, ROLE_EDITOR, ROLE_VIEWER,
)
from app.permissions import scope_for_endpoint


def _make_user(username, role, vehicle=None):
    user = User(username=username, email=f'{username}@example.com', role=role)
    user.set_password('TestPass123!')
    db.session.add(user)
    db.session.commit()
    if vehicle is not None:
        vehicle.shared_users.append(user)
        db.session.commit()
    return user


def _login(client, username):
    return client.post('/auth/login', data={
        'username': username,
        'password': 'TestPass123!',
    }, follow_redirects=True)


@pytest.fixture
def contributor(app, sample_vehicle):
    return _make_user('driver', ROLE_CONTRIBUTOR, sample_vehicle)


@pytest.fixture
def viewer(app, sample_vehicle):
    return _make_user('owner', ROLE_VIEWER, sample_vehicle)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class TestUserRole:
    def test_default_role_is_editor(self, test_user):
        assert test_user.effective_role == ROLE_EDITOR
        assert test_user.has_full_write_access is True
        assert test_user.is_read_only is False

    def test_role_missing_is_treated_as_editor(self, test_user):
        test_user.role = None
        assert test_user.effective_role == ROLE_EDITOR
        assert test_user.can_write('expenses') is True

    def test_unknown_role_is_treated_as_editor(self, test_user):
        test_user.role = 'nonsense'
        assert test_user.effective_role == ROLE_EDITOR

    def test_admin_overrides_role(self, admin_user):
        admin_user.role = ROLE_VIEWER
        assert admin_user.effective_role == 'admin'
        assert admin_user.can_write('expenses') is True
        assert admin_user.is_read_only is False

    def test_contributor_may_only_write_fuel_and_charging(self, test_user):
        test_user.role = ROLE_CONTRIBUTOR
        assert test_user.can_write('fuel') is True
        assert test_user.can_write('charging') is True
        assert test_user.can_write('expenses') is False
        assert test_user.can_write('vehicles') is False
        assert test_user.has_full_write_access is False
        assert test_user.is_read_only is False

    def test_viewer_may_write_nothing(self, test_user):
        test_user.role = ROLE_VIEWER
        assert test_user.can_write('fuel') is False
        assert test_user.can_write('expenses') is False
        assert test_user.is_read_only is True


class TestScopeForEndpoint:
    def test_blueprint_scope(self):
        assert scope_for_endpoint('fuel.delete_attachment') == 'fuel'
        assert scope_for_endpoint('expenses.new') == 'expenses'

    def test_endpoint_override(self):
        assert scope_for_endpoint('api.api_create_fuel_log') == 'fuel'
        assert scope_for_endpoint('homeassistant.add_fuel') == 'fuel'
        assert scope_for_endpoint('api.csv_import_execute') == 'import'

    def test_unmapped_endpoint(self):
        assert scope_for_endpoint('auth.smtp_settings') is None
        assert scope_for_endpoint(None) is None


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

class TestContributorWebAccess:
    def test_can_log_fuel(self, client, contributor, sample_vehicle):
        _login(client, 'driver')
        response = client.post('/fuel/new', data={
            'vehicle_id': sample_vehicle.id,
            'date': '2024-02-01',
            'odometer': '20000',
            'volume': '40',
            'price_per_unit': '1.50',
            'total_cost': '60',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert FuelLog.query.filter_by(user_id=contributor.id).count() == 1

    def test_cannot_add_an_expense(self, client, contributor, sample_vehicle):
        _login(client, 'driver')
        before = Expense.query.count()
        response = client.post('/expenses/new', data={
            'vehicle_id': sample_vehicle.id,
            'date': '2024-02-01',
            'category': 'maintenance',
            'description': 'New tyres',
            'cost': '300',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert Expense.query.count() == before
        assert 'does not have permission' in response.get_data(as_text=True)

    def test_cannot_open_the_expense_form(self, client, contributor):
        _login(client, 'driver')
        response = client.get('/expenses/new')
        assert response.status_code == 302

    def test_cannot_edit_a_vehicle(self, client, contributor, sample_vehicle):
        _login(client, 'driver')
        response = client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': 'Renamed',
            'vehicle_type': 'car',
        }, follow_redirects=True)
        assert response.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.name == 'Test Car'

    def test_can_still_read_expenses(self, client, contributor):
        _login(client, 'driver')
        assert client.get('/expenses/').status_code == 200

    def test_can_still_change_own_settings(self, client, contributor):
        _login(client, 'driver')
        response = client.post('/auth/menu-preferences', data={
            'start_page': 'fuel',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert User.query.filter_by(username='driver').first().start_page == 'fuel'


class TestViewerWebAccess:
    def test_cannot_log_fuel(self, client, viewer, sample_vehicle):
        _login(client, 'owner')
        before = FuelLog.query.count()
        response = client.post('/fuel/new', data={
            'vehicle_id': sample_vehicle.id,
            'date': '2024-02-01',
            'odometer': '20000',
            'volume': '40',
            'price_per_unit': '1.50',
            'total_cost': '60',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert FuelLog.query.count() == before

    def test_can_read_the_fuel_list(self, client, viewer, sample_fuel_log):
        _login(client, 'owner')
        assert client.get('/fuel/').status_code == 200

    def test_cannot_delete_a_fuel_log(self, client, viewer, sample_fuel_log):
        _login(client, 'owner')
        client.post(f'/fuel/{sample_fuel_log.id}/delete', follow_redirects=True)
        assert db.session.get(FuelLog, sample_fuel_log.id) is not None


class TestControlsAreHidden:
    def test_viewer_does_not_see_the_add_fuel_button(self, client, viewer):
        _login(client, 'owner')
        body = client.get('/fuel/').get_data(as_text=True)
        assert '/fuel/new' not in body

    def test_contributor_sees_the_add_fuel_button(self, client, contributor):
        _login(client, 'driver')
        body = client.get('/fuel/').get_data(as_text=True)
        assert '/fuel/new' in body

    def test_contributor_does_not_see_the_add_expense_button(self, client, contributor):
        _login(client, 'driver')
        body = client.get('/expenses/').get_data(as_text=True)
        assert '/expenses/new' not in body

    def test_editor_sees_the_add_expense_button(self, auth_client):
        body = auth_client.get('/expenses/').get_data(as_text=True)
        assert '/expenses/new' in body


class TestEditorUnaffected:
    def test_editor_can_add_an_expense(self, auth_client, sample_vehicle):
        before = Expense.query.count()
        response = auth_client.post('/expenses/new', data={
            'vehicle_id': sample_vehicle.id,
            'date': '2024-02-01',
            'category': 'maintenance',
            'description': 'New tyres',
            'cost': '300',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert Expense.query.count() == before + 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class TestApiPermissions:
    def _key(self, user):
        key = user.generate_api_key()
        db.session.commit()
        return {'X-API-Key': key}

    def test_contributor_can_create_a_fuel_log(self, client, contributor, sample_vehicle):
        response = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/fuel',
            json={'date': '2024-02-01', 'odometer': 20000, 'volume': 40,
                  'price_per_unit': 1.5, 'total_cost': 60},
            headers=self._key(contributor),
        )
        assert response.status_code == 201

    def test_contributor_cannot_create_an_expense(self, client, contributor, sample_vehicle):
        response = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/expenses',
            json={'date': '2024-02-01', 'category': 'maintenance', 'cost': 300},
            headers=self._key(contributor),
        )
        assert response.status_code == 403
        assert response.get_json()['code'] == 'permission_denied'

    def test_viewer_cannot_create_a_fuel_log(self, client, viewer, sample_vehicle):
        response = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/fuel',
            json={'date': '2024-02-01', 'odometer': 20000, 'volume': 40},
            headers=self._key(viewer),
        )
        assert response.status_code == 403

    def test_viewer_can_still_read(self, client, viewer, sample_vehicle):
        response = client.get('/api/v1/vehicles', headers=self._key(viewer))
        assert response.status_code == 200

    def test_editor_api_access_is_unchanged(self, client, test_user, sample_vehicle, api_headers):
        response = client.post(
            f'/api/v1/vehicles/{sample_vehicle.id}/expenses',
            json={'date': '2024-02-01', 'category': 'maintenance',
                  'description': 'New tyres', 'cost': 300},
            headers=api_headers,
        )
        assert response.status_code == 201


# ---------------------------------------------------------------------------
# Admin management of roles
# ---------------------------------------------------------------------------

class TestAdminRoleManagement:
    def test_create_user_with_a_role(self, admin_client):
        response = admin_client.post('/auth/users/create', data={
            'username': 'newdriver',
            'email': 'newdriver@example.com',
            'password': 'TestPass123!',
            'confirm_password': 'TestPass123!',
            'role': ROLE_CONTRIBUTOR,
        }, follow_redirects=True)
        assert response.status_code == 200
        created = User.query.filter_by(username='newdriver').first()
        assert created is not None
        assert created.role == ROLE_CONTRIBUTOR

    def test_create_user_defaults_to_editor(self, admin_client):
        admin_client.post('/auth/users/create', data={
            'username': 'plain',
            'email': 'plain@example.com',
            'password': 'TestPass123!',
            'confirm_password': 'TestPass123!',
        }, follow_redirects=True)
        assert User.query.filter_by(username='plain').first().role == ROLE_EDITOR

    def test_create_user_rejects_an_unknown_role(self, admin_client):
        admin_client.post('/auth/users/create', data={
            'username': 'sneaky',
            'email': 'sneaky@example.com',
            'password': 'TestPass123!',
            'confirm_password': 'TestPass123!',
            'role': 'superuser',
        }, follow_redirects=True)
        assert User.query.filter_by(username='sneaky').first().role == ROLE_EDITOR

    def test_edit_user_changes_the_role(self, admin_client, test_user):
        response = admin_client.post(f'/auth/users/{test_user.id}/edit', data={
            'email': test_user.email,
            'role': ROLE_VIEWER,
        }, follow_redirects=True)
        assert response.status_code == 200
        assert db.session.get(User, test_user.id).role == ROLE_VIEWER

    def test_role_shown_on_the_users_page(self, admin_client, test_user):
        response = admin_client.get('/auth/users')
        assert response.status_code == 200
        assert 'Editor' in response.get_data(as_text=True)

    def test_non_admin_cannot_reach_user_management(self, auth_client):
        response = auth_client.get('/auth/users', follow_redirects=True)
        assert 'Admin privileges required' in response.get_data(as_text=True)
