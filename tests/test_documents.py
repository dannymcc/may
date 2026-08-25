import pytest
import io
from app import db
from app.models import Document
from datetime import date


@pytest.fixture
def sample_document(app, test_user, sample_vehicle):
    import os
    # Create a dummy file
    filename = 'test_doc_file.pdf'
    file_path = os.path.join('/tmp/may_test_uploads', filename)
    os.makedirs('/tmp/may_test_uploads', exist_ok=True)
    with open(file_path, 'wb') as f:
        f.write(b'%PDF-1.4 test content')

    document = Document(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='MOT Certificate',
        document_type='mot',
        filename=filename,
        original_filename='mot_certificate.pdf',
        file_type='pdf',
        file_size=20,
    )
    db.session.add(document)
    db.session.commit()
    return document


class TestDocumentIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/documents/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/documents/')
        assert resp.status_code == 200

    def test_index_shows_documents(self, auth_client, sample_document):
        resp = auth_client.get('/documents/')
        assert resp.status_code == 200
        assert b'MOT Certificate' in resp.data


class TestDocumentNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/documents/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/documents/new')
        assert resp.status_code == 200

    def test_create_document(self, auth_client, sample_vehicle, test_user):
        data = {
            'vehicle_id': str(sample_vehicle.id),
            'title': 'Insurance Certificate',
            'document_type': 'insurance',
            'description': 'Annual insurance',
            'file': (io.BytesIO(b'PDF content here'), 'insurance.pdf'),
        }
        resp = auth_client.post('/documents/new', data=data,
                                content_type='multipart/form-data',
                                follow_redirects=True)
        assert resp.status_code == 200
        doc = Document.query.filter_by(title='Insurance Certificate').first()
        assert doc is not None
        assert doc.user_id == test_user.id

    def test_create_document_no_file_returns_error(self, auth_client, sample_vehicle):
        resp = auth_client.post('/documents/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'title': 'Test Doc',
            'document_type': 'other',
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Should not create a document without file
        assert Document.query.filter_by(title='Test Doc').first() is None


class TestDocumentView:
    def test_view_requires_auth(self, client, sample_document):
        resp = client.get(f'/documents/{sample_document.id}', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_view_returns_200(self, auth_client, sample_document):
        resp = auth_client.get(f'/documents/{sample_document.id}')
        assert resp.status_code == 200
        assert b'MOT Certificate' in resp.data

    def test_view_404_for_nonexistent(self, auth_client):
        resp = auth_client.get('/documents/99999')
        assert resp.status_code == 404


class TestDocumentEdit:
    def test_edit_requires_auth(self, client, sample_document):
        resp = client.get(f'/documents/{sample_document.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_document):
        resp = auth_client.get(f'/documents/{sample_document.id}/edit')
        assert resp.status_code == 200

    def test_edit_document(self, auth_client, sample_document):
        resp = auth_client.post(f'/documents/{sample_document.id}/edit', data={
            'title': 'Updated MOT Certificate',
            'document_type': 'mot',
            'description': 'Updated description',
            'remind_days': '30',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_document)
        assert sample_document.title == 'Updated MOT Certificate'


class TestDocumentDelete:
    def test_delete_requires_auth(self, client, sample_document):
        resp = client.post(f'/documents/{sample_document.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_document(self, auth_client, sample_document):
        doc_id = sample_document.id
        resp = auth_client.post(f'/documents/{doc_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(Document, doc_id) is None
