import pytest
from app import db
from app.models import Vehicle


class TestVehicleIndex:
    def test_list_requires_auth(self, client):
        resp = client.get('/vehicles/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_list_returns_200(self, auth_client):
        resp = auth_client.get('/vehicles/')
        assert resp.status_code == 200

    def test_list_shows_vehicles(self, auth_client, sample_vehicle):
        resp = auth_client.get('/vehicles/')
        assert b'Test Car' in resp.data


class TestVehicleNew:
    def test_get_new_form_requires_auth(self, client):
        resp = client.get('/vehicles/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client):
        resp = auth_client.get('/vehicles/new')
        assert resp.status_code == 200

    def test_create_vehicle(self, auth_client, test_user):
        resp = auth_client.post('/vehicles/new', data={
            'name': 'My New Car',
            'vehicle_type': 'car',
            'make': 'Honda',
            'model': 'Civic',
            'year': '2022',
            'fuel_type': 'petrol',
            'tracking_unit': 'mileage',
        }, follow_redirects=True)
        assert resp.status_code == 200
        vehicle = Vehicle.query.filter_by(name='My New Car').first()
        assert vehicle is not None
        assert vehicle.make == 'Honda'
        assert vehicle.owner_id == test_user.id


class TestVehicleView:
    def test_view_requires_auth(self, client, sample_vehicle):
        resp = client.get(f'/vehicles/{sample_vehicle.id}', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_view_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Test Car' in resp.data

    def test_view_404_for_nonexistent(self, auth_client):
        resp = auth_client.get('/vehicles/99999')
        assert resp.status_code == 404


class TestVehicleEdit:
    def test_edit_requires_auth(self, client, sample_vehicle):
        resp = client.get(f'/vehicles/{sample_vehicle.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}/edit')
        assert resp.status_code == 200

    def test_edit_form_renders_null_fields_blank(self, auth_client, sample_vehicle):
        # Nullable numeric fields (tank capacity etc.) must render as empty
        # strings, not the literal text "None", which blocks validation on
        # save (#241).
        sample_vehicle.tank_capacity = None
        db.session.commit()
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}/edit')
        assert resp.status_code == 200
        assert b'value="None"' not in resp.data

    def test_edit_vehicle(self, auth_client, sample_vehicle):
        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': 'Updated Car',
            'vehicle_type': 'car',
            'make': 'Toyota',
            'model': 'Camry',
            'year': '2024',
            'fuel_type': 'petrol',
            'tracking_unit': 'mileage',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.name == 'Updated Car'
        assert sample_vehicle.model == 'Camry'


class TestVehicleDelete:
    def test_delete_requires_auth(self, client, sample_vehicle):
        resp = client.post(f'/vehicles/{sample_vehicle.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_vehicle(self, auth_client, sample_vehicle):
        vehicle_id = sample_vehicle.id
        resp = auth_client.post(f'/vehicles/{vehicle_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert Vehicle.query.get(vehicle_id) is None


class TestVehicleArchive:
    def test_archive_vehicle(self, auth_client, sample_vehicle):
        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/archive', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.is_active is False

    def test_unarchive_vehicle(self, auth_client, sample_vehicle):
        sample_vehicle.is_active = False
        db.session.commit()

        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/unarchive', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.is_active is True

    def test_archived_vehicles_shown_with_param(self, auth_client, sample_vehicle):
        sample_vehicle.is_active = False
        db.session.commit()

        resp = auth_client.get('/vehicles/?archived=true')
        assert resp.status_code == 200
        assert b'Test Car' in resp.data


class TestVehicleSharing:
    def test_is_shared_defaults_false(self, sample_vehicle):
        assert sample_vehicle.is_shared is False

    def test_shared_vehicle_visible_to_other_user(self, app, test_user, sample_vehicle):
        from app.models import User
        other = User(username='other_user', email='other@example.com')
        other.set_password('OtherPass123!')
        db.session.add(other)
        db.session.commit()

        # Not shared yet — other user should not see it
        assert sample_vehicle not in other.get_all_vehicles()

        # Mark as shared
        sample_vehicle.is_shared = True
        db.session.commit()

        assert sample_vehicle in other.get_all_vehicles()

    def test_edit_vehicle_sets_is_shared(self, auth_client, sample_vehicle):
        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': sample_vehicle.name,
            'vehicle_type': sample_vehicle.vehicle_type,
            'fuel_type': sample_vehicle.fuel_type,
            'tracking_unit': 'mileage',
            'is_active': 'on',
            'is_shared': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.is_shared is True

    def test_edit_vehicle_clears_is_shared(self, auth_client, sample_vehicle):
        sample_vehicle.is_shared = True
        db.session.commit()

        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': sample_vehicle.name,
            'vehicle_type': sample_vehicle.vehicle_type,
            'fuel_type': sample_vehicle.fuel_type,
            'tracking_unit': 'mileage',
            'is_active': 'on',
            # is_shared omitted → checkbox unchecked
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.is_shared is False

    def test_shared_badge_shown_in_vehicle_list(self, auth_client, sample_vehicle):
        sample_vehicle.is_shared = True
        db.session.commit()
        resp = auth_client.get('/vehicles/')
        assert resp.status_code == 200
        assert b'Shared' in resp.data


class TestVehicleViewMaintenancePanel:
    def test_view_shows_maintenance_panel(self, auth_client, app, test_user, sample_vehicle):
        from app.models import MaintenanceSchedule
        from datetime import date, timedelta
        schedule = MaintenanceSchedule(
            vehicle_id=sample_vehicle.id,
            user_id=test_user.id,
            name='Oil Change',
            maintenance_type='oil_change',
            next_due_date=date.today() + timedelta(days=15),
            is_active=True,
        )
        db.session.add(schedule)
        db.session.commit()
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Upcoming Maintenance' in resp.data
        assert b'Oil Change' in resp.data

    def test_view_hides_maintenance_panel_when_empty(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'Upcoming Maintenance' not in resp.data


class TestVehicleReportReceipts:
    """#219 — receipt images attached to the vehicle PDF report."""

    @staticmethod
    def _attach(tmp_path, record, name, contents=b'fake-image-bytes', write=True):
        from app.models import Attachment
        stored = f'stored_{name}'
        if write:
            (tmp_path / stored).write_bytes(contents)
        attachment = Attachment(
            filename=stored,
            original_filename=name,
            file_type=name.rsplit('.', 1)[1].lower(),
            expense_id=record.id if record.__tablename__ == 'expenses' else None,
            fuel_log_id=record.id if record.__tablename__ == 'fuel_logs' else None,
        )
        db.session.add(attachment)
        db.session.commit()
        return attachment

    def test_images_are_inlined_as_data_uris(self, app, tmp_path, sample_expense):
        from app.routes.vehicles import collect_receipts
        self._attach(tmp_path, sample_expense, 'receipt.png')

        receipts, omitted = collect_receipts([], [sample_expense], str(tmp_path))

        assert omitted == []
        assert len(receipts) == 1
        assert receipts[0]['data_uri'].startswith('data:image/png;base64,')
        assert receipts[0]['title'] == 'Oil change'
        assert receipts[0]['cost'] == 75.0

    def test_jpg_uses_jpeg_mime_type(self, app, tmp_path, sample_expense):
        from app.routes.vehicles import collect_receipts
        self._attach(tmp_path, sample_expense, 'receipt.jpg')

        receipts, _omitted = collect_receipts([], [sample_expense], str(tmp_path))

        assert receipts[0]['data_uri'].startswith('data:image/jpeg;base64,')

    def test_fuel_log_receipts_included(self, app, tmp_path, sample_fuel_log):
        from app.routes.vehicles import collect_receipts
        self._attach(tmp_path, sample_fuel_log, 'fillup.webp')

        receipts, _omitted = collect_receipts([sample_fuel_log], [], str(tmp_path))

        assert len(receipts) == 1
        assert receipts[0]['cost'] == 60.0

    def test_pdf_attachment_is_listed_not_embedded(self, app, tmp_path, sample_expense):
        from app.routes.vehicles import collect_receipts
        self._attach(tmp_path, sample_expense, 'receipt.pdf')

        receipts, omitted = collect_receipts([], [sample_expense], str(tmp_path))

        assert receipts == []
        assert len(omitted) == 1
        assert omitted[0]['filename'] == 'receipt.pdf'
        assert 'data_uri' not in omitted[0]

    def test_missing_file_is_listed_not_fatal(self, app, tmp_path, sample_expense):
        from app.routes.vehicles import collect_receipts
        self._attach(tmp_path, sample_expense, 'gone.png', write=False)

        receipts, omitted = collect_receipts([], [sample_expense], str(tmp_path))

        assert receipts == []
        assert len(omitted) == 1

    def test_oversized_receipts_are_skipped(self, app, tmp_path, monkeypatch, sample_expense):
        from app.routes import vehicles as vehicles_routes
        self._attach(tmp_path, sample_expense, 'big.png', contents=b'x' * 64)
        monkeypatch.setattr(vehicles_routes, 'MAX_RECEIPT_BYTES', 8)

        receipts, omitted = vehicles_routes.collect_receipts(
            [], [sample_expense], str(tmp_path))

        assert receipts == []
        assert len(omitted) == 1

    def test_receipts_sorted_newest_first(self, app, tmp_path, test_user, sample_vehicle):
        from datetime import date
        from app.models import Expense
        from app.routes.vehicles import collect_receipts

        older = Expense(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                        date=date(2024, 1, 1), category='repairs',
                        description='Older', cost=10.0)
        newer = Expense(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                        date=date(2024, 6, 1), category='repairs',
                        description='Newer', cost=20.0)
        db.session.add_all([older, newer])
        db.session.commit()
        self._attach(tmp_path, older, 'older.png')
        self._attach(tmp_path, newer, 'newer.png')

        receipts, _omitted = collect_receipts([], [older, newer], str(tmp_path))

        assert [r['title'] for r in receipts] == ['Newer', 'Older']

    def test_template_renders_receipt_images(self, app, sample_vehicle, test_user):
        from datetime import date, datetime
        from flask import render_template
        from app.models import AppSettings

        with app.test_request_context():
            html = render_template(
                'vehicles/report_pdf.html',
                vehicle=sample_vehicle, fuel_logs=[], expenses=[], specs=[],
                stats={'total_fuel_cost': 0, 'total_expense_cost': 0, 'total_cost': 0,
                       'total_distance': 0, 'avg_consumption': None,
                       'fuel_logs_count': 0, 'expenses_count': 0},
                user=test_user, branding=AppSettings.get_all_branding(),
                include_receipts=True,
                receipts=[{'kind': 'Expense', 'date': date(2024, 1, 20),
                           'title': 'Oil change', 'subtitle': 'Halfords',
                           'cost': 75.0, 'filename': 'receipt.png',
                           'data_uri': 'data:image/png;base64,AAAA'}],
                receipts_omitted=[{'kind': 'Expense', 'date': date(2024, 2, 1),
                                   'title': 'Tyres', 'subtitle': '',
                                   'cost': 200.0, 'filename': 'scan.pdf',
                                   'reason': 'not an image'}],
                generated_at=datetime(2024, 3, 1, 12, 0),
            )

        assert 'Receipts (1 image)' in html
        assert 'data:image/png;base64,AAAA' in html
        assert 'scan.pdf' in html

    def test_template_omits_receipts_section_by_default(self, app, sample_vehicle, test_user):
        from datetime import datetime
        from flask import render_template
        from app.models import AppSettings

        with app.test_request_context():
            html = render_template(
                'vehicles/report_pdf.html',
                vehicle=sample_vehicle, fuel_logs=[], expenses=[], specs=[],
                stats={'total_fuel_cost': 0, 'total_expense_cost': 0, 'total_cost': 0,
                       'total_distance': 0, 'avg_consumption': None,
                       'fuel_logs_count': 0, 'expenses_count': 0},
                user=test_user, branding=AppSettings.get_all_branding(),
                include_receipts=False, receipts=[], receipts_omitted=[],
                generated_at=datetime(2024, 3, 1, 12, 0),
            )

        assert 'Receipts' not in html

    def test_view_offers_receipt_report_link(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert f'/vehicles/{sample_vehicle.id}/report?receipts=1'.encode() in resp.data

    def test_report_route_embeds_receipts(self, auth_client, app, tmp_path,
                                          monkeypatch, sample_expense):
        """The route feeds the receipt images through to the rendered HTML."""
        import sys
        import types

        rendered = {}

        class FakeHTML:
            def __init__(self, string, base_url=None):
                rendered['html'] = string

            def write_pdf(self):
                return b'%PDF-fake'

        fake = types.ModuleType('weasyprint')
        fake.HTML = FakeHTML
        fake.CSS = object
        monkeypatch.setitem(sys.modules, 'weasyprint', fake)
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        self._attach(tmp_path, sample_expense, 'receipt.png')

        resp = auth_client.get(
            f'/vehicles/{sample_expense.vehicle_id}/report?receipts=1')

        assert resp.status_code == 200
        assert resp.mimetype == 'application/pdf'
        assert 'data:image/png;base64,' in rendered['html']

    def test_report_route_skips_receipts_by_default(self, auth_client, app, tmp_path,
                                                    monkeypatch, sample_expense):
        import sys
        import types

        rendered = {}

        class FakeHTML:
            def __init__(self, string, base_url=None):
                rendered['html'] = string

            def write_pdf(self):
                return b'%PDF-fake'

        fake = types.ModuleType('weasyprint')
        fake.HTML = FakeHTML
        fake.CSS = object
        monkeypatch.setitem(sys.modules, 'weasyprint', fake)
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        self._attach(tmp_path, sample_expense, 'receipt.png')

        resp = auth_client.get(f'/vehicles/{sample_expense.vehicle_id}/report')

        assert resp.status_code == 200
        assert 'data:image/png;base64,' not in rendered['html']
        assert 'Receipts' not in rendered['html']


class TestVehicleReportParts:
    """#235 — the parts list appears in the vehicle PDF report."""

    @staticmethod
    def _add_part(vehicle, user, name='Engine Oil', part_type='oil', **kwargs):
        from app.models import VehiclePart
        part = VehiclePart(vehicle_id=vehicle.id, user_id=user.id,
                           name=name, part_type=part_type, **kwargs)
        db.session.add(part)
        db.session.commit()
        return part

    @staticmethod
    def _render(app, vehicle, user, **overrides):
        from datetime import datetime
        from flask import render_template
        from app.models import AppSettings

        kwargs = dict(
            vehicle=vehicle, fuel_logs=[], expenses=[], specs=[], parts=[],
            part_type_labels={},
            stats={'total_fuel_cost': 0, 'total_expense_cost': 0, 'total_cost': 0,
                   'total_distance': 0, 'avg_consumption': None,
                   'fuel_logs_count': 0, 'expenses_count': 0},
            user=user, branding=AppSettings.get_all_branding(),
            include_receipts=False, receipts=[], receipts_omitted=[],
            generated_at=datetime(2024, 3, 1, 12, 0),
        )
        kwargs.update(overrides)
        with app.test_request_context():
            return render_template('vehicles/report_pdf.html', **kwargs)

    @staticmethod
    def _fake_weasyprint(monkeypatch):
        """Swap WeasyPrint for a stub and return the dict it records HTML into."""
        import sys
        import types

        rendered = {}

        class FakeHTML:
            def __init__(self, string, base_url=None):
                rendered['html'] = string

            def write_pdf(self):
                return b'%PDF-fake'

        fake = types.ModuleType('weasyprint')
        fake.HTML = FakeHTML
        fake.CSS = object
        monkeypatch.setitem(sys.modules, 'weasyprint', fake)
        return rendered

    def test_template_renders_parts_table(self, app, sample_vehicle, test_user):
        part = self._add_part(sample_vehicle, test_user, specification='10W-40',
                              quantity=3.5, unit='L', part_number='ABC-123')

        html = self._render(app, sample_vehicle, test_user, parts=[part],
                            part_type_labels={'oil': 'Engine Oil'})

        assert 'Parts (1)' in html
        assert '10W-40' in html
        assert '3.5 L' in html
        assert 'ABC-123' in html

    def test_template_falls_back_to_raw_part_type(self, app, sample_vehicle, test_user):
        part = self._add_part(sample_vehicle, test_user, part_type='custom')

        html = self._render(app, sample_vehicle, test_user, parts=[part])

        assert 'custom' in html

    def test_template_omits_parts_section_when_none(self, app, sample_vehicle, test_user):
        html = self._render(app, sample_vehicle, test_user)

        assert 'Parts (' not in html

    def test_report_route_includes_parts(self, auth_client, app, tmp_path,
                                         monkeypatch, sample_vehicle, test_user):
        rendered = self._fake_weasyprint(monkeypatch)
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        self._add_part(sample_vehicle, test_user, name='Oil Filter',
                       part_type='oil_filter', part_number='KN-204')

        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}/report')

        assert resp.status_code == 200
        assert resp.mimetype == 'application/pdf'
        assert 'Oil Filter' in rendered['html']
        assert 'KN-204' in rendered['html']

    def test_report_route_omits_parts_section_when_none(self, auth_client, app, tmp_path,
                                                        monkeypatch, sample_vehicle):
        rendered = self._fake_weasyprint(monkeypatch)
        app.config['UPLOAD_FOLDER'] = str(tmp_path)

        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}/report')

        assert resp.status_code == 200
        assert 'Parts (' not in rendered['html']
