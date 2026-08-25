import os
import uuid
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from flask_babel import gettext as _
from app import db
from app.models import Vehicle, Document, DOCUMENT_TYPES

bp = Blueprint('documents', __name__, url_prefix='/documents')

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'doc', 'docx', 'xlsx', 'xls', 'txt', 'csv', 'epub'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/')
@login_required
def index():
    """List all documents"""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    # Filter by vehicle if specified
    vehicle_filter = request.args.get('vehicle')

    query = Document.query.filter(Document.vehicle_id.in_(vehicle_ids))
    if vehicle_filter:
        query = query.filter(Document.vehicle_id == vehicle_filter)

    documents = query.order_by(Document.created_at.desc()).all()

    # Group by document type
    docs_by_type = {}
    for doc in documents:
        if doc.document_type not in docs_by_type:
            docs_by_type[doc.document_type] = []
        docs_by_type[doc.document_type].append(doc)

    return render_template('documents/index.html',
                           documents=documents,
                           docs_by_type=docs_by_type,
                           vehicles=vehicles,
                           vehicle_filter=vehicle_filter,
                           document_types=DOCUMENT_TYPES)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Upload a new document"""
    vehicles = current_user.get_all_vehicles()

    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id')
        vehicle = db.session.get(Vehicle, vehicle_id)

        if not vehicle or vehicle not in vehicles:
            flash(_('Invalid vehicle'), 'error')
            return redirect(url_for('documents.index'))

        # Handle file upload
        if 'file' not in request.files:
            flash(_('No file selected'), 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash(_('No file selected'), 'error')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            original_filename = secure_filename(file.filename)
            filename = f"doc_{uuid.uuid4().hex}_{original_filename}"
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            # Get file info
            file_size = os.path.getsize(file_path)
            file_type = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else None

            document = Document(
                vehicle_id=vehicle_id,
                user_id=current_user.id,
                title=request.form.get('title'),
                document_type=request.form.get('document_type'),
                description=request.form.get('description'),
                filename=filename,
                original_filename=original_filename,
                file_type=file_type,
                file_size=file_size,
                reference_number=request.form.get('reference_number'),
                remind_before_expiry=request.form.get('remind_before_expiry') == 'on',
                remind_days=int(request.form.get('remind_days') or 30),
            )

            if request.form.get('issue_date'):
                document.issue_date = datetime.strptime(request.form.get('issue_date'), '%Y-%m-%d').date()
            if request.form.get('expiry_date'):
                document.expiry_date = datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date()

            db.session.add(document)
            db.session.commit()

            flash(_('Document "%(title)s" uploaded') % {'title': document.title}, 'success')
            return redirect(url_for('documents.index'))
        else:
            flash(_('Invalid file type'), 'error')
            return redirect(request.url)

    selected_vehicle = request.args.get('vehicle_id')
    return render_template('documents/form.html',
                           document=None,
                           vehicles=vehicles,
                           selected_vehicle=selected_vehicle,
                           document_types=DOCUMENT_TYPES)


@bp.route('/<int:document_id>')
@login_required
def view(document_id):
    """View document details"""
    document = db.get_or_404(Document, document_id)
    vehicles = current_user.get_all_vehicles()

    if document.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('documents.index'))

    return render_template('documents/view.html',
                           document=document,
                           document_types=DOCUMENT_TYPES)


@bp.route('/<int:document_id>/download')
@login_required
def download(document_id):
    """Download a document"""
    document = db.get_or_404(Document, document_id)
    vehicles = current_user.get_all_vehicles()

    if document.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('documents.index'))

    return send_from_directory(
        current_app.config['UPLOAD_FOLDER'],
        document.filename,
        download_name=document.original_filename,
        as_attachment=True
    )


@bp.route('/<int:document_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(document_id):
    """Edit document metadata"""
    document = db.get_or_404(Document, document_id)
    vehicles = current_user.get_all_vehicles()

    if document.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('documents.index'))

    if request.method == 'POST':
        document.title = request.form.get('title')
        document.document_type = request.form.get('document_type')
        document.description = request.form.get('description')
        document.reference_number = request.form.get('reference_number')
        document.remind_before_expiry = request.form.get('remind_before_expiry') == 'on'
        document.remind_days = int(request.form.get('remind_days') or 30)

        if request.form.get('issue_date'):
            document.issue_date = datetime.strptime(request.form.get('issue_date'), '%Y-%m-%d').date()
        else:
            document.issue_date = None

        if request.form.get('expiry_date'):
            document.expiry_date = datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d').date()
        else:
            document.expiry_date = None

        db.session.commit()
        flash(_('Document updated'), 'success')
        return redirect(url_for('documents.view', document_id=document.id))

    return render_template('documents/form.html',
                           document=document,
                           vehicles=vehicles,
                           selected_vehicle=document.vehicle_id,
                           document_types=DOCUMENT_TYPES)


@bp.route('/<int:document_id>/delete', methods=['POST'])
@login_required
def delete(document_id):
    """Delete a document"""
    document = db.get_or_404(Document, document_id)
    vehicles = current_user.get_all_vehicles()

    if document.vehicle not in vehicles:
        flash(_('Access denied'), 'error')
        return redirect(url_for('documents.index'))

    # Delete file
    try:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], document.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass

    title = document.title
    db.session.delete(document)
    db.session.commit()

    flash(_('Document "%(title)s" deleted') % {'title': title}, 'success')
    return redirect(url_for('documents.index'))
