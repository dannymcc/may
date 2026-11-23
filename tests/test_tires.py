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


class TestAxleFitments:
    def test_front_and_rear_can_remain_fitted(self, auth_client, sample_tire_set, summer_tire_set):
        for tire, axle in [(sample_tire_set, 'front'), (summer_tire_set, 'rear')]:
            auth_client.post(f'/tires/{tire.id}/fit', data={'axle': axle, 'fitted_odometer': '10000'})
        assert sample_tire_set.current_fitment.axle == 'front'
        assert summer_tire_set.current_fitment.axle == 'rear'
        assert sample_tire_set.get_distance(10500) == 500
        assert summer_tire_set.get_distance(10500) == 500

    def test_partial_replacement_keeps_other_pair_and_distance(self, auth_client, sample_tire_set, summer_tire_set):
        auth_client.post(f'/tires/{sample_tire_set.id}/fit', data={'axle': 'all', 'fitted_odometer': '10000'})
        auth_client.post(f'/tires/{summer_tire_set.id}/fit', data={'axle': 'front', 'fitted_odometer': '10500'})
        assert sample_tire_set.current_fitment.axle == 'rear'
        assert summer_tire_set.current_fitment.axle == 'front'
        assert sample_tire_set.get_distance(11000) == 1000
        assert summer_tire_set.get_distance(11000) == 500

    def test_all_axles_replace_both_pairs(self, auth_client, sample_tire_set, summer_tire_set, test_user, sample_vehicle):
        auth_client.post(f'/tires/{sample_tire_set.id}/fit', data={'axle': 'front', 'fitted_odometer': '10000'})
        auth_client.post(f'/tires/{summer_tire_set.id}/fit', data={'axle': 'rear', 'fitted_odometer': '10000'})
        new_set = TireSet(vehicle_id=sample_vehicle.id, user_id=test_user.id, name='Full set')
        db.session.add(new_set)
        db.session.commit()
        auth_client.post(f'/tires/{new_set.id}/fit', data={'axle': 'all', 'fitted_odometer': '11000'})
        assert not sample_tire_set.is_fitted
        assert not summer_tire_set.is_fitted
        assert new_set.current_fitment.axle == 'all'

    @pytest.mark.parametrize('data', [{'axle': 'invalid'}, {'axle': 'front', 'fitted_odometer': 'nan'},
                                     {'axle': 'front', 'fitted_odometer': '9000'}])
    def test_invalid_replacement_cannot_close_existing_fitment(self, auth_client, sample_tire_set, summer_tire_set, data):
        auth_client.post(f'/tires/{sample_tire_set.id}/fit', data={'fitted_odometer': '10000'})
        auth_client.post(f'/tires/{summer_tire_set.id}/fit', data=data)
        assert sample_tire_set.current_fitment.axle == 'all'
        assert not summer_tire_set.is_fitted


