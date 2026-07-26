from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db
from app.models import Vehicle, VehicleNote
from app.security import sanitize_html

bp = Blueprint('notes', __name__, url_prefix='/notes')


def _get_accessible_vehicle(vehicle_id):
    """Return vehicle if current user has access, else None."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if vehicle not in current_user.get_all_vehicles():
        return None
    return vehicle


def _get_accessible_note(note_id):
    """Return note if current user has access to its vehicle, else None."""
    note = VehicleNote.query.get_or_404(note_id)
    if note.vehicle not in current_user.get_all_vehicles():
        return None
    return note


@bp.route('/')
@login_required
def index():
    """Centralized notes page listing notes for all accessible vehicles."""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    search = request.args.get('search', '').strip()

    query = VehicleNote.query.filter(VehicleNote.vehicle_id.in_(vehicle_ids))

    if search:
        query = query.filter(
            db.or_(
                VehicleNote.title.ilike(f'%{search}%'),
                VehicleNote.content.ilike(f'%{search}%')
            )
        )

    notes = query.order_by(VehicleNote.is_pinned.desc(), VehicleNote.updated_at.desc()).all()

    return render_template('notes/index.html',
                           vehicles=vehicles,
                           notes=notes,
                           search=search)


@bp.route('/vehicle/<int:vehicle_id>')
@login_required
def vehicle_notes(vehicle_id):
    """List notes for a specific vehicle."""
    vehicle = _get_accessible_vehicle(vehicle_id)
    if not vehicle:
        flash(_('Access denied'), 'error')
        return redirect(url_for('notes.index'))

    notes = vehicle.vehicle_notes.order_by(
        VehicleNote.is_pinned.desc(),
        VehicleNote.updated_at.desc()
    ).all()

    return render_template('notes/vehicle_index.html',
                           vehicle=vehicle,
                           notes=notes)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Create a new note."""
    vehicles = current_user.get_all_vehicles()
    if not vehicles:
        flash(_('You need at least one vehicle to add a note'), 'error')
        return redirect(url_for('vehicles.index'))

    vehicle_id = request.args.get('vehicle_id', type=int) or request.form.get('vehicle_id', type=int)
    selected_vehicle = None
    if vehicle_id:
        selected_vehicle = next((v for v in vehicles if v.id == vehicle_id), None)

    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id', type=int)
        vehicle = _get_accessible_vehicle(vehicle_id) if vehicle_id else None
        if not vehicle:
            flash(_('Invalid vehicle selected'), 'error')
            return redirect(url_for('notes.index'))

        title = (request.form.get('title') or '').strip()
        content = sanitize_html(request.form.get('content', ''))
        is_pinned = request.form.get('is_pinned') == '1'

        if not title:
            flash(_('Title is required'), 'error')
            return render_template('notes/form.html',
                                   vehicles=vehicles,
                                   selected_vehicle=vehicle,
                                   title=title,
                                   content=content,
                                   is_pinned=is_pinned), 400

        note = VehicleNote(
            vehicle_id=vehicle.id,
            user_id=current_user.id,
            title=title,
            content=content,
            is_pinned=is_pinned,
        )
        db.session.add(note)
        db.session.commit()

        flash(_('Note added successfully'), 'success')
        return redirect(url_for('notes.index'))

    return render_template('notes/form.html',
                           vehicles=vehicles,
                           selected_vehicle=selected_vehicle,
                           title='',
                           content='',
                           is_pinned=False)


@bp.route('/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(note_id):
    """Edit an existing note."""
    note = _get_accessible_note(note_id)
    if not note:
        flash(_('Access denied'), 'error')
        return redirect(url_for('notes.index'))

    vehicles = current_user.get_all_vehicles()

    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id', type=int)
        vehicle = _get_accessible_vehicle(vehicle_id) if vehicle_id else None
        if not vehicle:
            flash(_('Invalid vehicle selected'), 'error')
            return redirect(url_for('notes.index'))

        title = (request.form.get('title') or '').strip()
        content = sanitize_html(request.form.get('content', ''))
        is_pinned = request.form.get('is_pinned') == '1'

        if not title:
            flash(_('Title is required'), 'error')
            return render_template('notes/form.html',
                                   vehicles=vehicles,
                                   selected_vehicle=note.vehicle,
                                   note=note,
                                   title=title,
                                   content=content,
                                   is_pinned=is_pinned), 400

        note.vehicle_id = vehicle.id
        note.title = title
        note.content = content
        note.is_pinned = is_pinned
        db.session.commit()

        flash(_('Note updated successfully'), 'success')
        return redirect(url_for('notes.index'))

    return render_template('notes/form.html',
                           vehicles=vehicles,
                           selected_vehicle=note.vehicle,
                           note=note,
                           title=note.title,
                           content=note.content,
                           is_pinned=note.is_pinned)


@bp.route('/<int:note_id>/delete', methods=['POST'])
@login_required
def delete(note_id):
    """Delete a note."""
    note = _get_accessible_note(note_id)
    if not note:
        flash(_('Access denied'), 'error')
        return redirect(url_for('notes.index'))

    vehicle_id = note.vehicle_id
    db.session.delete(note)
    db.session.commit()

    flash(_('Note deleted successfully'), 'success')

    return_to = request.args.get('return_to')
    if return_to == 'vehicle':
        return redirect(url_for('notes.vehicle_notes', vehicle_id=vehicle_id))
    return redirect(url_for('notes.index'))
