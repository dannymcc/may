import io
import pytest
from datetime import date
from app import db
from app.models import Attachment, Expense, EXPENSE_CATEGORIES


def _upload(filename, content=b'fake-image-bytes'):
    """Build a file tuple for a multipart POST."""
    return (io.BytesIO(content), filename)


class TestExpenseIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/expenses/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/expenses/')
        assert resp.status_code == 200

    def test_index_shows_expenses(self, auth_client, sample_expense):
        resp = auth_client.get('/expenses/')
        assert resp.status_code == 200


class TestExpenseNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/expenses/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/expenses/new')
        assert resp.status_code == 200

    def test_create_expense(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/expenses/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-02-10',
            'category': 'maintenance',
            'description': 'Tire rotation',
            'cost': '50.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        expense = Expense.query.filter_by(
            vehicle_id=sample_vehicle.id,
            description='Tire rotation'
        ).first()
        assert expense is not None
        assert expense.cost == 50.0
        assert expense.user_id == test_user.id

    def test_create_expense_with_optional_fields(self, auth_client, sample_vehicle):
        resp = auth_client.post('/expenses/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-02-15',
            'category': 'insurance',
            'description': 'Annual insurance',
            'cost': '500.00',
            'vendor': 'Insurance Co',
            'notes': 'Full coverage',
        }, follow_redirects=True)
        assert resp.status_code == 200
        expense = Expense.query.filter_by(description='Annual insurance').first()
        assert expense is not None
        assert expense.vendor == 'Insurance Co'


