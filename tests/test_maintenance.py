import pytest
from app import db
from app.models import MaintenanceSchedule
from datetime import date


@pytest.fixture
def sample_schedule(app, test_user, sample_vehicle):
    schedule = MaintenanceSchedule(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        name='Oil Change',
        maintenance_type='oil_change',
        interval_months=6,
        estimated_cost=50.0,
        auto_remind=True,
        remind_days_before=14,
    )
    db.session.add(schedule)
    db.session.commit()
    return schedule


class TestMaintenanceIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/maintenance/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/maintenance/')
        assert resp.status_code == 200

    def test_index_shows_schedules(self, auth_client, sample_schedule):
        resp = auth_client.get('/maintenance/')
        assert resp.status_code == 200
        assert b'Oil Change' in resp.data


class TestMaintenanceNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/maintenance/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/maintenance/new')
        assert resp.status_code == 200

    def test_create_schedule(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/maintenance/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'name': 'Tire Rotation',
            'maintenance_type': 'tyre_rotation',
            'interval_months': '6',
            'estimated_cost': '30.00',
            'auto_remind': 'on',
            'remind_days_before': '14',
        }, follow_redirects=True)
        assert resp.status_code == 200
        schedule = MaintenanceSchedule.query.filter_by(name='Tire Rotation').first()
        assert schedule is not None
        assert schedule.user_id == test_user.id


class TestMaintenanceEdit:
    def test_edit_requires_auth(self, client, sample_schedule):
        resp = client.get(f'/maintenance/{sample_schedule.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_schedule):
        resp = auth_client.get(f'/maintenance/{sample_schedule.id}/edit')
        assert resp.status_code == 200

    def test_edit_schedule(self, auth_client, sample_schedule):
        resp = auth_client.post(f'/maintenance/{sample_schedule.id}/edit', data={
            'name': 'Updated Oil Change',
            'maintenance_type': 'oil_change',
            'interval_months': '12',
            'estimated_cost': '60.00',
            'remind_days_before': '7',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_schedule)
        assert sample_schedule.name == 'Updated Oil Change'
        assert sample_schedule.interval_months == 12


class TestMaintenanceDelete:
    def test_delete_requires_auth(self, client, sample_schedule):
        resp = client.post(f'/maintenance/{sample_schedule.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_schedule(self, auth_client, sample_schedule):
        schedule_id = sample_schedule.id
        resp = auth_client.post(f'/maintenance/{schedule_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(MaintenanceSchedule, schedule_id) is None


class TestMaintenanceComplete:
    def test_complete_requires_auth(self, client, sample_schedule):
        resp = client.post(f'/maintenance/{sample_schedule.id}/complete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_complete_schedule(self, auth_client, sample_schedule):
        resp = auth_client.post(f'/maintenance/{sample_schedule.id}/complete', data={},
                                follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_schedule)
        assert sample_schedule.last_performed_date == date.today()

    def test_complete_with_expense(self, auth_client, sample_schedule):
        from app.models import Expense
        resp = auth_client.post(f'/maintenance/{sample_schedule.id}/complete', data={
            'create_expense': 'on',
            'actual_cost': '55.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        expense = Expense.query.filter_by(
            vehicle_id=sample_schedule.vehicle_id,
            description=sample_schedule.name
        ).first()
        assert expense is not None
        assert expense.cost == 55.0

    def test_complete_with_zero_cost_expense(self, auth_client, sample_schedule):
        """Ticking 'create expense' with a $0 cost must still create it (#271)."""
        from app.models import Expense
        resp = auth_client.post(f'/maintenance/{sample_schedule.id}/complete', data={
            'create_expense': 'on',
            'actual_cost': '0',
        }, follow_redirects=True)
        assert resp.status_code == 200
        expense = Expense.query.filter_by(
            vehicle_id=sample_schedule.vehicle_id,
            description=sample_schedule.name
        ).first()
        assert expense is not None
        assert expense.cost == 0.0

    def test_complete_with_performed_date(self, auth_client, sample_schedule):
        """A user-chosen completion date is applied to schedule and expense (#220)."""
        from app.models import Expense
        resp = auth_client.post(f'/maintenance/{sample_schedule.id}/complete', data={
            'performed_date': '2026-07-15',
            'create_expense': 'on',
            'actual_cost': '10.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_schedule)
        assert sample_schedule.last_performed_date == date(2026, 7, 15)
        expense = Expense.query.filter_by(
            vehicle_id=sample_schedule.vehicle_id,
            description=sample_schedule.name
        ).first()
        assert expense is not None
        assert expense.date == date(2026, 7, 15)


class TestMaintenanceHistory:
    def test_completions_survive_schedule_edit_and_delete(self, auth_client, sample_schedule):
        from app.models import MaintenanceEvent
        for day, reading in [(1, 10000), (2, 15000)]:
            response = auth_client.post(f'/maintenance/{sample_schedule.id}/complete', data={
                'performed_date': f'2026-01-0{day}', 'odometer': str(reading)})
            assert response.status_code == 302
        assert MaintenanceEvent.query.count() == 2
        auth_client.post(f'/maintenance/{sample_schedule.id}/delete')
        assert MaintenanceEvent.query.count() == 2
        assert all(e.schedule_id is None for e in MaintenanceEvent.query.all())
        response = auth_client.get('/maintenance/history')
        assert b'Oil Change' in response.data

    def test_edit_preserves_previous_and_new_service_details(self, auth_client, sample_schedule):
        from app.models import MaintenanceEvent
        sample_schedule.last_performed_date = date(2025, 1, 1)
        sample_schedule.last_performed_odometer = 5000
        db.session.commit()
        data = {'name': 'Oil Change', 'maintenance_type': 'oil_change',
                'last_performed_date': '2026-01-01', 'last_performed_odometer': '10000'}
        auth_client.post(f'/maintenance/{sample_schedule.id}/edit', data=data)
        auth_client.post(f'/maintenance/{sample_schedule.id}/edit', data=data)
        assert MaintenanceEvent.query.count() == 2
        assert {e.odometer for e in MaintenanceEvent.query.all()} == {5000, 10000}

    def test_private_history_cannot_be_requested(self, auth_client, admin_user):
        from app.models import Vehicle
        private = Vehicle(owner_id=admin_user.id, name='Private', vehicle_type='car')
        db.session.add(private)
        db.session.commit()
        assert auth_client.get(f'/maintenance/history?vehicle_id={private.id}').status_code == 403

    def test_existing_expenses_are_visible(self, auth_client, sample_expense):
        sample_expense.category = 'maintenance'
        sample_expense.description = 'Previous workshop service'
        db.session.commit()
        response = auth_client.get('/maintenance/history')
        assert response.status_code == 200
        assert b'Previous workshop service' in response.data


def test_matching_service_details_on_different_vehicles_are_not_hidden(auth_client, sample_vehicle, test_user):
    from app.models import Vehicle, Expense, MaintenanceEvent
    second = Vehicle(owner_id=test_user.id, name='Second vehicle', vehicle_type='car')
    db.session.add(second)
    db.session.flush()
    db.session.add_all([
        MaintenanceEvent(vehicle_id=sample_vehicle.id, user_id=test_user.id, name='Oil service',
                         maintenance_type='custom', performed_date=date(2026, 1, 1), odometer=100),
        Expense(vehicle_id=second.id, user_id=test_user.id, description='Oil service',
                category='maintenance', date=date(2026, 1, 1), odometer=100, cost=0),
    ])
    db.session.commit()
    body = auth_client.get('/maintenance/history').get_data(as_text=True)
    assert body.count('Oil service') == 2
