import pytest
from app import db
from app.models import Expense, RecurringExpense
from datetime import date


@pytest.fixture
def sample_recurring(app, test_user, sample_vehicle):
    recurring = RecurringExpense(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        name='Monthly Insurance',
        category='insurance',
        frequency='monthly',
        amount=100.0,
        start_date=date(2024, 1, 1),
        next_due=date(2024, 2, 1),
        is_active=True,
    )
    db.session.add(recurring)
    db.session.commit()
    return recurring


class TestRecurringIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/recurring/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/recurring/')
        assert resp.status_code == 200

    def test_index_shows_recurring(self, auth_client, sample_recurring):
        resp = auth_client.get('/recurring/')
        assert resp.status_code == 200
        assert b'Monthly Insurance' in resp.data


class TestRecurringNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/recurring/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/recurring/new')
        assert resp.status_code == 200

    def test_create_recurring(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/recurring/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'name': 'Road Tax',
            'category': 'tax',
            'frequency': 'yearly',
            'amount': '250.00',
            'start_date': '2024-01-01',
        }, follow_redirects=True)
        assert resp.status_code == 200
        recurring = RecurringExpense.query.filter_by(name='Road Tax').first()
        assert recurring is not None
        assert recurring.user_id == test_user.id
        assert recurring.frequency == 'yearly'

    def test_create_recurring_saves_vendor(self, auth_client, sample_vehicle, test_user):
        """#349: the recurring expense form should capture a vendor so that
        auto-generated expenses are allocated to it, the same way the
        one-off expense form does."""
        resp = auth_client.post('/recurring/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'name': 'Car Insurance',
            'category': 'insurance',
            'frequency': 'yearly',
            'amount': '250.00',
            'start_date': '2024-01-01',
            'vendor': 'Acme Insurance Co',
        }, follow_redirects=True)
        assert resp.status_code == 200
        recurring = RecurringExpense.query.filter_by(name='Car Insurance').first()
        assert recurring is not None
        assert recurring.vendor == 'Acme Insurance Co'

    def test_new_form_offers_vendor_field(self, auth_client, sample_vehicle):
        resp = auth_client.get('/recurring/new')
        assert resp.status_code == 200
        assert b'name="vendor"' in resp.data

    def test_generated_expense_gets_the_vendor(self, auth_client, sample_vehicle):
        """#349: the point of the field — the expense created from the
        schedule is allocated to the vendor."""
        auth_client.post('/recurring/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'name': 'Breakdown Cover',
            'category': 'insurance',
            'frequency': 'yearly',
            'amount': '90.00',
            'start_date': '2024-01-01',
            'vendor': 'Acme Recovery',
        }, follow_redirects=True)
        recurring = RecurringExpense.query.filter_by(name='Breakdown Cover').first()

        resp = auth_client.post(f'/recurring/{recurring.id}/generate', follow_redirects=True)
        assert resp.status_code == 200

        expense = Expense.query.filter_by(vehicle_id=sample_vehicle.id).first()
        assert expense is not None
        assert expense.vendor == 'Acme Recovery'


class TestRecurringEdit:
    def test_edit_requires_auth(self, client, sample_recurring):
        resp = client.get(f'/recurring/{sample_recurring.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_recurring):
        resp = auth_client.get(f'/recurring/{sample_recurring.id}/edit')
        assert resp.status_code == 200

    def test_edit_recurring(self, auth_client, sample_recurring):
        resp = auth_client.post(f'/recurring/{sample_recurring.id}/edit', data={
            'name': 'Updated Insurance',
            'category': 'insurance',
            'frequency': 'quarterly',
            'amount': '120.00',
            'start_date': '2024-01-01',
            'next_due': '2024-04-01',
            'remind_days_before': '7',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_recurring)
        assert sample_recurring.name == 'Updated Insurance'
        assert sample_recurring.frequency == 'quarterly'

    def test_edit_recurring_saves_vendor(self, auth_client, sample_recurring):
        """#349: editing a recurring expense should let you set the vendor
        so it flows through to auto-generated expenses."""
        resp = auth_client.post(f'/recurring/{sample_recurring.id}/edit', data={
            'name': sample_recurring.name,
            'category': sample_recurring.category,
            'frequency': sample_recurring.frequency,
            'amount': '100.00',
            'start_date': '2024-01-01',
            'next_due': '2024-02-01',
            'remind_days_before': '7',
            'vendor': 'Acme Insurance Co',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_recurring)
        assert sample_recurring.vendor == 'Acme Insurance Co'

    def test_edit_form_prefills_vendor(self, auth_client, sample_recurring):
        sample_recurring.vendor = 'Acme Insurance Co'
        db.session.commit()
        resp = auth_client.get(f'/recurring/{sample_recurring.id}/edit')
        assert resp.status_code == 200
        assert b'Acme Insurance Co' in resp.data


class TestRecurringDelete:
    def test_delete_requires_auth(self, client, sample_recurring):
        resp = client.post(f'/recurring/{sample_recurring.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_recurring(self, auth_client, sample_recurring):
        recurring_id = sample_recurring.id
        resp = auth_client.post(f'/recurring/{recurring_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(RecurringExpense, recurring_id) is None


class TestRecurringGenerate:
    def test_generate_requires_auth(self, client, sample_recurring):
        resp = client.post(f'/recurring/{sample_recurring.id}/generate', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_generate_creates_expense(self, auth_client, sample_recurring):
        from app.models import Expense
        resp = auth_client.post(f'/recurring/{sample_recurring.id}/generate', follow_redirects=True)
        assert resp.status_code == 200
        expense = Expense.query.filter_by(
            vehicle_id=sample_recurring.vehicle_id,
            category=sample_recurring.category
        ).first()
        assert expense is not None
        assert expense.cost == sample_recurring.amount


class TestRecurringToggle:
    def test_toggle_requires_auth(self, client, sample_recurring):
        resp = client.post(f'/recurring/{sample_recurring.id}/toggle', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_toggle_active(self, auth_client, sample_recurring):
        assert sample_recurring.is_active is True
        resp = auth_client.post(f'/recurring/{sample_recurring.id}/toggle', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_recurring)
        assert sample_recurring.is_active is False

    def test_toggle_inactive_to_active(self, auth_client, sample_recurring):
        sample_recurring.is_active = False
        db.session.commit()

        resp = auth_client.post(f'/recurring/{sample_recurring.id}/toggle', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_recurring)
        assert sample_recurring.is_active is True
