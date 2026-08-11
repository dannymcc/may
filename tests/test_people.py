"""Tests for People — the inner-circle entity and its tasks."""
import pytest
from datetime import date, datetime, timedelta

from app import db
from app.models import (
    User, Person, PersonTask, Reminder, CalendarEvent,
    RELATIONSHIP_TYPES, PERSON_TASK_STATUSES, PERSON_TASK_PRIORITIES
)
from app.routes.people import apply_task_status


@pytest.fixture(scope='function')
def sample_person(app, test_user):
    """Create a sample person owned by test_user."""
    person = Person(
        owner_id=test_user.id,
        name='Ada Coworker',
        relationship_type='coworker',
        email='ada@example.com',
        phone='07700900123',
        organization='Analytical Engines Ltd',
        role_title='Lead Engineer',
    )
    db.session.add(person)
    db.session.commit()
    return person


@pytest.fixture(scope='function')
def sample_task(app, test_user, sample_person):
    """Create a sample outstanding task for sample_person."""
    task = PersonTask(
        person_id=sample_person.id,
        user_id=test_user.id,
        title='Review the ledger',
        description='Cross-check the quarterly figures.',
        status='todo',
        priority='high',
        due_date=date.today() + timedelta(days=30),
    )
    db.session.add(task)
    db.session.commit()
    return task


@pytest.fixture(scope='function')
def other_user(app):
    """A second regular (non-admin) user, for access-control checks."""
    user = User(
        username='otheruser',
        email='other@example.com',
    )
    user.set_password('OtherPass123!')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def other_client(app, other_user):
    """A test client logged in as other_user."""
    other = app.test_client()
    other.post('/auth/login', data={
        'username': 'otheruser',
        'password': 'OtherPass123!',
    }, follow_redirects=True)
    return other


@pytest.fixture(scope='function')
def other_person(app, other_user):
    """A person owned by other_user and not shared with the instance."""
    person = Person(
        owner_id=other_user.id,
        name='Grace Outsider',
        relationship_type='client',
        organization='Elsewhere Inc',
    )
    db.session.add(person)
    db.session.commit()
    return person


@pytest.fixture(scope='function')
def feed_token(test_user):
    """An API key for test_user, usable as a calendar feed token."""
    api_key = test_user.generate_api_key()
    db.session.commit()
    return api_key


# ---------------------------------------------------------------------------
# Person model
# ---------------------------------------------------------------------------

class TestPersonModel:
    def test_create_person_applies_defaults(self, app, test_user):
        person = Person(owner_id=test_user.id, name='Minimal Person')
        db.session.add(person)
        db.session.commit()

        assert person.id is not None
        assert person.relationship_type == 'coworker'
        assert person.is_active is True
        assert person.is_shared is False
        assert person.created_at is not None
        assert person.updated_at is not None

    def test_owner_backref(self, sample_person, test_user):
        assert sample_person.owner.id == test_user.id
        assert sample_person in test_user.owned_people.all()

    def test_display_name_with_role_and_organization(self, sample_person):
        assert sample_person.display_name == 'Ada Coworker (Lead Engineer, Analytical Engines Ltd)'

    def test_display_name_with_organization_only(self, app, test_user):
        person = Person(owner_id=test_user.id, name='Solo', organization='Acme')
        db.session.add(person)
        db.session.commit()
        assert person.display_name == 'Solo (Acme)'

    def test_display_name_with_role_only(self, app, test_user):
        person = Person(owner_id=test_user.id, name='Solo', role_title='Nurse')
        db.session.add(person)
        db.session.commit()
        assert person.display_name == 'Solo (Nurse)'

    def test_display_name_falls_back_to_name(self, app, test_user):
        person = Person(owner_id=test_user.id, name='Just A Name')
        db.session.add(person)
        db.session.commit()
        assert person.display_name == 'Just A Name'

    def test_relationship_type_label(self, app, sample_person):
        # Rendering a lazy_gettext string needs a request context: get_locale()
        # reads current_user, which is None outside one.
        with app.test_request_context():
            assert str(sample_person.relationship_type_label) == 'Coworker'

    def test_relationship_type_label_unknown_value(self, app, test_user):
        person = Person(owner_id=test_user.id, name='Odd', relationship_type='side_kick')
        db.session.add(person)
        db.session.commit()
        assert str(person.relationship_type_label) == 'Side Kick'

    def test_to_dict_contains_all_fields(self, sample_person):
        data = sample_person.to_dict()
        expected_keys = {
            'id', 'name', 'relationship_type', 'email', 'phone', 'organization',
            'role_title', 'notes', 'image_filename', 'is_active', 'is_shared',
            'vehicles', 'created_at', 'updated_at',
        }
        assert expected_keys == set(data.keys())

    def test_to_dict_vehicles_empty_without_viewer(self, sample_person):
        # Vehicle links are viewer-scoped; with no viewer nothing is exposed
        assert sample_person.to_dict()['vehicles'] == []

    def test_to_dict_values(self, sample_person):
        data = sample_person.to_dict()
        assert data['id'] == sample_person.id
        assert data['name'] == 'Ada Coworker'
        assert data['relationship_type'] == 'coworker'
        assert data['email'] == 'ada@example.com'
        assert data['organization'] == 'Analytical Engines Ltd'
        assert data['role_title'] == 'Lead Engineer'
        assert data['is_active'] is True
        assert data['is_shared'] is False
        # Timestamps are serialized as ISO-8601 strings
        assert datetime.fromisoformat(data['created_at']) == sample_person.created_at

    def test_delete_person_cascades_tasks(self, app, sample_person, sample_task):
        task_id = sample_task.id
        db.session.delete(sample_person)
        db.session.commit()
        assert PersonTask.query.get(task_id) is None

    def test_delete_person_cascades_reminders(self, app, test_user, sample_person):
        reminder = Reminder(
            person_id=sample_person.id,
            user_id=test_user.id,
            title='One-to-one',
            reminder_type='custom',
            due_date=date.today() + timedelta(days=3),
        )
        db.session.add(reminder)
        db.session.commit()
        reminder_id = reminder.id

        db.session.delete(sample_person)
        db.session.commit()
        assert Reminder.query.get(reminder_id) is None


# ---------------------------------------------------------------------------
# User.get_all_people()
# ---------------------------------------------------------------------------

class TestGetAllPeople:
    def test_returns_owned_people(self, test_user, sample_person):
        assert sample_person in test_user.get_all_people()

    def test_empty_for_user_without_people(self, other_user):
        assert other_user.get_all_people() == []

    def test_excludes_other_users_unshared_person(self, test_user, other_person):
        assert other_person not in test_user.get_all_people()

    def test_includes_shared_person_from_another_user(self, test_user, other_person):
        other_person.is_shared = True
        db.session.commit()
        assert other_person in test_user.get_all_people()

    def test_deduplicates_own_shared_person(self, test_user, sample_person):
        sample_person.is_shared = True
        db.session.commit()
        people = test_user.get_all_people()
        assert [p.id for p in people].count(sample_person.id) == 1

    def test_sorted_by_name(self, app, test_user):
        for name in ('Zoe Last', 'Alan First', 'Mia Middle'):
            db.session.add(Person(owner_id=test_user.id, name=name))
        db.session.commit()
        names = [p.name for p in test_user.get_all_people()]
        assert names == ['Alan First', 'Mia Middle', 'Zoe Last']

    def test_includes_archived_people(self, test_user, sample_person):
        """get_all_people() is not is_active-aware; callers do the filtering."""
        sample_person.is_active = False
        db.session.commit()
        assert sample_person in test_user.get_all_people()


