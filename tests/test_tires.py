import pytest
from datetime import date

from app import db
from app.models import TireSet, TireFitment


@pytest.fixture(scope='function')
def sample_tire_set(app, test_user, sample_vehicle):
    tire_set = TireSet(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        name='Michelin Alpin 6',
        tire_type='winter',
        size='205/55 R16 91H',
        purchase_date=date(2023, 10, 1),
        purchase_odometer=9000.0,
        cost=480.0,
    )
    db.session.add(tire_set)
    db.session.commit()
    return tire_set


@pytest.fixture(scope='function')
def summer_tire_set(app, test_user, sample_vehicle):
    tire_set = TireSet(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        name='Continental PremiumContact',
        tire_type='summer',
    )
    db.session.add(tire_set)
    db.session.commit()
    return tire_set


class TestTireSetDistance:
    def test_no_fitments_covers_nothing(self, sample_tire_set):
        assert sample_tire_set.get_distance() == 0

    def test_closed_periods_are_summed(self, sample_tire_set):
        db.session.add(TireFitment(tire_set_id=sample_tire_set.id, fitted_date=date(2023, 11, 1),
                                   fitted_odometer=10000.0, removed_date=date(2024, 4, 1),
                                   removed_odometer=13000.0))
        db.session.add(TireFitment(tire_set_id=sample_tire_set.id, fitted_date=date(2024, 11, 1),
                                   fitted_odometer=20000.0, removed_date=date(2025, 4, 1),
                                   removed_odometer=22500.0))
        db.session.commit()
        assert sample_tire_set.get_distance() == 5500.0

    def test_open_period_uses_the_current_odometer(self, sample_tire_set):
        db.session.add(TireFitment(tire_set_id=sample_tire_set.id, fitted_date=date(2024, 11, 1),
                                   fitted_odometer=20000.0))
        db.session.commit()
        assert sample_tire_set.get_distance(current_odometer=21000.0) == 1000.0

    def test_open_period_falls_back_to_the_vehicle_odometer(self, sample_tire_set, sample_fuel_log):
        # sample_fuel_log records an odometer of 10000
        db.session.add(TireFitment(tire_set_id=sample_tire_set.id, fitted_date=date(2024, 1, 1),
                                   fitted_odometer=9500.0))
        db.session.commit()
        assert sample_tire_set.get_distance() == 500.0

    def test_readings_out_of_order_do_not_count_backwards(self, sample_tire_set):
        db.session.add(TireFitment(tire_set_id=sample_tire_set.id, fitted_date=date(2024, 11, 1),
                                   fitted_odometer=20000.0, removed_date=date(2024, 12, 1),
                                   removed_odometer=19000.0))
        db.session.commit()
        assert sample_tire_set.get_distance() == 0

    def test_is_fitted_tracks_the_open_period(self, sample_tire_set):
        assert sample_tire_set.is_fitted is False
        fitment = TireFitment(tire_set_id=sample_tire_set.id, fitted_date=date(2024, 11, 1),
                              fitted_odometer=20000.0)
        db.session.add(fitment)
        db.session.commit()
        assert sample_tire_set.is_fitted is True
        assert sample_tire_set.vehicle.get_fitted_tire_set().id == sample_tire_set.id

        fitment.removed_date = date(2025, 4, 1)
        fitment.removed_odometer = 22000.0
        db.session.commit()
        assert sample_tire_set.is_fitted is False
        assert sample_tire_set.vehicle.get_fitted_tire_set() is None


class TestTireIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/tires/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/tires/')
        assert resp.status_code == 200

    def test_index_shows_sets_and_distance(self, auth_client, sample_tire_set):
        db.session.add(TireFitment(tire_set_id=sample_tire_set.id, fitted_date=date(2023, 11, 1),
                                   fitted_odometer=10000.0, removed_date=date(2024, 4, 1),
                                   removed_odometer=13000.0))
        db.session.commit()
        resp = auth_client.get('/tires/')
        assert resp.status_code == 200
        assert b'Michelin Alpin 6' in resp.data
        assert b'3000' in resp.data