class TestExpenseEdit:
    def test_edit_requires_auth(self, client, sample_expense):
        resp = client.get(f'/expenses/{sample_expense.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_expense):
        resp = auth_client.get(f'/expenses/{sample_expense.id}/edit')
        assert resp.status_code == 200

    def test_edit_expense(self, auth_client, sample_expense):
        resp = auth_client.post(f'/expenses/{sample_expense.id}/edit', data={
            'date': '2024-01-20',
            'category': 'maintenance',
            'description': 'Updated oil change',
            'cost': '85.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_expense)
        assert sample_expense.description == 'Updated oil change'
        assert sample_expense.cost == 85.0

    def test_edit_form_no_odometer_omits_literal_none(self, auth_client, sample_expense):
        """Regression for #217: an expense without an odometer must not
        render value="None" into the odometer input, which would be
        submitted back and break the save."""
        assert sample_expense.odometer is None
        resp = auth_client.get(f'/expenses/{sample_expense.id}/edit')
        assert resp.status_code == 200
        assert b'value="None"' not in resp.data

    def test_edit_notes_persist_without_odometer(self, auth_client, sample_expense):
        """Regression for #217: editing notes on an expense that has no
        odometer must persist. The buggy edit form rendered value="None"
        for the odometer field; simulate that round-trip and confirm the
        notes are saved rather than silently discarded."""
        assert sample_expense.odometer is None
        resp = auth_client.post(f'/expenses/{sample_expense.id}/edit', data={
            'date': '2024-01-20',
            'category': 'maintenance',
            'description': 'Oil change',
            'cost': '75.00',
            'odometer': 'None',  # what the buggy template submitted
            'notes': 'Remember to check the filter next time',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_expense)
        assert sample_expense.notes == 'Remember to check the filter next time'
        assert sample_expense.odometer is None

    def test_edit_notes_change_persists(self, auth_client, test_user, sample_vehicle):
        """An expense that already has notes must save an updated notes value."""
        expense = Expense(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 4, 1),
            category='repairs',
            description='Clutch',
            cost=300.0,
            notes='Original notes',
        )
        db.session.add(expense)
        db.session.commit()

        resp = auth_client.post(f'/expenses/{expense.id}/edit', data={
            'date': '2024-04-01',
            'category': 'repairs',
            'description': 'Clutch',
            'cost': '300.00',
            'odometer': 'None',
            'notes': 'Updated notes after inspection',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(expense)
        assert expense.notes == 'Updated notes after inspection'


class TestExpenseDelete:
    def test_delete_requires_auth(self, client, sample_expense):
        resp = client.post(f'/expenses/{sample_expense.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_expense(self, auth_client, sample_expense):
        expense_id = sample_expense.id
        resp = auth_client.post(f'/expense_id/delete'.replace('expense_id', str(expense_id)),
                                follow_redirects=True)
        # Use correct URL
        resp = auth_client.post(f'/expenses/{expense_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert Expense.query.get(expense_id) is None


class TestExpenseAttachments:
    def test_create_expense_with_two_attachments(self, auth_client, sample_vehicle):
        resp = auth_client.post('/expenses/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-05-01',
            'category': 'repairs',
            'description': 'Two receipts',
            'cost': '99.00',
            'attachment': [_upload('receipt-one.jpg'), _upload('receipt-two.png')],
        }, content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200

        expense = Expense.query.filter_by(description='Two receipts').first()
        assert expense is not None
        names = sorted(a.original_filename for a in expense.attachments.all())
        assert names == ['receipt-one.jpg', 'receipt-two.png']

    def test_create_expense_with_single_attachment(self, auth_client, sample_vehicle):
        resp = auth_client.post('/expenses/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-05-02',
            'category': 'repairs',
            'description': 'One receipt',
            'cost': '10.00',
            'attachment': _upload('single.pdf'),
        }, content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200

        expense = Expense.query.filter_by(description='One receipt').first()
        attachments = expense.attachments.all()
        assert len(attachments) == 1
        assert attachments[0].original_filename == 'single.pdf'
        assert attachments[0].file_type == 'pdf'

    def test_disallowed_extension_is_skipped_and_reported(self, auth_client, sample_vehicle):
        resp = auth_client.post('/expenses/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-05-03',
            'category': 'repairs',
            'description': 'Mixed uploads',
            'cost': '20.00',
            'attachment': [_upload('notes.exe'), _upload('receipt.jpg')],
        }, content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        assert b'notes.exe' in resp.data

        expense = Expense.query.filter_by(description='Mixed uploads').first()
        attachments = expense.attachments.all()
        assert len(attachments) == 1
        assert attachments[0].original_filename == 'receipt.jpg'

    def test_edit_adds_further_attachments(self, auth_client, sample_expense):
        resp = auth_client.post(f'/expenses/{sample_expense.id}/edit', data={
            'date': '2024-01-20',
            'category': 'maintenance',
            'description': 'Oil change',
            'cost': '75.00',
            'attachment': [_upload('a.jpg'), _upload('b.jpg')],
        }, content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        assert sample_expense.attachments.count() == 2

    def test_index_links_to_attachments(self, auth_client, sample_expense):
        attachment = Attachment(
            filename='abc123_receipt.jpg',
            original_filename='receipt.jpg',
            file_type='jpg',
            expense_id=sample_expense.id,
        )
        db.session.add(attachment)
        db.session.commit()

        resp = auth_client.get('/expenses/')
        assert resp.status_code == 200
        assert b'/api/uploads/abc123_receipt.jpg' in resp.data
        assert b'receipt.jpg' in resp.data

    def test_delete_attachment_removes_only_that_row(self, auth_client, sample_expense):
        first = Attachment(filename='one.jpg', original_filename='one.jpg',
                           file_type='jpg', expense_id=sample_expense.id)
        second = Attachment(filename='two.jpg', original_filename='two.jpg',
                            file_type='jpg', expense_id=sample_expense.id)
        db.session.add_all([first, second])
        db.session.commit()
        first_id = first.id

        resp = auth_client.post(
            f'/expenses/{sample_expense.id}/attachments/{first_id}/delete',
            follow_redirects=True)
        assert resp.status_code == 200
        assert Attachment.query.get(first_id) is None
        assert sample_expense.attachments.count() == 1


class TestExpenseCategories:
    def test_inspection_category_exists(self):
        category_keys = [k for k, _ in EXPENSE_CATEGORIES]
        assert 'inspection' in category_keys

    def test_create_inspection_expense(self, auth_client, sample_vehicle):
        resp = auth_client.post('/expenses/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-01',
            'category': 'inspection',
            'description': 'Annual MOT inspection',
            'cost': '55.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        expense = Expense.query.filter_by(description='Annual MOT inspection').first()
        assert expense is not None
        assert expense.category == 'inspection'

    def test_expense_list_shows_odometer(self, auth_client, test_user, sample_vehicle):
        expense = Expense(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 3, 1),
            category='maintenance',
            description='Oil change with odometer',
            cost=40.0,
            odometer=12345.0,
        )
        db.session.add(expense)
        db.session.commit()
        resp = auth_client.get('/expenses/')
        assert resp.status_code == 200
        assert b'12345' in resp.data

    def test_expense_list_shows_expandable_details(self, auth_client, test_user, sample_vehicle):
        expense = Expense(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            date=date(2024, 3, 2),
            category='repairs',
            description='Brake pads',
            cost=120.0,
            vendor='AutoShop Ltd',
            notes='Front brakes replaced',
        )
        db.session.add(expense)
        db.session.commit()
        resp = auth_client.get('/expenses/')
        assert resp.status_code == 200
        assert b'AutoShop Ltd' in resp.data
        assert b'Front brakes replaced' in resp.data