# ---------------------------------------------------------------------------
# PersonTask model
# ---------------------------------------------------------------------------

class TestPersonTaskModel:
    def test_create_task_applies_defaults(self, app, test_user, sample_person):
        task = PersonTask(
            person_id=sample_person.id,
            user_id=test_user.id,
            title='Minimal task',
        )
        db.session.add(task)
        db.session.commit()

        assert task.id is not None
        assert task.status == 'todo'
        assert task.priority == 'normal'
        assert task.due_date is None
        assert task.started_at is None
        assert task.completed_at is None
        assert task.created_at is not None

    def test_person_backref(self, sample_person, sample_task):
        assert sample_task.person.id == sample_person.id
        assert sample_task in sample_person.tasks.all()

    def test_user_backref(self, test_user, sample_task):
        assert sample_task.user.id == test_user.id

    def test_is_overdue_true_when_past_due(self, app, test_user, sample_person):
        task = PersonTask(
            person_id=sample_person.id, user_id=test_user.id,
            title='Late', due_date=date.today() - timedelta(days=1),
        )
        db.session.add(task)
        db.session.commit()
        assert task.is_overdue() is True

    def test_is_overdue_false_when_due_today(self, app, test_user, sample_person):
        task = PersonTask(
            person_id=sample_person.id, user_id=test_user.id,
            title='Due today', due_date=date.today(),
        )
        db.session.add(task)
        db.session.commit()
        assert task.is_overdue() is False

    def test_is_overdue_false_without_due_date(self, app, test_user, sample_person):
        task = PersonTask(
            person_id=sample_person.id, user_id=test_user.id, title='Undated',
        )
        db.session.add(task)
        db.session.commit()
        assert task.is_overdue() is False

    def test_is_overdue_false_when_done(self, app, test_user, sample_person):
        task = PersonTask(
            person_id=sample_person.id, user_id=test_user.id,
            title='Late but finished', status='done',
            due_date=date.today() - timedelta(days=5),
        )
        db.session.add(task)
        db.session.commit()
        assert task.is_overdue() is False

    def test_to_dict_contains_all_fields(self, sample_task):
        data = sample_task.to_dict()
        expected_keys = {
            'id', 'person_id', 'title', 'description', 'status', 'priority',
            'due_date', 'started_at', 'completed_at', 'notification_sent',
            'recurrence', 'recurrence_interval', 'is_overdue',
            'created_at', 'updated_at',
        }
        assert expected_keys == set(data.keys())

    def test_to_dict_values(self, sample_task, sample_person):
        data = sample_task.to_dict()
        assert data['person_id'] == sample_person.id
        assert data['title'] == 'Review the ledger'
        assert data['status'] == 'todo'
        assert data['priority'] == 'high'
        assert data['due_date'] == (date.today() + timedelta(days=30)).isoformat()
        assert data['is_overdue'] is False
        assert data['started_at'] is None
        assert data['completed_at'] is None


class TestApplyTaskStatus:
    """The shared helper that keeps started_at/completed_at in step with status."""

    def test_todo_leaves_timestamps_alone(self, sample_task):
        apply_task_status(sample_task, 'todo')
        assert sample_task.status == 'todo'
        assert sample_task.started_at is None
        assert sample_task.completed_at is None

    def test_in_progress_sets_started_at(self, sample_task):
        apply_task_status(sample_task, 'in_progress')
        assert sample_task.status == 'in_progress'
        assert sample_task.started_at is not None
        assert sample_task.completed_at is None

    def test_done_sets_both_timestamps(self, sample_task):
        apply_task_status(sample_task, 'done')
        assert sample_task.status == 'done'
        assert sample_task.started_at is not None
        assert sample_task.completed_at is not None
        assert sample_task.completed_at >= sample_task.started_at

    def test_started_at_is_not_overwritten(self, sample_task):
        original = datetime(2020, 1, 1, 12, 0, 0)
        sample_task.started_at = original
        apply_task_status(sample_task, 'done')
        assert sample_task.started_at == original

    def test_reopening_clears_completed_at_but_keeps_started_at(self, sample_task):
        apply_task_status(sample_task, 'done')
        started = sample_task.started_at
        apply_task_status(sample_task, 'in_progress')
        assert sample_task.completed_at is None
        assert sample_task.started_at == started

    def test_blocked_clears_completed_at(self, sample_task):
        apply_task_status(sample_task, 'done')
        apply_task_status(sample_task, 'blocked')
        assert sample_task.status == 'blocked'
        assert sample_task.completed_at is None


# ---------------------------------------------------------------------------
# Web routes — people
# ---------------------------------------------------------------------------

class TestPeopleIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/people/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/people/')
        assert resp.status_code == 200

    def test_index_shows_people(self, auth_client, sample_person):
        resp = auth_client.get('/people/')
        assert resp.status_code == 200
        assert b'Ada Coworker' in resp.data

    def test_index_hides_archived_by_default(self, auth_client, sample_person):
        sample_person.is_active = False
        db.session.commit()
        resp = auth_client.get('/people/')
        assert resp.status_code == 200
        assert b'Ada Coworker' not in resp.data

    def test_index_shows_archived_with_param(self, auth_client, sample_person):
        sample_person.is_active = False
        db.session.commit()
        resp = auth_client.get('/people/?archived=true')
        assert resp.status_code == 200
        assert b'Ada Coworker' in resp.data

    def test_index_shows_shared_badge(self, auth_client, sample_person):
        resp = auth_client.get('/people/')
        assert b'Shared' not in resp.data

        sample_person.is_shared = True
        db.session.commit()
        resp = auth_client.get('/people/')
        assert b'Shared' in resp.data

    def test_index_shows_task_summary(self, auth_client, sample_person, sample_task):
        resp = auth_client.get('/people/')
        assert resp.status_code == 200
        assert b'1 active tasks' in resp.data

    def test_index_excludes_other_users_person(self, auth_client, other_person):
        resp = auth_client.get('/people/')
        assert b'Grace Outsider' not in resp.data


class TestPeopleNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/people/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client):
        resp = auth_client.get('/people/new')
        assert resp.status_code == 200

    def test_create_person(self, auth_client, test_user):
        resp = auth_client.post('/people/new', data={
            'name': 'Bilal Client',
            'relationship_type': 'client',
            'email': 'bilal@example.com',
            'phone': '01234567890',
            'organization': 'Bright Ideas',
            'role_title': 'Director',
            'notes': 'Prefers email.',
        }, follow_redirects=True)
        assert resp.status_code == 200

        person = Person.query.filter_by(name='Bilal Client').first()
        assert person is not None
        assert person.owner_id == test_user.id
        assert person.relationship_type == 'client'
        assert person.email == 'bilal@example.com'
        assert person.organization == 'Bright Ideas'
        assert person.is_active is True
        assert person.is_shared is False

    def test_create_person_blank_optionals_stored_as_none(self, auth_client):
        resp = auth_client.post('/people/new', data={
            'name': 'Sparse Person',
            'relationship_type': 'family',
            'email': '',
            'phone': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        person = Person.query.filter_by(name='Sparse Person').first()
        assert person is not None
        assert person.email is None
        assert person.phone is None

    def test_create_person_invalid_relationship_falls_back(self, auth_client):
        resp = auth_client.post('/people/new', data={
            'name': 'Odd Relationship',
            'relationship_type': 'nemesis',
        }, follow_redirects=True)
        assert resp.status_code == 200
        person = Person.query.filter_by(name='Odd Relationship').first()
        assert person is not None
        assert person.relationship_type == 'coworker'


class TestPeopleView:
    def test_view_requires_auth(self, client, sample_person):
        resp = client.get(f'/people/{sample_person.id}', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_view_returns_200(self, auth_client, sample_person):
        resp = auth_client.get(f'/people/{sample_person.id}')
        assert resp.status_code == 200
        assert b'Ada Coworker' in resp.data

    def test_view_404_for_nonexistent(self, auth_client):
        resp = auth_client.get('/people/99999')
        assert resp.status_code == 404

    def test_view_shows_tasks(self, auth_client, sample_person, sample_task):
        resp = auth_client.get(f'/people/{sample_person.id}')
        assert resp.status_code == 200
        assert b'Review the ledger' in resp.data

    def test_view_shows_person_reminders(self, auth_client, test_user, sample_person):
        reminder = Reminder(
            person_id=sample_person.id,
            user_id=test_user.id,
            title='Performance review',
            reminder_type='custom',
            due_date=date.today() + timedelta(days=5),
            is_completed=False,
        )
        db.session.add(reminder)
        db.session.commit()

        resp = auth_client.get(f'/people/{sample_person.id}')
        assert resp.status_code == 200
        assert b'Performance review' in resp.data

    def test_view_shows_person_calendar_events(self, auth_client, test_user, sample_person):
        event = CalendarEvent(
            user_id=test_user.id,
            person_id=sample_person.id,
            title='Quarterly catch-up',
            start_at=datetime.combine(date.today() + timedelta(days=2), datetime.min.time()),
        )
        db.session.add(event)
        db.session.commit()

        resp = auth_client.get(f'/people/{sample_person.id}')
        assert resp.status_code == 200
        assert b'Quarterly catch-up' in resp.data

    def test_view_other_users_person_denied(self, other_client, sample_person):
        resp = other_client.get(f'/people/{sample_person.id}', follow_redirects=False)
        assert resp.status_code == 302
        assert '/people/' in resp.headers['Location']

    def test_view_other_users_person_flashes_access_denied(self, other_client, sample_person):
        resp = other_client.get(f'/people/{sample_person.id}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Access denied' in resp.data
        assert b'Ada Coworker' not in resp.data

    def test_view_shared_person_allowed_for_other_user(self, other_client, sample_person):
        sample_person.is_shared = True
        db.session.commit()
        resp = other_client.get(f'/people/{sample_person.id}')
        assert resp.status_code == 200
        assert b'Ada Coworker' in resp.data


class TestPeopleEdit:
    def test_edit_requires_auth(self, client, sample_person):
        resp = client.get(f'/people/{sample_person.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_person):
        resp = auth_client.get(f'/people/{sample_person.id}/edit')
        assert resp.status_code == 200
        assert b'Ada Coworker' in resp.data

    def test_edit_person(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/edit', data={
            'name': 'Ada Lovelace',
            'relationship_type': 'family',
            'email': 'ada@home.example.com',
            'organization': 'Home',
            'role_title': 'Sister',
            'notes': 'Updated notes.',
            'is_active': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.refresh(sample_person)
        assert sample_person.name == 'Ada Lovelace'
        assert sample_person.relationship_type == 'family'
        assert sample_person.email == 'ada@home.example.com'
        assert sample_person.notes == 'Updated notes.'

    def test_edit_sets_is_shared(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/edit', data={
            'name': sample_person.name,
            'relationship_type': sample_person.relationship_type,
            'is_active': 'on',
            'is_shared': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_person)
        assert sample_person.is_shared is True

    def test_edit_clears_is_shared_and_is_active(self, auth_client, sample_person):
        sample_person.is_shared = True
        db.session.commit()

        resp = auth_client.post(f'/people/{sample_person.id}/edit', data={
            'name': sample_person.name,
            'relationship_type': sample_person.relationship_type,
            # is_active / is_shared omitted → checkboxes unchecked
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_person)
        assert sample_person.is_shared is False
        assert sample_person.is_active is False

    def test_edit_ignores_invalid_relationship_type(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/edit', data={
            'name': sample_person.name,
            'relationship_type': 'nemesis',
            'is_active': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_person)
        assert sample_person.relationship_type == 'coworker'

    def test_edit_other_users_person_denied(self, other_client, sample_person):
        resp = other_client.post(f'/people/{sample_person.id}/edit', data={
            'name': 'Hacked',
            'relationship_type': 'coworker',
        }, follow_redirects=False)
        assert resp.status_code == 302
        db.session.refresh(sample_person)
        assert sample_person.name == 'Ada Coworker'

    def test_edit_shared_person_denied_for_non_owner(self, other_client, sample_person):
        """Sharing grants visibility, not the right to edit."""
        sample_person.is_shared = True
        db.session.commit()

        resp = other_client.post(f'/people/{sample_person.id}/edit', data={
            'name': 'Hacked',
            'relationship_type': 'coworker',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Access denied' in resp.data
        db.session.refresh(sample_person)
        assert sample_person.name == 'Ada Coworker'


class TestPeopleDelete:
    def test_delete_requires_auth(self, client, sample_person):
        resp = client.post(f'/people/{sample_person.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_person(self, auth_client, sample_person):
        person_id = sample_person.id
        resp = auth_client.post(f'/people/{person_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert Person.query.get(person_id) is None

    def test_delete_person_removes_tasks(self, auth_client, sample_person, sample_task):
        task_id = sample_task.id
        resp = auth_client.post(f'/people/{sample_person.id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert PersonTask.query.get(task_id) is None

    def test_delete_other_users_person_denied(self, other_client, sample_person):
        person_id = sample_person.id
        resp = other_client.post(f'/people/{person_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Access denied' in resp.data
        assert Person.query.get(person_id) is not None


class TestPeopleShareAndArchive:
    def test_share_person(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/share', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_person)
        assert sample_person.is_shared is True

    def test_unshare_person(self, auth_client, sample_person):
        sample_person.is_shared = True
        db.session.commit()
        resp = auth_client.post(f'/people/{sample_person.id}/unshare', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_person)
        assert sample_person.is_shared is False

    def test_archive_person(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/archive', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_person)
        assert sample_person.is_active is False

    def test_unarchive_person(self, auth_client, sample_person):
        sample_person.is_active = False
        db.session.commit()
        resp = auth_client.post(f'/people/{sample_person.id}/unarchive', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_person)
        assert sample_person.is_active is True

    def test_archive_other_users_person_denied(self, other_client, sample_person):
        resp = other_client.post(f'/people/{sample_person.id}/archive', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Access denied' in resp.data
        db.session.refresh(sample_person)
        assert sample_person.is_active is True


# ---------------------------------------------------------------------------
# Web routes — person tasks
# ---------------------------------------------------------------------------

class TestPersonTaskRoutes:
    def test_new_task_requires_auth(self, client, sample_person):
        resp = client.get(f'/people/{sample_person.id}/tasks/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_task_form_returns_200(self, auth_client, sample_person):
        resp = auth_client.get(f'/people/{sample_person.id}/tasks/new')
        assert resp.status_code == 200

    def test_create_task(self, auth_client, test_user, sample_person):
        due = date.today() + timedelta(days=7)
        resp = auth_client.post(f'/people/{sample_person.id}/tasks/new', data={
            'title': 'Send the contract',
            'description': 'Countersigned copy.',
            'status': 'todo',
            'priority': 'urgent',
            'due_date': due.isoformat(),
        }, follow_redirects=True)
        assert resp.status_code == 200

        task = PersonTask.query.filter_by(title='Send the contract').first()
        assert task is not None
        assert task.person_id == sample_person.id
        assert task.user_id == test_user.id
        assert task.priority == 'urgent'
        assert task.due_date == due
        assert task.started_at is None
        assert task.completed_at is None

    def test_create_task_without_due_date(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/tasks/new', data={
            'title': 'Someday task',
            'due_date': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        task = PersonTask.query.filter_by(title='Someday task').first()
        assert task is not None
        assert task.due_date is None

    def test_create_task_in_progress_sets_started_at(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/tasks/new', data={
            'title': 'Already underway',
            'status': 'in_progress',
        }, follow_redirects=True)
        assert resp.status_code == 200
        task = PersonTask.query.filter_by(title='Already underway').first()
        assert task is not None
        assert task.started_at is not None
        assert task.completed_at is None

    def test_create_task_requires_title(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/tasks/new', data={
            'title': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Please enter a task title' in resp.data
        assert sample_person.tasks.count() == 0

    def test_create_task_invalid_due_date_rejected(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/tasks/new', data={
            'title': 'Bad date',
            'due_date': 'not-a-date',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert PersonTask.query.filter_by(title='Bad date').first() is None

    def test_create_task_invalid_status_falls_back(self, auth_client, sample_person):
        resp = auth_client.post(f'/people/{sample_person.id}/tasks/new', data={
            'title': 'Odd status',
            'status': 'procrastinating',
            'priority': 'whenever',
        }, follow_redirects=True)
        assert resp.status_code == 200
        task = PersonTask.query.filter_by(title='Odd status').first()
        assert task is not None
        assert task.status == 'todo'
        assert task.priority == 'normal'

    def test_create_task_denied_for_other_user(self, other_client, sample_person):
        resp = other_client.post(f'/people/{sample_person.id}/tasks/new', data={
            'title': 'Sneaky task',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Access denied' in resp.data
        assert PersonTask.query.filter_by(title='Sneaky task').first() is None

    def test_get_edit_task_form_returns_200(self, auth_client, sample_person, sample_task):
        resp = auth_client.get(f'/people/{sample_person.id}/tasks/{sample_task.id}/edit')
        assert resp.status_code == 200
        assert b'Review the ledger' in resp.data

    def test_edit_task(self, auth_client, sample_person, sample_task):
        due = date.today() + timedelta(days=14)
        resp = auth_client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/edit',
            data={
                'title': 'Review the ledger carefully',
                'description': 'And the petty cash.',
                'status': 'blocked',
                'priority': 'low',
                'due_date': due.isoformat(),
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        db.session.refresh(sample_task)
        assert sample_task.title == 'Review the ledger carefully'
        assert sample_task.description == 'And the petty cash.'
        assert sample_task.status == 'blocked'
        assert sample_task.priority == 'low'
        assert sample_task.due_date == due

    def test_edit_task_requires_title(self, auth_client, sample_person, sample_task):
        resp = auth_client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/edit',
            data={'title': ''},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Please enter a task title' in resp.data
        db.session.refresh(sample_task)
        assert sample_task.title == 'Review the ledger'

    def test_edit_task_to_done_sets_timestamps(self, auth_client, sample_person, sample_task):
        resp = auth_client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/edit',
            data={'title': sample_task.title, 'status': 'done'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(sample_task)
        assert sample_task.status == 'done'
        assert sample_task.started_at is not None
        assert sample_task.completed_at is not None

    def test_edit_task_belonging_to_another_person(self, auth_client, test_user, sample_person, sample_task):
        stranger = Person(owner_id=test_user.id, name='Unrelated Person')
        db.session.add(stranger)
        db.session.commit()

        resp = auth_client.post(
            f'/people/{stranger.id}/tasks/{sample_task.id}/edit',
            data={'title': 'Moved'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Task not found' in resp.data
        db.session.refresh(sample_task)
        assert sample_task.title == 'Review the ledger'

    def test_task_status_to_in_progress(self, auth_client, sample_person, sample_task):
        resp = auth_client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/status',
            data={'status': 'in_progress'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(sample_task)
        assert sample_task.status == 'in_progress'
        assert sample_task.started_at is not None
        assert sample_task.completed_at is None

    def test_task_status_to_done(self, auth_client, sample_person, sample_task):
        resp = auth_client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/status',
            data={'status': 'done'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(sample_task)
        assert sample_task.status == 'done'
        assert sample_task.started_at is not None
        assert sample_task.completed_at is not None

    def test_task_status_reopen_clears_completed_at(self, auth_client, sample_person, sample_task):
        auth_client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/status',
            data={'status': 'done'}, follow_redirects=True,
        )
        db.session.refresh(sample_task)
        started = sample_task.started_at

        resp = auth_client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/status',
            data={'status': 'todo'}, follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(sample_task)
        assert sample_task.status == 'todo'
        assert sample_task.completed_at is None
        assert sample_task.started_at == started

    def test_task_status_rejects_invalid_status(self, auth_client, sample_person, sample_task):
        resp = auth_client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/status',
            data={'status': 'napping'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Invalid status' in resp.data
        db.session.refresh(sample_task)
        assert sample_task.status == 'todo'

    def test_delete_task(self, auth_client, sample_person, sample_task):
        task_id = sample_task.id
        resp = auth_client.post(
            f'/people/{sample_person.id}/tasks/{task_id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert PersonTask.query.get(task_id) is None

    def test_delete_task_requires_auth(self, client, sample_person, sample_task):
        resp = client.post(
            f'/people/{sample_person.id}/tasks/{sample_task.id}/delete',
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_task_denied_for_other_user(self, other_client, sample_person, sample_task):
        task_id = sample_task.id
        resp = other_client.post(
            f'/people/{sample_person.id}/tasks/{task_id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Access denied' in resp.data
        assert PersonTask.query.get(task_id) is not None


# ---------------------------------------------------------------------------
# REST API v1 — people
# ---------------------------------------------------------------------------

class TestApiPeopleAuth:
    def test_list_people_without_key_returns_401(self, client):
        resp = client.get('/api/v1/people')
        assert resp.status_code == 401
        assert resp.get_json()['code'] == 'missing_api_key'

    def test_list_people_invalid_key_returns_401(self, client):
        resp = client.get('/api/v1/people', headers={'X-API-Key': 'nope'})
        assert resp.status_code == 401
        assert resp.get_json()['code'] == 'invalid_api_key'

    def test_person_detail_without_key_returns_401(self, client, sample_person):
        resp = client.get(f'/api/v1/people/{sample_person.id}')
        assert resp.status_code == 401

    def test_tasks_without_key_returns_401(self, client, sample_person):
        resp = client.get(f'/api/v1/people/{sample_person.id}/tasks')
        assert resp.status_code == 401

    def test_all_tasks_without_key_returns_401(self, client):
        resp = client.get('/api/v1/tasks')
        assert resp.status_code == 401

    def test_metadata_without_key_returns_401(self, client):
        resp = client.get('/api/v1/people/metadata')
        assert resp.status_code == 401


class TestApiPeopleMetadata:
    def test_metadata_lists_choices(self, client, api_headers):
        resp = client.get('/api/v1/people/metadata', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert [item['id'] for item in data['relationship_types']] == [
            value for value, _label in RELATIONSHIP_TYPES
        ]
        assert [item['id'] for item in data['task_statuses']] == [
            value for value, _label in PERSON_TASK_STATUSES
        ]
        assert [item['id'] for item in data['task_priorities']] == [
            value for value, _label in PERSON_TASK_PRIORITIES
        ]


class TestApiPeopleList:
    def test_list_people_empty(self, client, api_headers):
        resp = client.get('/api/v1/people', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 0
        assert data['people'] == []

    def test_list_people(self, client, api_headers, sample_person):
        resp = client.get('/api/v1/people', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1
        assert data['people'][0]['name'] == 'Ada Coworker'

    def test_list_people_excludes_archived_by_default(self, client, api_headers, sample_person):
        sample_person.is_active = False
        db.session.commit()
        resp = client.get('/api/v1/people', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['count'] == 0

    def test_list_people_include_archived(self, client, api_headers, sample_person):
        sample_person.is_active = False
        db.session.commit()
        resp = client.get('/api/v1/people?include_archived=true', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['count'] == 1

    def test_list_people_relationship_type_filter(self, client, api_headers, test_user, sample_person):
        db.session.add(Person(owner_id=test_user.id, name='Cleo Client', relationship_type='client'))
        db.session.commit()

        resp = client.get('/api/v1/people?relationship_type=client', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1
        assert data['people'][0]['name'] == 'Cleo Client'

    def test_list_people_invalid_relationship_type(self, client, api_headers):
        resp = client.get('/api/v1/people?relationship_type=nemesis', headers=api_headers)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'validation_error'

    def test_list_people_excludes_other_users_person(self, client, api_headers, other_person):
        resp = client.get('/api/v1/people', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['count'] == 0

    def test_list_people_includes_shared_person(self, client, api_headers, other_person):
        other_person.is_shared = True
        db.session.commit()
        resp = client.get('/api/v1/people', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1
        assert data['people'][0]['name'] == 'Grace Outsider'


class TestApiPeopleCrud:
    def test_create_person(self, client, api_headers, test_user):
        resp = client.post('/api/v1/people', json={
            'name': 'Nadia Dependent',
            'relationship_type': 'dependent',
            'email': 'nadia@example.com',
            'organization': 'School',
        }, headers=api_headers)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['name'] == 'Nadia Dependent'
        assert data['relationship_type'] == 'dependent'
        assert 'id' in data

        person = Person.query.get(data['id'])
        assert person.owner_id == test_user.id

    def test_create_person_defaults_to_coworker(self, client, api_headers):
        resp = client.post('/api/v1/people', json={'name': 'Default Type'},
                           headers=api_headers)
        assert resp.status_code == 201
        assert resp.get_json()['relationship_type'] == 'coworker'

    def test_create_person_missing_name(self, client, api_headers):
        resp = client.post('/api/v1/people', json={'relationship_type': 'client'},
                           headers=api_headers)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'validation_error'

    def test_create_person_invalid_relationship_type(self, client, api_headers):
        resp = client.post('/api/v1/people',
                           json={'name': 'Bad', 'relationship_type': 'nemesis'},
                           headers=api_headers)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'validation_error'

    def test_create_person_no_body(self, client, api_headers):
        resp = client.post('/api/v1/people', headers=api_headers)
        assert resp.status_code in (400, 415)

    def test_get_person(self, client, api_headers, sample_person):
        resp = client.get(f'/api/v1/people/{sample_person.id}', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['id'] == sample_person.id
        assert data['name'] == 'Ada Coworker'

    def test_get_person_not_found(self, client, api_headers):
        resp = client.get('/api/v1/people/99999', headers=api_headers)
        assert resp.status_code == 404
        assert resp.get_json()['code'] == 'not_found'

    def test_get_person_other_user_returns_404(self, client, api_headers, other_person):
        resp = client.get(f'/api/v1/people/{other_person.id}', headers=api_headers)
        assert resp.status_code == 404

    def test_put_person_replaces_unsent_fields(self, client, api_headers, sample_person):
        sample_person.is_shared = True
        db.session.commit()

        resp = client.put(f'/api/v1/people/{sample_person.id}',
                          json={'name': 'Ada Only'}, headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'Ada Only'
        assert data['relationship_type'] == 'coworker'
        assert data['email'] is None
        assert data['organization'] is None
        assert data['role_title'] is None
        assert data['is_active'] is True
        assert data['is_shared'] is False

    def test_patch_person_only_changes_sent_fields(self, client, api_headers, sample_person):
        resp = client.patch(f'/api/v1/people/{sample_person.id}',
                            json={'organization': 'New Engines Ltd'},
                            headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['organization'] == 'New Engines Ltd'
        assert data['name'] == 'Ada Coworker'
        assert data['email'] == 'ada@example.com'
        assert data['role_title'] == 'Lead Engineer'

    def test_patch_person_invalid_relationship_type(self, client, api_headers, sample_person):
        resp = client.patch(f'/api/v1/people/{sample_person.id}',
                            json={'relationship_type': 'nemesis'},
                            headers=api_headers)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'validation_error'

    def test_update_person_no_body(self, client, api_headers, sample_person):
        resp = client.put(f'/api/v1/people/{sample_person.id}', headers=api_headers)
        assert resp.status_code in (400, 415)

    def test_update_person_other_user_returns_404(self, client, api_headers, other_person):
        resp = client.patch(f'/api/v1/people/{other_person.id}',
                            json={'name': 'Hacked'}, headers=api_headers)
        assert resp.status_code == 404
        db.session.refresh(other_person)
        assert other_person.name == 'Grace Outsider'

    def test_update_shared_person_not_owner_returns_403(self, client, api_headers, other_person):
        other_person.is_shared = True
        db.session.commit()

        resp = client.patch(f'/api/v1/people/{other_person.id}',
                            json={'name': 'Hacked'}, headers=api_headers)
        assert resp.status_code == 403
        assert resp.get_json()['code'] == 'forbidden'

    def test_delete_person(self, client, api_headers, sample_person):
        person_id = sample_person.id
        resp = client.delete(f'/api/v1/people/{person_id}', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert Person.query.get(person_id) is None

    def test_delete_person_not_found(self, client, api_headers):
        resp = client.delete('/api/v1/people/99999', headers=api_headers)
        assert resp.status_code == 404

    def test_delete_person_other_user_returns_404(self, client, api_headers, other_person):
        person_id = other_person.id
        resp = client.delete(f'/api/v1/people/{person_id}', headers=api_headers)
        assert resp.status_code == 404
        assert Person.query.get(person_id) is not None

    def test_delete_shared_person_not_owner_returns_403(self, client, api_headers, other_person):
        other_person.is_shared = True
        db.session.commit()
        person_id = other_person.id

        resp = client.delete(f'/api/v1/people/{person_id}', headers=api_headers)
        assert resp.status_code == 403
        assert Person.query.get(person_id) is not None


# ---------------------------------------------------------------------------
# REST API v1 — person tasks
# ---------------------------------------------------------------------------

class TestApiPersonTasks:
    def test_list_tasks_empty(self, client, api_headers, sample_person):
        resp = client.get(f'/api/v1/people/{sample_person.id}/tasks', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['tasks'] == []
        assert data['total'] == 0

    def test_list_tasks(self, client, api_headers, sample_person, sample_task):
        resp = client.get(f'/api/v1/people/{sample_person.id}/tasks', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1
        assert data['count'] == 1
        assert data['tasks'][0]['title'] == 'Review the ledger'

    def test_list_tasks_status_filter(self, client, api_headers, test_user, sample_person, sample_task):
        db.session.add(PersonTask(
            person_id=sample_person.id, user_id=test_user.id,
            title='Finished thing', status='done',
        ))
        db.session.commit()

        resp = client.get(f'/api/v1/people/{sample_person.id}/tasks?status=done',
                          headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1
        assert data['tasks'][0]['title'] == 'Finished thing'

    def test_list_tasks_invalid_status(self, client, api_headers, sample_person):
        resp = client.get(f'/api/v1/people/{sample_person.id}/tasks?status=napping',
                          headers=api_headers)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'validation_error'

    def test_list_tasks_person_not_found(self, client, api_headers):
        resp = client.get('/api/v1/people/99999/tasks', headers=api_headers)
        assert resp.status_code == 404

    def test_list_tasks_other_users_person_returns_404(self, client, api_headers, other_person):
        resp = client.get(f'/api/v1/people/{other_person.id}/tasks', headers=api_headers)
        assert resp.status_code == 404

    def test_create_task(self, client, api_headers, test_user, sample_person):
        due = date.today() + timedelta(days=3)
        resp = client.post(f'/api/v1/people/{sample_person.id}/tasks', json={
            'title': 'Draft the proposal',
            'description': 'Two pages, no more.',
            'priority': 'high',
            'due_date': due.isoformat(),
        }, headers=api_headers)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['title'] == 'Draft the proposal'
        assert data['person_id'] == sample_person.id
        assert data['status'] == 'todo'
        assert data['priority'] == 'high'
        assert data['due_date'] == due.isoformat()

        task = PersonTask.query.get(data['id'])
        assert task.user_id == test_user.id

    def test_create_task_missing_title(self, client, api_headers, sample_person):
        resp = client.post(f'/api/v1/people/{sample_person.id}/tasks',
                           json={'priority': 'high'}, headers=api_headers)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'validation_error'

    def test_create_task_invalid_status(self, client, api_headers, sample_person):
        resp = client.post(f'/api/v1/people/{sample_person.id}/tasks',
                           json={'title': 'Bad', 'status': 'napping'},
                           headers=api_headers)
        assert resp.status_code == 400

    def test_create_task_invalid_priority(self, client, api_headers, sample_person):
        resp = client.post(f'/api/v1/people/{sample_person.id}/tasks',
                           json={'title': 'Bad', 'priority': 'whenever'},
                           headers=api_headers)
        assert resp.status_code == 400

    def test_create_task_invalid_due_date(self, client, api_headers, sample_person):
        resp = client.post(f'/api/v1/people/{sample_person.id}/tasks',
                           json={'title': 'Bad', 'due_date': 'not-a-date'},
                           headers=api_headers)
        assert resp.status_code == 400

    def test_create_task_no_body(self, client, api_headers, sample_person):
        resp = client.post(f'/api/v1/people/{sample_person.id}/tasks', headers=api_headers)
        assert resp.status_code in (400, 415)

    def test_create_task_person_not_found(self, client, api_headers):
        resp = client.post('/api/v1/people/99999/tasks', json={'title': 'Orphan'},
                           headers=api_headers)
        assert resp.status_code == 404

    def test_create_task_done_sets_completed_at(self, client, api_headers, sample_person):
        resp = client.post(f'/api/v1/people/{sample_person.id}/tasks',
                           json={'title': 'Already done', 'status': 'done'},
                           headers=api_headers)
        assert resp.status_code == 201
        assert resp.get_json()['completed_at'] is not None

    def test_get_task(self, client, api_headers, sample_person, sample_task):
        resp = client.get(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                          headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['id'] == sample_task.id
        assert data['title'] == 'Review the ledger'

    def test_get_task_not_found(self, client, api_headers, sample_person):
        resp = client.get(f'/api/v1/people/{sample_person.id}/tasks/99999',
                          headers=api_headers)
        assert resp.status_code == 404

    def test_get_task_under_wrong_person_returns_404(self, client, api_headers, test_user,
                                                     sample_person, sample_task):
        stranger = Person(owner_id=test_user.id, name='Unrelated Person')
        db.session.add(stranger)
        db.session.commit()

        resp = client.get(f'/api/v1/people/{stranger.id}/tasks/{sample_task.id}',
                          headers=api_headers)
        assert resp.status_code == 404

    def test_put_task_replaces_unsent_fields(self, client, api_headers, sample_person, sample_task):
        resp = client.put(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                          json={'title': 'Just the title'}, headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['title'] == 'Just the title'
        assert data['description'] is None
        assert data['status'] == 'todo'
        assert data['priority'] == 'normal'
        assert data['due_date'] is None

    def test_patch_task_only_changes_sent_fields(self, client, api_headers, sample_person, sample_task):
        resp = client.patch(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                            json={'priority': 'low'}, headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['priority'] == 'low'
        assert data['title'] == 'Review the ledger'
        assert data['due_date'] == (date.today() + timedelta(days=30)).isoformat()

    def test_patch_task_in_progress_sets_started_at(self, client, api_headers, sample_person, sample_task):
        resp = client.patch(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                            json={'status': 'in_progress'}, headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'in_progress'
        assert data['started_at'] is not None
        assert data['completed_at'] is None

    def test_patch_task_done_sets_completed_at(self, client, api_headers, sample_person, sample_task):
        resp = client.patch(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                            json={'status': 'done'}, headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'done'
        assert data['completed_at'] is not None
        # Matches apply_task_status() on the web side: a task never finishes
        # before it began, whichever surface performed the transition.
        assert data['started_at'] is not None

    def test_patch_task_reopen_clears_completed_at(self, client, api_headers, sample_person, sample_task):
        client.patch(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                     json={'status': 'done'}, headers=api_headers)
        resp = client.patch(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                            json={'status': 'todo'}, headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['completed_at'] is None

    def test_patch_task_invalid_status(self, client, api_headers, sample_person, sample_task):
        resp = client.patch(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                            json={'status': 'napping'}, headers=api_headers)
        assert resp.status_code == 400

    def test_update_task_no_body(self, client, api_headers, sample_person, sample_task):
        resp = client.put(f'/api/v1/people/{sample_person.id}/tasks/{sample_task.id}',
                          headers=api_headers)
        assert resp.status_code in (400, 415)

    def test_delete_task(self, client, api_headers, sample_person, sample_task):
        task_id = sample_task.id
        resp = client.delete(f'/api/v1/people/{sample_person.id}/tasks/{task_id}',
                             headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert PersonTask.query.get(task_id) is None

    def test_delete_task_not_found(self, client, api_headers, sample_person):
        resp = client.delete(f'/api/v1/people/{sample_person.id}/tasks/99999',
                             headers=api_headers)
        assert resp.status_code == 404


class TestApiAllTasks:
    def test_list_all_tasks_empty(self, client, api_headers):
        resp = client.get('/api/v1/tasks', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['tasks'] == []
        assert data['total'] == 0
        assert data['limit'] == 100
        assert data['offset'] == 0

    def test_list_all_tasks_spans_the_whole_circle(self, client, api_headers, test_user,
                                                  sample_person, sample_task):
        second = Person(owner_id=test_user.id, name='Bo Second')
        db.session.add(second)
        db.session.flush()
        db.session.add(PersonTask(
            person_id=second.id, user_id=test_user.id,
            title='Book the venue', due_date=date.today() + timedelta(days=1),
        ))
        db.session.commit()

        resp = client.get('/api/v1/tasks', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 2
        titles = [task['title'] for task in data['tasks']]
        assert set(titles) == {'Review the ledger', 'Book the venue'}
        # The soonest due date comes first
        assert titles[0] == 'Book the venue'

    def test_list_all_tasks_includes_person_name(self, client, api_headers, sample_person, sample_task):
        resp = client.get('/api/v1/tasks', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['tasks'][0]['person_name'] == 'Ada Coworker'

    def test_list_all_tasks_status_filter(self, client, api_headers, test_user,
                                          sample_person, sample_task):
        db.session.add(PersonTask(
            person_id=sample_person.id, user_id=test_user.id,
            title='Shipped it', status='done',
        ))
        db.session.commit()

        resp = client.get('/api/v1/tasks?status=done', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 1
        assert data['tasks'][0]['title'] == 'Shipped it'

        resp = client.get('/api/v1/tasks?status=todo', headers=api_headers)
        data = resp.get_json()
        assert data['total'] == 1
        assert data['tasks'][0]['title'] == 'Review the ledger'

    def test_list_all_tasks_invalid_status(self, client, api_headers):
        resp = client.get('/api/v1/tasks?status=napping', headers=api_headers)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'validation_error'

    def test_list_all_tasks_priority_filter(self, client, api_headers, sample_person, sample_task):
        resp = client.get('/api/v1/tasks?priority=high', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['total'] == 1

        resp = client.get('/api/v1/tasks?priority=low', headers=api_headers)
        assert resp.get_json()['total'] == 0

    def test_list_all_tasks_due_before_filter(self, client, api_headers, sample_person, sample_task):
        cutoff = date.today() + timedelta(days=1)
        resp = client.get(f'/api/v1/tasks?due_before={cutoff.isoformat()}', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['total'] == 0

        cutoff = date.today() + timedelta(days=60)
        resp = client.get(f'/api/v1/tasks?due_before={cutoff.isoformat()}', headers=api_headers)
        assert resp.get_json()['total'] == 1

    def test_list_all_tasks_person_id_filter(self, client, api_headers, sample_person, sample_task):
        resp = client.get(f'/api/v1/tasks?person_id={sample_person.id}', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['total'] == 1

    def test_list_all_tasks_person_id_other_user_returns_404(self, client, api_headers, other_person):
        resp = client.get(f'/api/v1/tasks?person_id={other_person.id}', headers=api_headers)
        assert resp.status_code == 404

    def test_list_all_tasks_excludes_other_users_tasks(self, client, api_headers,
                                                       other_user, other_person):
        db.session.add(PersonTask(
            person_id=other_person.id, user_id=other_user.id,
            title='Not your business',
        ))
        db.session.commit()

        resp = client.get('/api/v1/tasks', headers=api_headers)
        assert resp.status_code == 200
        assert resp.get_json()['total'] == 0

    def test_list_all_tasks_limit_and_offset(self, client, api_headers, test_user, sample_person):
        for offset_days in range(3):
            db.session.add(PersonTask(
                person_id=sample_person.id, user_id=test_user.id,
                title=f'Task {offset_days}',
                due_date=date.today() + timedelta(days=offset_days + 1),
            ))
        db.session.commit()

        resp = client.get('/api/v1/tasks?limit=2', headers=api_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total'] == 3
        assert data['count'] == 2
        assert data['limit'] == 2

        resp = client.get('/api/v1/tasks?limit=2&offset=2', headers=api_headers)
        data = resp.get_json()
        assert data['count'] == 1
        assert data['offset'] == 2


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------

class TestSearchPeople:
    def test_search_finds_person_by_name(self, auth_client, sample_person):
        resp = auth_client.get('/search/?q=Coworker')
        assert resp.status_code == 200
        assert b'Ada Coworker' in resp.data

    def test_search_finds_person_by_organization(self, auth_client, sample_person):
        resp = auth_client.get('/search/?q=Analytical')
        assert resp.status_code == 200
        assert b'Ada Coworker' in resp.data

    def test_search_finds_person_by_email(self, auth_client, sample_person):
        resp = auth_client.get('/search/?q=ada@example.com')
        assert resp.status_code == 200
        assert b'Ada Coworker' in resp.data

    def test_search_finds_task_by_title(self, auth_client, sample_person, sample_task):
        resp = auth_client.get('/search/?q=ledger')
        assert resp.status_code == 200
        assert b'Review the ledger' in resp.data

    def test_search_finds_task_by_description(self, auth_client, sample_person, sample_task):
        resp = auth_client.get('/search/?q=quarterly')
        assert resp.status_code == 200
        assert b'Review the ledger' in resp.data

    def test_search_excludes_other_users_person(self, auth_client, sample_person, other_person):
        resp = auth_client.get('/search/?q=Outsider')
        assert resp.status_code == 200
        assert b'Grace Outsider' not in resp.data

    def test_search_excludes_other_users_task(self, auth_client, sample_person,
                                              other_user, other_person):
        db.session.add(PersonTask(
            person_id=other_person.id, user_id=other_user.id,
            title='Secret-outsider-task',
        ))
        db.session.commit()
        resp = auth_client.get('/search/?q=Secret-outsider')
        assert resp.status_code == 200
        assert b'Secret-outsider-task' not in resp.data

    def test_search_no_match_returns_no_person(self, auth_client, sample_person):
        resp = auth_client.get('/search/?q=zzz-nothing-matches')
        assert resp.status_code == 200
        assert b'Ada Coworker' not in resp.data


# ---------------------------------------------------------------------------
# iCalendar feed
# ---------------------------------------------------------------------------

class TestCalendarFeedPeople:
    def test_feed_includes_person_reminder(self, client, test_user, feed_token, sample_person):
        reminder = Reminder(
            person_id=sample_person.id,
            user_id=test_user.id,
            title='Performance review',
            reminder_type='custom',
            due_date=date.today() + timedelta(days=9),
            is_completed=False,
        )
        db.session.add(reminder)
        db.session.commit()

        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert f'UID:remind-{reminder.id}-{test_user.id}@may-vehicle' in body
        assert 'Performance review' in body
        assert 'X-MAY-PERSON:' in body
        assert 'Ada Coworker' in body

    def test_feed_excludes_completed_person_reminder(self, client, test_user, feed_token, sample_person):
        reminder = Reminder(
            person_id=sample_person.id,
            user_id=test_user.id,
            title='Already handled',
            reminder_type='custom',
            due_date=date.today() + timedelta(days=9),
            is_completed=True,
        )
        db.session.add(reminder)
        db.session.commit()

        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        assert resp.status_code == 200
        assert f'UID:remind-{reminder.id}-' not in resp.data.decode('utf-8')

    def test_feed_includes_person_task_with_due_date(self, client, test_user, feed_token,
                                                     sample_person, sample_task):
        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert f'UID:person-task-{sample_task.id}-{test_user.id}@may-vehicle' in body
        assert 'Review the ledger' in body
        assert 'X-MAY-PERSON:' in body

    def test_feed_person_task_carries_due_date(self, client, feed_token, sample_person, sample_task):
        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        body = resp.data.decode('utf-8')
        due = date.today() + timedelta(days=30)
        assert f'DTSTART;VALUE=DATE:{due.strftime("%Y%m%d")}' in body

    def test_feed_excludes_done_person_task(self, client, test_user, feed_token, sample_person):
        task = PersonTask(
            person_id=sample_person.id, user_id=test_user.id,
            title='Finished work', status='done',
            due_date=date.today() + timedelta(days=4),
        )
        db.session.add(task)
        db.session.commit()

        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        assert f'UID:person-task-{task.id}-' not in resp.data.decode('utf-8')

    def test_feed_excludes_undated_person_task(self, client, test_user, feed_token, sample_person):
        task = PersonTask(
            person_id=sample_person.id, user_id=test_user.id, title='Someday maybe',
        )
        db.session.add(task)
        db.session.commit()

        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        assert f'UID:person-task-{task.id}-' not in resp.data.decode('utf-8')

    def test_feed_includes_person_calendar_event(self, client, test_user, feed_token, sample_person):
        event = CalendarEvent(
            user_id=test_user.id,
            person_id=sample_person.id,
            title='Quarterly catch-up',
            start_at=datetime.combine(date.today() + timedelta(days=6), datetime.min.time()),
        )
        db.session.add(event)
        db.session.commit()

        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert f'UID:event-{event.id}-{test_user.id}@may-vehicle' in body
        assert 'Quarterly catch-up' in body
        assert 'X-MAY-PERSON:Ada Coworker' in body

    def test_feed_excludes_other_users_person_task(self, client, feed_token, other_user, other_person):
        task = PersonTask(
            person_id=other_person.id, user_id=other_user.id,
            title='Not in my feed', due_date=date.today() + timedelta(days=2),
        )
        db.session.add(task)
        db.session.commit()

        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        assert resp.status_code == 200
        assert f'UID:person-task-{task.id}-' not in resp.data.decode('utf-8')

    def test_feed_still_valid_without_vehicles(self, client, feed_token, sample_person, sample_task):
        """A person-only circle still produces a well-formed calendar."""
        resp = client.get(f'/api/calendar/feed?token={feed_token}')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert body.startswith('BEGIN:VCALENDAR')
        assert body.rstrip().endswith('END:VCALENDAR')


# ---------------------------------------------------------------------------
# Menu preference
# ---------------------------------------------------------------------------

class TestShowMenuPeople:
    def test_defaults_to_true(self, test_user):
        assert test_user.show_menu_people is True

    def test_settings_page_offers_the_toggle(self, auth_client):
        resp = auth_client.get('/auth/settings')
        assert resp.status_code == 200
        assert b'show_menu_people' in resp.data

    def test_menu_preferences_enables_people(self, auth_client, test_user, app):
        test_user.show_menu_people = False
        db.session.commit()

        resp = auth_client.post('/auth/menu-preferences', data={
            'start_page': 'dashboard',
            'show_menu_people': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Menu preferences updated' in resp.data

        user = User.query.filter_by(username='testuser').first()
        assert user.show_menu_people is True

    def test_menu_preferences_disables_people(self, auth_client, test_user, app):
        resp = auth_client.post('/auth/menu-preferences', data={
            'start_page': 'dashboard',
            # show_menu_people omitted → hidden
        }, follow_redirects=True)
        assert resp.status_code == 200

        user = User.query.filter_by(username='testuser').first()
        assert user.show_menu_people is False

    def test_nav_shows_people_link_when_enabled(self, auth_client, test_user):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200
        assert b'href="/people/"' in resp.data

    def test_nav_hides_people_link_when_disabled(self, auth_client, test_user):
        test_user.show_menu_people = False
        db.session.commit()
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200
        assert b'href="/people/"' not in resp.data
