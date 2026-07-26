import pytest
from app.models import Vehicle, VehicleNote
from app.security import sanitize_html


def test_notes_index_requires_login(client):
    """Notes page should redirect anonymous users to login."""
    response = client.get('/notes/')
    assert response.status_code == 302


def test_notes_index_lists_accessible_notes(auth_client, sample_vehicle, test_user):
    """Centralized notes page shows notes for accessible vehicles."""
    note = VehicleNote(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='Test Note',
        content='<p>Note content</p>',
    )
    from app import db
    db.session.add(note)
    db.session.commit()

    response = auth_client.get('/notes/')
    assert response.status_code == 200
    assert b'Test Note' in response.data
    assert b'Note content' in response.data


def test_notes_index_search(auth_client, sample_vehicle, test_user):
    """Search filters notes by title/content."""
    from app import db
    note1 = VehicleNote(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='Maintenance Plan',
        content='<p>Oil change schedule</p>',
    )
    note2 = VehicleNote(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='Trip Ideas',
        content='<p>Highlands route</p>',
    )
    db.session.add_all([note1, note2])
    db.session.commit()

    response = auth_client.get('/notes/?search=maintenance')
    assert response.status_code == 200
    assert b'Maintenance Plan' in response.data
    assert b'Trip Ideas' not in response.data


def test_notes_create(auth_client, sample_vehicle, test_user):
    """User can create a new note for an accessible vehicle."""
    response = auth_client.post('/notes/new', data={
        'vehicle_id': sample_vehicle.id,
        'title': 'New Note',
        'content': '<p>New content</p>',
        'is_pinned': '1',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Note added successfully' in response.data

    note = VehicleNote.query.filter_by(title='New Note').first()
    assert note is not None
    assert note.content == '<p>New content</p>'
    assert note.is_pinned is True
    assert note.user_id == test_user.id


def test_notes_create_requires_title(auth_client, sample_vehicle):
    """Creating a note without a title shows an error."""
    response = auth_client.post('/notes/new', data={
        'vehicle_id': sample_vehicle.id,
        'title': '',
        'content': '<p>Content</p>',
    })
    assert response.status_code == 400
    assert b'Title is required' in response.data


def test_notes_edit(auth_client, sample_vehicle, test_user):
    """User can edit their note."""
    from app import db
    note = VehicleNote(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='Original',
        content='<p>Original content</p>',
    )
    db.session.add(note)
    db.session.commit()

    response = auth_client.post(f'/notes/{note.id}/edit', data={
        'vehicle_id': sample_vehicle.id,
        'title': 'Updated',
        'content': '<p>Updated content</p>',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Note updated successfully' in response.data

    updated = VehicleNote.query.get(note.id)
    assert updated.title == 'Updated'
    assert updated.content == '<p>Updated content</p>'


def test_notes_delete(auth_client, sample_vehicle, test_user):
    """User can delete their note."""
    from app import db
    note = VehicleNote(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='To Delete',
        content='<p>Delete me</p>',
    )
    db.session.add(note)
    db.session.commit()

    response = auth_client.post(f'/notes/{note.id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert b'Note deleted successfully' in response.data
    assert VehicleNote.query.get(note.id) is None


def test_notes_access_denied_for_unshared_vehicle(auth_client, test_user, admin_user):
    """User cannot access notes for vehicles they do not own or share."""
    from app import db
    other_vehicle = Vehicle(
        owner_id=admin_user.id,
        name='Admin Vehicle',
        vehicle_type='car',
    )
    db.session.add(other_vehicle)
    db.session.commit()

    note = VehicleNote(
        vehicle_id=other_vehicle.id,
        user_id=admin_user.id,
        title='Secret',
        content='<p>Secret content</p>',
    )
    db.session.add(note)
    db.session.commit()

    response = auth_client.get(f'/notes/{note.id}/edit')
    assert response.status_code == 302

    response = auth_client.get(f'/notes/{note.id}/edit', follow_redirects=True)
    assert b'Access denied' in response.data


def test_notes_html_sanitization():
    """Dangerous HTML is sanitized before storage."""
    dirty = '<p>Hello</p><script>alert("xss")</script>'
    clean = sanitize_html(dirty)
    assert '<p>Hello</p>' in clean
    assert '<script>' not in clean
    assert '</script>' not in clean


def test_notes_vehicle_notes_page(auth_client, sample_vehicle, test_user):
    """Vehicle-specific notes page lists notes for that vehicle."""
    from app import db
    note = VehicleNote(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='Vehicle Note',
        content='<p>Details</p>',
    )
    db.session.add(note)
    db.session.commit()

    response = auth_client.get(f'/notes/vehicle/{sample_vehicle.id}')
    assert response.status_code == 200
    assert b'Vehicle Note' in response.data
    assert b'Details' in response.data


def test_notes_pinned_sorting(auth_client, sample_vehicle, test_user):
    """Pinned notes appear before unpinned notes."""
    from app import db
    unpinned = VehicleNote(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='Unpinned',
        content='',
        is_pinned=False,
    )
    pinned = VehicleNote(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        title='Pinned',
        content='',
        is_pinned=True,
    )
    db.session.add_all([unpinned, pinned])
    db.session.commit()

    response = auth_client.get('/notes/')
    data = response.data.decode('utf-8')
    pinned_pos = data.find('Pinned')
    unpinned_pos = data.find('Unpinned')
    assert pinned_pos != -1
    assert unpinned_pos != -1
    assert pinned_pos < unpinned_pos