class TestTireSetCrud:
    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/tires/new')
        assert resp.status_code == 200

    def test_create_tire_set(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/tires/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'name': 'Nokian Hakkapeliitta',
            'tire_type': 'winter',
            'size': '205/55 R16',
            'purchase_date': '2024-09-30',
            'purchase_odometer': '15000',
            'cost': '520.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        tire_set = TireSet.query.filter_by(name='Nokian Hakkapeliitta').first()
        assert tire_set is not None
        assert tire_set.tire_type == 'winter'
        assert tire_set.purchase_odometer == 15000.0
        assert tire_set.cost == 520.0
        assert tire_set.user_id == test_user.id

    def test_create_without_a_name_is_rejected(self, auth_client, sample_vehicle):
        resp = auth_client.post('/tires/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'name': '  ',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert TireSet.query.count() == 0

    def test_get_edit_form_returns_200(self, auth_client, sample_tire_set):
        resp = auth_client.get(f'/tires/{sample_tire_set.id}/edit')
        assert resp.status_code == 200
        assert b'Michelin Alpin 6' in resp.data

    def test_edit_tire_set(self, auth_client, sample_tire_set):
        resp = auth_client.post(f'/tires/{sample_tire_set.id}/edit', data={
            'name': 'Michelin Alpin 6',
            'tire_type': 'winter',
            'cost': '500',
            'is_retired': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_tire_set)
        assert sample_tire_set.cost == 500.0
        assert sample_tire_set.is_retired is True

    def test_delete_tire_set_removes_its_history(self, auth_client, sample_tire_set):
        db.session.add(TireFitment(tire_set_id=sample_tire_set.id, fitted_date=date(2023, 11, 1),
                                   fitted_odometer=10000.0))
        db.session.commit()
        set_id = sample_tire_set.id

        resp = auth_client.post(f'/tires/{set_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(TireSet, set_id) is None
        assert TireFitment.query.filter_by(tire_set_id=set_id).count() == 0


class TestFitAndRemove:
    def test_fit_records_the_period(self, auth_client, sample_tire_set):
        resp = auth_client.post(f'/tires/{sample_tire_set.id}/fit', data={
            'fitted_date': '2024-11-05',
            'fitted_odometer': '20000',
        }, follow_redirects=True)
        assert resp.status_code == 200

        fitment = sample_tire_set.current_fitment
        assert fitment is not None
        assert fitment.fitted_date == date(2024, 11, 5)
        assert fitment.fitted_odometer == 20000.0
        assert fitment.removed_odometer is None

    def test_fit_defaults_to_the_vehicles_latest_odometer(self, auth_client, sample_tire_set, sample_fuel_log):
        resp = auth_client.post(f'/tires/{sample_tire_set.id}/fit', data={}, follow_redirects=True)
        assert resp.status_code == 200
        assert sample_tire_set.current_fitment.fitted_odometer == 10000.0

    def test_fitting_a_second_set_takes_the_first_one_off(self, auth_client, sample_tire_set, summer_tire_set):
        auth_client.post(f'/tires/{sample_tire_set.id}/fit',
                         data={'fitted_date': '2023-11-01', 'fitted_odometer': '10000'},
                         follow_redirects=True)
        auth_client.post(f'/tires/{summer_tire_set.id}/fit',
                         data={'fitted_date': '2024-04-01', 'fitted_odometer': '13000'},
                         follow_redirects=True)

        assert sample_tire_set.is_fitted is False
        assert sample_tire_set.get_distance() == 3000.0
        assert summer_tire_set.is_fitted is True

    def test_fitting_an_already_fitted_set_is_a_no_op(self, auth_client, sample_tire_set):
        auth_client.post(f'/tires/{sample_tire_set.id}/fit',
                         data={'fitted_date': '2023-11-01', 'fitted_odometer': '10000'},
                         follow_redirects=True)
        auth_client.post(f'/tires/{sample_tire_set.id}/fit',
                         data={'fitted_date': '2023-12-01', 'fitted_odometer': '11000'},
                         follow_redirects=True)
        assert sample_tire_set.fitments.count() == 1

    def test_a_retired_set_cannot_be_fitted(self, auth_client, sample_tire_set):
        sample_tire_set.is_retired = True
        db.session.commit()

        resp = auth_client.post(f'/tires/{sample_tire_set.id}/fit',
                                data={'fitted_odometer': '20000'}, follow_redirects=True)
        assert resp.status_code == 200
        assert sample_tire_set.fitments.count() == 0

    def test_remove_closes_the_period(self, auth_client, sample_tire_set):
        auth_client.post(f'/tires/{sample_tire_set.id}/fit',
                         data={'fitted_date': '2023-11-01', 'fitted_odometer': '10000'},
                         follow_redirects=True)
        resp = auth_client.post(f'/tires/{sample_tire_set.id}/remove',
                                data={'removed_date': '2024-04-01', 'removed_odometer': '13500'},
                                follow_redirects=True)
        assert resp.status_code == 200
        assert sample_tire_set.is_fitted is False
        assert sample_tire_set.get_distance() == 3500.0

    def test_remove_rejects_a_lower_reading(self, auth_client, sample_tire_set):
        auth_client.post(f'/tires/{sample_tire_set.id}/fit',
                         data={'fitted_date': '2023-11-01', 'fitted_odometer': '10000'},
                         follow_redirects=True)
        resp = auth_client.post(f'/tires/{sample_tire_set.id}/remove',
                                data={'removed_date': '2024-04-01', 'removed_odometer': '9000'},
                                follow_redirects=True)
        assert resp.status_code == 200
        assert sample_tire_set.is_fitted is True

    def test_remove_when_not_fitted_is_a_no_op(self, auth_client, sample_tire_set):
        resp = auth_client.post(f'/tires/{sample_tire_set.id}/remove',
                                data={'removed_odometer': '13000'}, follow_redirects=True)
        assert resp.status_code == 200
        assert sample_tire_set.fitments.count() == 0

    def test_delete_a_fitting_record(self, auth_client, sample_tire_set):
        auth_client.post(f'/tires/{sample_tire_set.id}/fit',
                         data={'fitted_date': '2023-11-01', 'fitted_odometer': '10000'},
                         follow_redirects=True)
        fitment_id = sample_tire_set.current_fitment.id

        resp = auth_client.post(f'/tires/fitments/{fitment_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(TireFitment, fitment_id) is None


class TestTireAccessControl:
    def test_another_users_set_is_not_visible(self, app, client, sample_tire_set):
        from app.models import User

        other = User(username='other', email='other@example.com')
        other.set_password('OtherPass123!')
        db.session.add(other)
        db.session.commit()

        client.post('/auth/login', data={'username': 'other', 'password': 'OtherPass123!'},
                    follow_redirects=True)
        resp = client.get('/tires/')
        assert resp.status_code == 200
        assert b'Michelin Alpin 6' not in resp.data

    def test_another_user_cannot_fit_the_set(self, app, client, sample_tire_set):
        from app.models import User

        other = User(username='other', email='other@example.com')
        other.set_password('OtherPass123!')
        db.session.add(other)
        db.session.commit()

        client.post('/auth/login', data={'username': 'other', 'password': 'OtherPass123!'},
                    follow_redirects=True)
        resp = client.post(f'/tires/{sample_tire_set.id}/fit', data={'fitted_odometer': '20000'},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert sample_tire_set.fitments.count() == 0

    def test_a_viewer_cannot_fit_the_set(self, app, client, sample_tire_set, test_user):
        from app.models import ROLE_VIEWER

        test_user.role = ROLE_VIEWER
        db.session.commit()

        client.post('/auth/login', data={'username': 'testuser', 'password': 'TestPass123!'},
                    follow_redirects=True)
        resp = client.post(f'/tires/{sample_tire_set.id}/fit', data={'fitted_odometer': '20000'},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert sample_tire_set.fitments.count() == 0
