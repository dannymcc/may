import pytest
from datetime import date
from app import db
from app.models import Note


@pytest.fixture(scope='function')
def sample_note(app, test_user, sample_vehicle):
    note = Note(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 1, 18),
        title='DPF regeneration',
        content='Active regen completed on the motorway.',
        odometer=12345.0,
    )
    db.session.add(note)
    db.session.commit()
    return note


class TestNotesIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/notes/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/notes/')
        assert resp.status_code == 200

    def test_index_shows_notes(self, auth_client, sample_note):
        resp = auth_client.get('/notes/')
        assert resp.status_code == 200
        assert b'DPF regeneration' in resp.data


class TestNotesNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/notes/new', follow_redirects=False)
        assert resp.status_code == 302

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/notes/new')
        assert resp.status_code == 200

    def test_create_note(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/notes/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-02-10',
            'title': 'Tyre pressure check',
            'content': 'All four at 32 psi.',
            'odometer': '13000',
        }, follow_redirects=True)
        assert resp.status_code == 200
        note = Note.query.filter_by(vehicle_id=sample_vehicle.id, title='Tyre pressure check').first()
        assert note is not None
        assert note.content == 'All four at 32 psi.'
        assert note.odometer == 13000.0
        assert note.user_id == test_user.id

    def test_create_note_without_content_rejected(self, auth_client, sample_vehicle):
        resp = auth_client.post('/notes/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-02-10',
            'content': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Note.query.filter_by(vehicle_id=sample_vehicle.id).count() == 0

    def test_create_note_optional_odometer(self, auth_client, sample_vehicle):
        resp = auth_client.post('/notes/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-02-11',
            'content': 'No odometer recorded.',
        }, follow_redirects=True)
        assert resp.status_code == 200
        note = Note.query.filter_by(content='No odometer recorded.').first()
        assert note is not None
        assert note.odometer is None


class TestNotesEdit:
    def test_edit_requires_auth(self, client, sample_note):
        resp = client.get(f'/notes/{sample_note.id}/edit', follow_redirects=False)
        assert resp.status_code == 302

    def test_get_edit_form_returns_200(self, auth_client, sample_note):
        resp = auth_client.get(f'/notes/{sample_note.id}/edit')
        assert resp.status_code == 200

    def test_edit_note(self, auth_client, sample_note):
        resp = auth_client.post(f'/notes/{sample_note.id}/edit', data={
            'date': '2024-01-18',
            'title': 'DPF regeneration',
            'content': 'Updated: regen completed twice.',
            'odometer': '12400',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_note)
        assert sample_note.content == 'Updated: regen completed twice.'
        assert sample_note.odometer == 12400.0


class TestNotesDelete:
    def test_delete_requires_auth(self, client, sample_note):
        resp = client.post(f'/notes/{sample_note.id}/delete', follow_redirects=False)
        assert resp.status_code == 302

    def test_delete_note(self, auth_client, sample_note):
        note_id = sample_note.id
        resp = auth_client.post(f'/notes/{note_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(Note, note_id) is None


class TestNoteRedirects:
    """Saving a note returns to the notes list unless the user came from a
    vehicle page (#283)."""

    def _payload(self, vehicle, **overrides):
        data = {
            'vehicle_id': str(vehicle.id),
            'date': '2024-05-02',
            'title': 'Redirect test',
            'content': 'Checking where we land.',
        }
        data.update(overrides)
        return data

    def test_create_redirects_to_notes(self, auth_client, sample_vehicle):
        resp = auth_client.post('/notes/new', data=self._payload(sample_vehicle),
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/notes/')

    def test_create_returns_to_vehicle_when_requested(self, auth_client, sample_vehicle):
        resp = auth_client.post('/notes/new',
                                data=self._payload(sample_vehicle, return_to='vehicle'),
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/vehicles/{sample_vehicle.id}')

    def test_edit_redirects_to_notes(self, auth_client, sample_note):
        resp = auth_client.post(f'/notes/{sample_note.id}/edit',
                                data=self._payload(sample_note.vehicle),
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/notes/')

    def test_edit_returns_to_vehicle_when_requested(self, auth_client, sample_note):
        vehicle_id = sample_note.vehicle_id
        resp = auth_client.post(f'/notes/{sample_note.id}/edit',
                                data=self._payload(sample_note.vehicle,
                                                   return_to='vehicle'),
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/vehicles/{vehicle_id}')

    def test_delete_redirects_to_notes(self, auth_client, sample_note):
        resp = auth_client.post(f'/notes/{sample_note.id}/delete',
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/notes/')

    def test_delete_returns_to_vehicle_when_requested(self, auth_client, sample_note):
        vehicle_id = sample_note.vehicle_id
        resp = auth_client.post(f'/notes/{sample_note.id}/delete?return_to=vehicle',
                                follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/vehicles/{vehicle_id}')

    def test_form_from_notes_page_omits_hidden_field(self, auth_client, sample_vehicle):
        resp = auth_client.get('/notes/new')
        assert resp.status_code == 200
        assert b'name="return_to"' not in resp.data
