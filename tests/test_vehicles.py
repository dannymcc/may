import json
import re
import pytest
from datetime import date
from app import db
from app.models import Vehicle, Expense


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


class TestVehicleExpenseChart:
    """Per-vehicle expense breakdown chart (#287)."""

    def _add_expense(self, vehicle, user, category, cost):
        expense = Expense(
            vehicle_id=vehicle.id,
            user_id=user.id,
            date=date(2024, 3, 1),
            category=category,
            description=f'{category} spend',
            cost=cost,
        )
        db.session.add(expense)
        db.session.commit()
        return expense

    def _chart_data(self, body):
        """The category totals handed to the chart, as rendered into the page."""
        match = re.search(r'const categoryData = (\{.*?\});', body, re.DOTALL)
        assert match, 'chart data not found in page'
        return json.loads(match.group(1))

    def test_chart_shows_categories(self, auth_client, sample_vehicle, test_user):
        self._add_expense(sample_vehicle, test_user, 'maintenance', 100.0)
        self._add_expense(sample_vehicle, test_user, 'insurance', 250.5)
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'canvas id="expensesChart"' in body
        assert self._chart_data(body) == {'Maintenance': 100.0, 'Insurance': 250.5}

    def test_chart_excludes_other_vehicles(self, auth_client, sample_vehicle, test_user):
        self._add_expense(sample_vehicle, test_user, 'maintenance', 100.0)
        other = Vehicle(
            owner_id=test_user.id,
            name='Other Car',
            vehicle_type='car',
            fuel_type='petrol',
        )
        db.session.add(other)
        db.session.commit()
        self._add_expense(other, test_user, 'insurance', 250.5)

        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert self._chart_data(resp.data.decode()) == {'Maintenance': 100.0}

    def test_no_chart_without_expenses(self, auth_client, sample_vehicle):
        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')
        assert resp.status_code == 200
        assert b'canvas id="expensesChart"' not in resp.data


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
        assert db.session.get(Vehicle, vehicle_id) is None


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

    def test_template_shows_fuel_sales_tax(self, app, sample_vehicle, test_user,
                                          sample_fuel_log):
        """#225 — the report an accountant sees carries the tax and its total."""
        sample_fuel_log.sales_tax = 7.8
        db.session.commit()

        html = self._render(app, sample_vehicle, test_user,
                            fuel_logs=[sample_fuel_log])

        assert 'Sales Tax' in html
        assert 'Sales tax total' in html
        assert '7.80' in html

    def test_template_omits_sales_tax_column_when_unused(self, app, sample_vehicle,
                                                         test_user, sample_fuel_log):
        html = self._render(app, sample_vehicle, test_user,
                            fuel_logs=[sample_fuel_log])

        assert 'Sales Tax' not in html
        assert 'Sales tax total' not in html

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