class TestTreadHistory:
    def record(self, client, tire_set, **overrides):
        values = dict(label='A', measured_date='2026-10-01', depth_mm='6.5',
                      odometer='12000', position='front_left')
        values.update(overrides)
        return client.post(f'/tires/{tire_set.id}/tread', data=values, follow_redirects=True)

    def test_rotation_retains_identity_and_backdated_measurements(self, auth_client, sample_tire_set):
        from app.models import Tire, TireMeasurement
        assert self.record(auth_client, sample_tire_set).status_code == 200
        tire = Tire.query.one()
        self.record(auth_client, sample_tire_set, tire_id=tire.id,
                    measured_date='2026-11-01', depth_mm='5.4', position='rear_right')
        self.record(auth_client, sample_tire_set, tire_id=tire.id,
                    measured_date='2026-09-01', depth_mm='7', position='', odometer='')
        db.session.expire_all()
        assert Tire.query.count() == 1
        assert TireMeasurement.query.count() == 3
        assert tire.latest_measurement.depth_mm == 5.4
        assert [m.position for m in tire.measurements] == ['rear_right', 'front_left', '']
        assert tire.measurements[-1].odometer is None
        page = auth_client.get('/tires/')
        assert b'5.4 mm' in page.data

    @pytest.mark.parametrize('overrides', [
        {'depth_mm': '-1'}, {'depth_mm': 'nan'}, {'depth_mm': 'inf'},
        {'depth_mm': '101'}, {'depth_mm': ''}, {'odometer': '-1'},
        {'odometer': 'nan'}, {'odometer': 'bad'}, {'measured_date': '2026-02-30'},
        {'position': 'invalid'}, {'label': ''}, {'label': 'x' * 101},
    ])
    def test_invalid_measurement_is_atomic(self, auth_client, sample_tire_set, overrides):
        from app.models import Tire, TireMeasurement
        self.record(auth_client, sample_tire_set, **overrides)
        assert Tire.query.count() == TireMeasurement.query.count() == 0

    def test_edit_delete_and_cascade(self, auth_client, sample_tire_set):
        from app.models import Tire, TireMeasurement
        self.record(auth_client, sample_tire_set)
        tire = Tire.query.one()
        measurement = TireMeasurement.query.one()
        route = f'/tires/{sample_tire_set.id}/tread/{measurement.id}/edit'
        assert auth_client.get(route).status_code == 200
        auth_client.post(route, data=dict(tire_id=tire.id, measured_date='2026-10-02',
                                         depth_mm='0', odometer='0', position='rear'))
        db.session.refresh(measurement)
        assert measurement.depth_mm == measurement.odometer == 0
        assert measurement.position == 'rear'
        auth_client.post(f'/tires/measurements/{measurement.id}/delete')
        assert TireMeasurement.query.count() == 0
        self.record(auth_client, sample_tire_set, tire_id=tire.id)
        auth_client.post(f'/tires/{sample_tire_set.id}/delete')
        assert Tire.query.count() == TireMeasurement.query.count() == 0

    def test_tire_from_other_set_cannot_be_used(self, auth_client, sample_tire_set, summer_tire_set):
        from app.models import Tire, TireMeasurement
        self.record(auth_client, sample_tire_set)
        tire = Tire.query.one()
        self.record(auth_client, summer_tire_set, tire_id=tire.id)
        assert TireMeasurement.query.count() == 1
        measurement = TireMeasurement.query.one()
        assert auth_client.get(f'/tires/{summer_tire_set.id}/tread/{measurement.id}/edit').status_code == 404

    def test_viewer_cannot_write(self, auth_client, sample_tire_set, test_user):
        from app.models import ROLE_VIEWER, TireMeasurement
        self.record(auth_client, sample_tire_set)
        measurement = TireMeasurement.query.one()
        test_user.role = ROLE_VIEWER
        db.session.commit()
        self.record(auth_client, sample_tire_set, label='B')
        auth_client.post(f'/tires/measurements/{measurement.id}/delete')
        assert TireMeasurement.query.count() == 1
        assert b'name="depth_mm"' not in auth_client.get(f'/tires/{sample_tire_set.id}/tread').data

    def test_other_account_cannot_read_or_change_measurements(self, auth_client, sample_tire_set, test_user):
        from app.models import TireMeasurement, User
        self.record(auth_client, sample_tire_set)
        measurement = TireMeasurement.query.one()
        other = User(username='unrelated', email='unrelated@example.org')
        other.set_password('OtherPass123!')
        db.session.add(other)
        db.session.commit()
        auth_client.get('/auth/logout')
        auth_client.post('/auth/login', data=dict(username='unrelated', password='OtherPass123!'))
        page = auth_client.get(f'/tires/{sample_tire_set.id}/tread', follow_redirects=True)
        assert b'name="depth_mm"' not in page.data
        self.record(auth_client, sample_tire_set, label='B')
        auth_client.post(f'/tires/measurements/{measurement.id}/delete')
        assert TireMeasurement.query.count() == 1

    def test_thresholds_are_optional_and_use_latest_by_date(self, auth_client, sample_tire_set):
        from app.models import Tire
        self.record(auth_client, sample_tire_set, depth_mm='3')
        tire = Tire.query.one()
        assert tire.tread_status is None
        route = f'/tires/{sample_tire_set.id}/tread'
        auth_client.post(route, data=dict(action='thresholds', tread_warning_mm='4', tread_replace_mm='2'))
        db.session.refresh(sample_tire_set)
        assert str(tire.tread_status) == 'Warning threshold reached'
        self.record(auth_client, sample_tire_set, tire_id=tire.id, depth_mm='2', measured_date='2026-11-01')
        db.session.expire_all()
        assert str(tire.tread_status) == 'Replacement threshold reached'
        auth_client.post(route, data=dict(action='thresholds', tread_warning_mm='1', tread_replace_mm='2'))
        db.session.refresh(sample_tire_set)
        assert sample_tire_set.tread_warning_mm == 4
        auth_client.post(route, data=dict(action='thresholds', tread_warning_mm='', tread_replace_mm=''))
        db.session.refresh(sample_tire_set)
        assert tire.tread_status is None

    def test_backup_roundtrip_and_repeat_restore(self, auth_client, sample_tire_set, test_user):
        from app.models import Tire, TireMeasurement
        from app.services.backup_restore import restore_backup
        self.record(auth_client, sample_tire_set)
        tire = Tire.query.one()
        self.record(auth_client, sample_tire_set, tire_id=tire.id, depth_mm='5',
                    measured_date='2026-11-01', position='rear_right')
        raw_set = sample_tire_set.to_dict()
        identity = tire.identity
        backup = dict(export_info={}, vehicles=[dict(name=sample_tire_set.vehicle.name,
                      tire_sets=[raw_set])])
        db.session.delete(tire)
        db.session.commit()
        preview = restore_backup(backup, test_user, dry_run=True)
        assert preview['tire_measurements']['added'] == 2
        assert Tire.query.count() == 0
        summary = restore_backup(backup, test_user)
        assert summary['tires']['added'] == 1
        assert summary['tire_measurements']['added'] == 2
        assert Tire.query.one().identity == identity
        repeated = restore_backup(backup, test_user)
        assert repeated['tire_measurements']['added'] == 0
        assert repeated['tire_measurements']['skipped'] == 2
        assert TireMeasurement.query.count() == 2

    def test_json_and_zip_export_restore_to_another_account(self, auth_client, sample_tire_set, admin_user):
        import io
        import json
        import zipfile
        from app.models import Tire
        from app.services.backup_restore import restore_backup
        self.record(auth_client, sample_tire_set)
        sample_tire_set.tread_warning_mm = 4
        sample_tire_set.tread_replace_mm = 2
        db.session.commit()
        exported = auth_client.get('/api/export/json').get_json()
        exported_set = exported['vehicles'][0]['tire_sets'][0]
        assert exported_set['tires'][0]['measurements'][0]['depth_mm'] == 6.5
        assert exported_set['tread_warning_mm'] == 4
        response = auth_client.get('/api/export/backup')
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            name = next(n for n in archive.namelist() if n.endswith('.json'))
            zipped = json.loads(archive.read(name))
        assert zipped['vehicles'][0]['tire_sets'][0]['tires'] == exported_set['tires']
        restored = restore_backup(exported, admin_user)
        assert restored['tire_measurements']['added'] == 1
        assert Tire.query.count() == 2
        assert len({t.identity for t in Tire.query.all()}) == 1
        restored_set = admin_user.get_all_vehicles()[0].tire_sets.first()
        assert restored_set.tread_warning_mm == 4
        assert restored_set.tread_replace_mm == 2

    def test_restore_rejects_invalid_measurements(self, auth_client, sample_tire_set, test_user):
        from app.models import TireMeasurement
        from app.services.backup_restore import restore_backup
        self.record(auth_client, sample_tire_set)
        exported = auth_client.get('/api/export/json').get_json()
        raw_tire = exported['vehicles'][0]['tire_sets'][0]['tires'][0]
        valid = raw_tire['measurements'][0]
        raw_tire['measurements'] = [dict(valid, depth_mm=-1), dict(valid, depth_mm=float('nan')),
                                    dict(valid, depth_mm=True), dict(valid, odometer='broken'),
                                    dict(valid, position=[])]
        result = restore_backup(exported, test_user)
        assert result['tire_measurements']['skipped'] == 5
        raw_tire['measurements'] = 1
        assert restore_backup(exported, test_user)['tire_measurements']['skipped'] == 1
        exported['vehicles'][0]['tire_sets'][0]['tires'] = 1
        assert restore_backup(exported, test_user)['tires']['skipped'] == 1
        assert TireMeasurement.query.count() == 1