class TestVehiclePhotos:
    """#147 — a vehicle keeps a gallery of photos, stored as attachments."""

    @staticmethod
    def _file(name='photo.png', content=b'fake-image'):
        import io
        return (io.BytesIO(content), name)

    def _upload(self, client, vehicle_id, *files, follow_redirects=True):
        return client.post(
            f'/vehicles/{vehicle_id}/photos',
            data={'photo': list(files) or [self._file()]},
            content_type='multipart/form-data',
            follow_redirects=follow_redirects,
        )

    @staticmethod
    def _add_photo(vehicle, filename='existing.png', upload_folder=None):
        from app.models import Attachment
        if upload_folder:
            (upload_folder / filename).write_bytes(b'fake-image')
        photo = Attachment(filename=filename, original_filename=filename,
                           file_type='png', vehicle_id=vehicle.id)
        db.session.add(photo)
        db.session.commit()
        return photo

    def test_upload_requires_auth(self, client, sample_vehicle):
        resp = self._upload(client, sample_vehicle.id, follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_upload_stores_photos(self, auth_client, app, tmp_path, sample_vehicle):
        from app.models import Attachment
        app.config['UPLOAD_FOLDER'] = str(tmp_path)

        resp = self._upload(auth_client, sample_vehicle.id,
                            self._file('front.png'), self._file('rear.jpg'))

        assert resp.status_code == 200
        photos = Attachment.query.filter_by(vehicle_id=sample_vehicle.id).all()
        assert len(photos) == 2
        assert {p.original_filename for p in photos} == {'front.png', 'rear.jpg'}
        for photo in photos:
            assert (tmp_path / photo.filename).exists()
        assert b'2 photos added' in resp.data

    def test_upload_without_a_file_says_so(self, auth_client, app, tmp_path,
                                           sample_vehicle):
        from app.models import Attachment
        app.config['UPLOAD_FOLDER'] = str(tmp_path)

        resp = auth_client.post(f'/vehicles/{sample_vehicle.id}/photos',
                                data={'photo': []},
                                content_type='multipart/form-data',
                                follow_redirects=True)

        assert resp.status_code == 200
        assert b'No photos were selected' in resp.data
        assert Attachment.query.filter_by(vehicle_id=sample_vehicle.id).count() == 0

    def test_first_photo_becomes_main_image(self, auth_client, app, tmp_path,
                                            sample_vehicle):
        from app.models import Attachment
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        assert sample_vehicle.image_filename is None

        self._upload(auth_client, sample_vehicle.id, self._file('front.png'))

        db.session.refresh(sample_vehicle)
        photo = Attachment.query.filter_by(vehicle_id=sample_vehicle.id).one()
        assert sample_vehicle.image_filename == photo.filename

    def test_upload_keeps_existing_main_image(self, auth_client, app, tmp_path,
                                              sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        sample_vehicle.image_filename = 'chosen.png'
        db.session.commit()

        self._upload(auth_client, sample_vehicle.id, self._file('front.png'))

        db.session.refresh(sample_vehicle)
        assert sample_vehicle.image_filename == 'chosen.png'

    def test_unsupported_file_type_is_skipped(self, auth_client, app, tmp_path,
                                              sample_vehicle):
        from app.models import Attachment
        app.config['UPLOAD_FOLDER'] = str(tmp_path)

        resp = self._upload(auth_client, sample_vehicle.id,
                            self._file('manual.pdf'), self._file('front.png'))

        assert resp.status_code == 200
        photos = Attachment.query.filter_by(vehicle_id=sample_vehicle.id).all()
        assert [p.original_filename for p in photos] == ['front.png']
        assert b'manual.pdf' in resp.data

    def test_non_owner_cannot_upload(self, client, app, tmp_path, sample_vehicle):
        from app.models import Attachment, User
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        sample_vehicle.is_shared = True
        other = User(username='other_user', email='other@example.com')
        other.set_password('OtherPass123!')
        db.session.add(other)
        db.session.commit()
        client.post('/auth/login', data={'username': 'other_user',
                                         'password': 'OtherPass123!'},
                    follow_redirects=True)

        self._upload(client, sample_vehicle.id, self._file('front.png'))

        assert Attachment.query.filter_by(vehicle_id=sample_vehicle.id).count() == 0

    def test_view_lists_photos(self, auth_client, app, tmp_path, sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        self._add_photo(sample_vehicle, 'existing.png', tmp_path)

        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')

        assert resp.status_code == 200
        assert b'existing.png' in resp.data
        assert b'Photos' in resp.data

    def test_view_shows_carousel_arrows_for_several_photos(self, auth_client, app,
                                                           tmp_path, sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        sample_vehicle.image_filename = 'main.png'
        db.session.commit()
        self._add_photo(sample_vehicle, 'second.png', tmp_path)

        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')

        assert b'stepVehicleCarousel' in resp.data
        assert b'1 / 2' in resp.data

    def test_view_omits_carousel_arrows_for_single_photo(self, auth_client, app,
                                                         tmp_path, sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        sample_vehicle.image_filename = 'main.png'
        db.session.commit()

        resp = auth_client.get(f'/vehicles/{sample_vehicle.id}')

        assert b'stepVehicleCarousel' not in resp.data

    def test_set_primary_photo(self, auth_client, app, tmp_path, sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        photo = self._add_photo(sample_vehicle, 'gallery.png', tmp_path)

        resp = auth_client.post(
            f'/vehicles/{sample_vehicle.id}/photos/{photo.id}/primary',
            follow_redirects=True)

        assert resp.status_code == 200
        db.session.refresh(sample_vehicle)
        assert sample_vehicle.image_filename == 'gallery.png'

    def test_set_primary_keeps_previous_main_image_in_gallery(self, auth_client, app,
                                                              tmp_path, sample_vehicle):
        from app.models import Attachment
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        (tmp_path / 'abc123_old.png').write_bytes(b'fake-image')
        sample_vehicle.image_filename = 'abc123_old.png'
        db.session.commit()
        photo = self._add_photo(sample_vehicle, 'gallery.png', tmp_path)

        auth_client.post(f'/vehicles/{sample_vehicle.id}/photos/{photo.id}/primary',
                         follow_redirects=True)

        kept = Attachment.query.filter_by(filename='abc123_old.png').one()
        assert kept.vehicle_id == sample_vehicle.id
        assert kept.original_filename == 'old.png'
        assert (tmp_path / 'abc123_old.png').exists()

    def test_photo_of_another_vehicle_is_rejected(self, auth_client, app, tmp_path,
                                                  test_user, sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        other = Vehicle(owner_id=test_user.id, name='Other Car', vehicle_type='car')
        db.session.add(other)
        db.session.commit()
        photo = self._add_photo(other, 'other.png', tmp_path)

        auth_client.post(f'/vehicles/{sample_vehicle.id}/photos/{photo.id}/primary',
                         follow_redirects=True)

        db.session.refresh(sample_vehicle)
        assert sample_vehicle.image_filename is None

    def test_delete_photo_removes_record_and_file(self, auth_client, app, tmp_path,
                                                  sample_vehicle):
        from app.models import Attachment
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        photo = self._add_photo(sample_vehicle, 'gallery.png', tmp_path)

        resp = auth_client.post(
            f'/vehicles/{sample_vehicle.id}/photos/{photo.id}/delete',
            follow_redirects=True)

        assert resp.status_code == 200
        assert db.session.get(Attachment, photo.id) is None
        assert not (tmp_path / 'gallery.png').exists()

    def test_deleting_main_photo_falls_back_to_another(self, auth_client, app,
                                                       tmp_path, sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        first = self._add_photo(sample_vehicle, 'first.png', tmp_path)
        self._add_photo(sample_vehicle, 'second.png', tmp_path)
        sample_vehicle.image_filename = 'first.png'
        db.session.commit()

        auth_client.post(f'/vehicles/{sample_vehicle.id}/photos/{first.id}/delete',
                         follow_redirects=True)

        db.session.refresh(sample_vehicle)
        assert sample_vehicle.image_filename == 'second.png'

    def test_deleting_last_photo_clears_main_image(self, auth_client, app, tmp_path,
                                                   sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        photo = self._add_photo(sample_vehicle, 'only.png', tmp_path)
        sample_vehicle.image_filename = 'only.png'
        db.session.commit()

        auth_client.post(f'/vehicles/{sample_vehicle.id}/photos/{photo.id}/delete',
                         follow_redirects=True)

        db.session.refresh(sample_vehicle)
        assert sample_vehicle.image_filename is None

    def test_new_main_image_upload_keeps_gallery_file(self, auth_client, app,
                                                      tmp_path, sample_vehicle):
        """Replacing the main image must not delete a file the gallery still uses."""
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        self._add_photo(sample_vehicle, 'gallery.png', tmp_path)
        sample_vehicle.image_filename = 'gallery.png'
        db.session.commit()

        auth_client.post(f'/vehicles/{sample_vehicle.id}/edit', data={
            'name': sample_vehicle.name,
            'vehicle_type': 'car',
            'tracking_unit': 'mileage',
            'image': self._file('new.png'),
        }, content_type='multipart/form-data', follow_redirects=True)

        db.session.refresh(sample_vehicle)
        assert sample_vehicle.image_filename != 'gallery.png'
        assert (tmp_path / 'gallery.png').exists()

    def test_deleting_vehicle_removes_photo_files(self, auth_client, app, tmp_path,
                                                  sample_vehicle):
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        self._add_photo(sample_vehicle, 'gallery.png', tmp_path)

        auth_client.post(f'/vehicles/{sample_vehicle.id}/delete',
                         follow_redirects=True)

        assert not (tmp_path / 'gallery.png').exists()

    def test_viewer_without_edit_rights_sees_no_controls(self, client, app, tmp_path,
                                                         sample_vehicle):
        from app.models import User
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        sample_vehicle.is_shared = True
        db.session.commit()
        self._add_photo(sample_vehicle, 'gallery.png', tmp_path)
        other = User(username='other_user', email='other@example.com')
        other.set_password('OtherPass123!')
        db.session.add(other)
        db.session.commit()
        client.post('/auth/login', data={'username': 'other_user',
                                         'password': 'OtherPass123!'},
                    follow_redirects=True)

        resp = client.get(f'/vehicles/{sample_vehicle.id}')

        assert resp.status_code == 200
        assert b'gallery.png' in resp.data
        assert b'Set as main' not in resp.data