class TestTreadOnSetForm:
    def test_create_and_edit_readings_in_the_set_form(self, auth_client, sample_vehicle):
        from app.models import Tire, TireMeasurement

        form = dict(vehicle_id=sample_vehicle.id, name='With tread', tread_config_present='1',
                    tread_tracking='on', tread_date='2026-10-01',
                    depth_front_left='6,5', depth_front_right='7')
        assert auth_client.post('/tires/new', data=form).status_code == 302
        tire_set = TireSet.query.filter_by(name=form['name']).one()
        assert tire_set.tracks_tread
        assert Tire.query.filter_by(tire_set_id=tire_set.id).count() == 2
        first = TireMeasurement.query.filter_by(position='front_left').one()

        db.session.add(TireFitment(tire_set_id=tire_set.id, fitted_date=date(2026, 10, 2),
                                   fitted_odometer=12000))
        db.session.commit()
        route = f'/tires/{tire_set.id}/edit'
        entry = dict(name=form['name'], tread_config_present='1', tread_tracking='on',
                     tread_date='2026-10-03', tread_odometer='12250',
                     depth_rear_right='5.8', tire_rear_right=first.tire_id)
        assert auth_client.post(route, data=entry).status_code == 302
        assert auth_client.post(route, data=entry).status_code == 302
        page = auth_client.get(route)
        assert b'id="tread-history"' in page.data
        assert b'250 km' in page.data
        assert b'12250' in page.data or b'12,250' in page.data
        assert len(db.session.get(Tire, first.tire_id).measurements) == 2

        assert auth_client.post(route, data=dict(name=form['name'], tread_config_present='1')).status_code == 302
        assert db.session.get(TireSet, tire_set.id).tracks_tread is False
        assert db.session.get(Tire, first.tire_id).measurements

    def test_invalid_batch_rolls_back_set_and_all_readings(self, auth_client, sample_tire_set):
        from app.models import TireMeasurement

        route = f'/tires/{sample_tire_set.id}/edit'
        name = sample_tire_set.name
        response = auth_client.post(route, data=dict(name='Do not save', tread_config_present='1',
                                    tread_tracking='on', tread_date='2026-10-01',
                                    depth_front_left='6', depth_rear_right='-1'))
        assert response.status_code == 200
        assert b'Do not save' in response.data
        db.session.expire_all()
        assert sample_tire_set.name == name
        assert TireMeasurement.query.count() == 0
        assert not sample_tire_set.tracks_tread

    def test_one_physical_tire_cannot_fill_two_wheel_positions(self, auth_client, sample_tire_set):
        from app.models import Tire, TireMeasurement

        tire = Tire(tire_set=sample_tire_set, label='A')
        db.session.add(tire)
        db.session.commit()
        route = f'/tires/{sample_tire_set.id}/edit'
        response = auth_client.post(route, data=dict(name=sample_tire_set.name, tread_config_present='1',
                                    tread_tracking='on', tread_date='2026-10-01',
                                    depth_front_left='6', tire_front_left=tire.id,
                                    depth_rear_right='5', tire_rear_right=tire.id))
        assert response.status_code == 200
        assert TireMeasurement.query.count() == 0

    def test_motorcycle_form_only_saves_its_two_positions(self, auth_client, sample_vehicle):
        from app.models import TireMeasurement

        sample_vehicle.vehicle_type = 'motorbike'
        db.session.commit()
        response = auth_client.post('/tires/new', data=dict(
            vehicle_id=sample_vehicle.id, name='Motorcycle', tread_config_present='1',
            tread_tracking='on', tread_date='2026-10-01', depth_front='3.8',
            depth_rear='4.2', depth_front_left='6'))
        assert response.status_code == 302
        assert {row.position for row in TireMeasurement.query.all()} == {'front', 'rear'}

    def test_replacement_starts_separate_history_and_disabling_hides_it(self, auth_client, sample_tire_set):
        from app.models import Tire, TireMeasurement

        old_tire = Tire(tire_set=sample_tire_set, label='Old right')
        db.session.add(TireMeasurement(tire=old_tire, measured_date=date(2026, 10, 1),
                                       depth_mm=3.25, position='front_right'))
        db.session.commit()

        edit_url = f'/tires/{sample_tire_set.id}/edit'
        previous = old_tire.id
        data = dict(name=sample_tire_set.name, tread_config_present='1', tread_tracking='on',
                    tread_date='2026-10-02', depth_front_right='7.6')
        rejected = auth_client.post(edit_url, data=data)
        assert rejected.status_code == 200
        assert TireMeasurement.query.count() == 1

        data['tire_front_right'] = f'replace:{previous}'
        assert auth_client.post(edit_url, data=data).status_code == 302
        assert auth_client.post(edit_url, data=data).status_code == 200
        assert TireMeasurement.query.count() == 2
        assert db.session.get(Tire, previous).latest_measurement.depth_mm == 3.25
        history = auth_client.get(edit_url).data
        assert b'<details id="tread-history"' in history
        assert b'3.25 mm' in history and b'7.6 mm' in history
        overview = auth_client.get('/tires/').data
        assert b'3.25 mm' not in overview and b'7.6 mm' in overview

        replacement = Tire.query.filter(Tire.id != previous).one()
        rotation = dict(name=sample_tire_set.name, tread_config_present='1', tread_tracking='on',
                        tread_date='2026-10-03', depth_rear_right='7.4', tire_rear_right=replacement.id)
        assert auth_client.post(edit_url, data=rotation).status_code == 302
        assert b'3.25 mm' not in auth_client.get('/tires/').data
        measurement_url = f'/tires/{sample_tire_set.id}/tread'
        unpositioned = dict(tire_id=replacement.id, measured_date='2026-10-04', depth_mm='7.3', position='')
        assert auth_client.post(measurement_url, data=unpositioned).status_code == 302
        overview = auth_client.get('/tires/').data
        assert b'3.25 mm' not in overview and b'7.3 mm' in overview
        individual = auth_client.get(measurement_url).data
        assert b'data-position="rear_right"' in individual and b'data-position="front_right"' not in individual

        data.pop('tread_tracking')
        assert auth_client.post(edit_url, data=data).status_code == 302
        assert b'id="tread-history"' not in auth_client.get(edit_url).data
        assert b'7.3 mm' not in auth_client.get('/tires/').data
        assert TireMeasurement.query.count() == 4
        data.pop('depth_front_right')
        data['tread_tracking'] = 'on'
        assert auth_client.post(edit_url, data=data).status_code == 302
        assert b'3.25 mm' in auth_client.get(edit_url).data

    def test_profile_unit_covers_overview_thresholds_and_individual_measurements(self, auth_client, sample_vehicle, test_user):
        from app.models import TireMeasurement

        assert auth_client.post('/auth/settings', data=dict(tread_unit='inch32')).status_code == 302
        db.session.refresh(test_user)
        assert test_user.tread_unit == 'inch32'
        assert test_user.distance_unit == 'km'

        response = auth_client.post('/tires/new', data=dict(
            vehicle_id=sample_vehicle.id, name='US tread', tread_config_present='1',
            tread_tracking='on', tread_unit='inch32', tread_date='2026-10-01',
            depth_front_left='6', depth_front_right='6/32″', depth_rear_left='6.5 / 32',
            tread_warning_mm='4/32', tread_replace_mm='2', tread_odometer='10250'))
        assert response.status_code == 302
        rows = TireMeasurement.query.all()
        by_position = {row.position: row for row in rows}
        assert by_position['front_left'].depth_mm == by_position['front_right'].depth_mm == 4.7625
        assert by_position['rear_left'].depth_mm == 5.159375
        assert {row.odometer for row in rows} == {10250}
        assert '6/32″'.encode() in auth_client.get('/tires/').data

        tire_set = TireSet.query.filter_by(name='US tread').one()
        route = f'/tires/{tire_set.id}/tread'
        assert tire_set.tread_warning_mm == 3.175 and tire_set.tread_replace_mm == 1.5875
        set_form = auth_client.get(f'/tires/{tire_set.id}/edit').data
        assert b'name="tread_warning_mm"' in set_form and b'<select name="tread_unit"' not in set_form
        individual_form = auth_client.get(route).data
        assert b'Individual measurements' in individual_form and b'data-position="front_left"' in individual_form
        assert b'name="tread_warning_mm"' not in individual_form and b'id="tread-history"' not in individual_form
        measurement = TireMeasurement.query.filter_by(position='front_left').one()
        edit = f'{route}/{measurement.id}/edit'
        assert b'value="6"' in auth_client.get(edit).data
        assert auth_client.post('/auth/settings', data=dict(tread_unit='mm')).status_code == 302
        assert b'4.76 mm' in auth_client.get('/tires/').data
        assert b'value="4.7625"' in auth_client.get(edit).data
        db.session.refresh(measurement)
        assert measurement.depth_mm == 4.7625

    def test_inline_thresholds_clear_and_reject_invalid_order_atomically(self, auth_client, sample_tire_set):
        route = f'/tires/{sample_tire_set.id}/edit'
        fields = dict(name=sample_tire_set.name, tread_config_present='1', tread_tracking='on', tread_unit='mm')
        assert auth_client.post(route, data=dict(fields, tread_warning_mm='4', tread_replace_mm='2')).status_code == 302
        assert auth_client.post(route, data=dict(fields, tread_warning_mm='1', tread_replace_mm='2')).status_code == 200
        db.session.refresh(sample_tire_set)
        assert sample_tire_set.tread_warning_mm == 4
        assert auth_client.post(route, data=dict(fields, tread_warning_mm='', tread_replace_mm='')).status_code == 302
        db.session.refresh(sample_tire_set)
        assert sample_tire_set.tread_warning_mm is None and sample_tire_set.tread_replace_mm is None

    @pytest.mark.parametrize('bad', ['6/16', '6"', '-1/32', '127', 'nan', 'inf'])
    def test_reject_malformed_or_out_of_range_us_readings(self, auth_client, sample_vehicle, bad):
        from app.models import TireMeasurement

        response = auth_client.post('/tires/new', data=dict(
            vehicle_id=sample_vehicle.id, name='Bad US tread', tread_config_present='1',
            tread_tracking='on', tread_unit='inch32', tread_date='2026-10-01',
            depth_front_left=bad))
        assert response.status_code == 200
        assert TireSet.query.filter_by(name='Bad US tread').count() == 0
        assert TireMeasurement.query.count() == 0
