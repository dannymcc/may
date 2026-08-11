import os
import uuid
from datetime import datetime, date
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from app import db, DATE_FORMATS
from app.models import (Person, PersonTask, PersonVehicleLink, Reminder, CalendarEvent,
                        Vehicle, RELATIONSHIP_TYPES, PERSON_TASK_STATUSES,
                        PERSON_TASK_PRIORITIES, PERSON_VEHICLE_ROLES, RECURRENCE_OPTIONS,
                        REMINDER_TYPES)
from app.routes.reminders import calculate_next_due_date

bp = Blueprint('people', __name__, url_prefix='/people')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Statuses that still need attention, in board order
OPEN_STATUSES = ('todo', 'in_progress', 'blocked')

# Sort order for the task board — urgent work first
PRIORITY_ORDER = {'urgent': 0, 'high': 1, 'normal': 2, 'low': 3}

# The unified board caps the Done column so years of finished work don't weigh
# down the page — the full history stays on each person's own page
BOARD_DONE_LIMIT = 25


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def sort_tasks(tasks):
    """Sort tasks by due date (undated last), then priority, then title"""
    return sorted(tasks, key=lambda t: (
        t.due_date is None,
        t.due_date or date.max,
        PRIORITY_ORDER.get(t.priority, 2),
        (t.title or '').lower()
    ))


def apply_task_status(task, status):
    """Set a task's status, keeping started_at/completed_at in step with it.

    Work that goes straight from "to do" to "done" still gets a start time so
    the board never shows a task that finished before it began.
    """
    now = datetime.utcnow()

    if status in ('in_progress', 'done') and not task.started_at:
        task.started_at = now

    if status == 'done':
        if not task.completed_at:
            task.completed_at = now
    else:
        task.completed_at = None

    task.status = status


def spawn_next_occurrence(task):
    """Create the next occurrence of a recurring task that was just completed.

    Returns the new open task, or None when the task does not recur or a
    matching open occurrence already exists (completed, un-completed and
    completed again — same guard as recurring reminders).
    """
    if not task.is_recurring():
        return None

    base_date = task.due_date or date.today()
    next_due = calculate_next_due_date(base_date, task.recurrence, task.recurrence_interval)

    # Any open occurrence of the same recurring task blocks a new spawn —
    # matching on due date alone would let a dateless task re-completed on a
    # different day (or a rescheduled occurrence) slip past the guard
    existing = PersonTask.query.filter(
        PersonTask.id != task.id,
        PersonTask.person_id == task.person_id,
        PersonTask.user_id == task.user_id,
        PersonTask.title == task.title,
        PersonTask.recurrence == task.recurrence,
        PersonTask.recurrence_interval == task.recurrence_interval,
        PersonTask.status.in_(OPEN_STATUSES),
    ).first()
    if existing:
        return None

    next_task = PersonTask(
        person_id=task.person_id,
        user_id=task.user_id,
        title=task.title,
        description=task.description,
        status='todo',
        priority=task.priority,
        due_date=next_due,
        recurrence=task.recurrence,
        recurrence_interval=task.recurrence_interval,
    )
    db.session.add(next_task)
    return next_task


def complete_with_recurrence(task, status):
    """Apply a status change, spawning the next occurrence on open -> done."""
    was_done = task.status == 'done'
    apply_task_status(task, status)
    if status == 'done' and not was_done:
        return spawn_next_occurrence(task)
    return None


def format_user_date(d):
    """Format a date with the current user's configured date format"""
    user_format = getattr(current_user, 'date_format', None) or 'DD/MM/YYYY'
    fmt = DATE_FORMATS.get(user_format, DATE_FORMATS['DD/MM/YYYY'])['default']
    return d.strftime(fmt)


def parse_recurrence_form(form):
    """Validated (recurrence, interval) pair from a submitted task form"""
    recurrence = form.get('recurrence', 'none')
    if recurrence not in dict(RECURRENCE_OPTIONS):
        recurrence = 'none'
    try:
        interval = max(int(form.get('recurrence_interval') or 1), 1)
    except (ValueError, TypeError):
        interval = 1
    return recurrence, interval


def get_task_summary(person):
    """Compact 'currently working on' summary used by the index cards"""
    open_tasks = sort_tasks([t for t in person.tasks.all() if t.status in OPEN_STATUSES])
    dated = [t for t in open_tasks if t.due_date]
    return {
        'active_count': len(open_tasks),
        'overdue_count': len([t for t in open_tasks if t.is_overdue()]),
        'next_task': dated[0] if dated else (open_tasks[0] if open_tasks else None)
    }


@bp.route('/')
@login_required
def index():
    show_archived = request.args.get('archived', 'false') == 'true'
    all_people = current_user.get_all_people()

    if show_archived:
        people = [p for p in all_people if not p.is_active]
    else:
        people = [p for p in all_people if p.is_active]

    archived_count = len([p for p in all_people if not p.is_active])

    summaries = {p.id: get_task_summary(p) for p in people}

    return render_template('people/index.html',
                           people=people,
                           summaries=summaries,
                           show_archived=show_archived,
                           archived_count=archived_count)


@bp.route('/board')
@login_required
def board():
    """Unified kanban of tasks across every person the user can see"""
    people = [p for p in current_user.get_all_people() if p.is_active]
    people_by_id = {p.id: p for p in people}

    person_filter = request.args.get('person', type=int)
    if person_filter not in people_by_id:
        person_filter = None
    priority_filter = request.args.get('priority')
    if priority_filter not in dict(PERSON_TASK_PRIORITIES):
        priority_filter = None

    tasks = []
    if people_by_id:
        query = PersonTask.query.filter(PersonTask.person_id.in_(people_by_id.keys()))
        if person_filter:
            query = query.filter(PersonTask.person_id == person_filter)
        if priority_filter:
            query = query.filter(PersonTask.priority == priority_filter)
        tasks = query.all()

    tasks_by_status = {}
    for value, label in PERSON_TASK_STATUSES:
        tasks_by_status[value] = sort_tasks([t for t in tasks if t.status == value])

    done = sorted(tasks_by_status.get('done', []),
                  key=lambda t: t.completed_at or datetime.min,
                  reverse=True)
    done_total = len(done)
    tasks_by_status['done'] = done[:BOARD_DONE_LIMIT]

    open_tasks = [t for t in tasks if t.status in OPEN_STATUSES]
    stats = {
        'active_tasks': len(open_tasks),
        'overdue_tasks': len([t for t in open_tasks if t.is_overdue()]),
        'done_tasks': done_total,
        'people_count': len({t.person_id for t in open_tasks}),
    }

    return render_template('people/board.html',
                           people=people,
                           tasks_by_status=tasks_by_status,
                           task_statuses=PERSON_TASK_STATUSES,
                           task_priorities=PERSON_TASK_PRIORITIES,
                           stats=stats,
                           done_total=done_total,
                           done_limit=BOARD_DONE_LIMIT,
                           person_filter=person_filter,
                           priority_filter=priority_filter,
                           today=date.today())


@bp.route('/tasks/<int:task_id>/move', methods=['POST'])
@login_required
def move_task(task_id):
    """JSON endpoint behind the unified board's drag-and-drop"""
    task = PersonTask.query.get_or_404(task_id)

    if task.person not in current_user.get_all_people():
        return {'error': 'Access denied'}, 403

    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in dict(PERSON_TASK_STATUSES):
        return {'error': 'Invalid status'}, 400

    next_task = complete_with_recurrence(task, status)
    db.session.commit()

    return {'ok': True, 'task_id': task.id, 'status': task.status,
            'next_task_id': next_task.id if next_task else None}


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        person = Person(
            owner_id=current_user.id,
            name=request.form.get('name'),
            relationship_type=(request.form.get('relationship_type')
                               if request.form.get('relationship_type') in dict(RELATIONSHIP_TYPES)
                               else 'coworker'),
            email=request.form.get('email') or None,
            phone=request.form.get('phone') or None,
            organization=request.form.get('organization') or None,
            role_title=request.form.get('role_title') or None,
            notes=request.form.get('notes') or None,
        )

        # Handle image upload
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                person.image_filename = filename

        db.session.add(person)
        db.session.commit()

        flash(_('%(name)s added successfully') % {'name': person.name}, 'success')
        return redirect(url_for('people.view', person_id=person.id))

    return render_template('people/form.html',
                           person=None,
                           relationship_types=RELATIONSHIP_TYPES)


@bp.route('/<int:person_id>')
@login_required
def view(person_id):
    person = Person.query.get_or_404(person_id)

    # Check access
    if person not in current_user.get_all_people():
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    # Group tasks into the board columns
    all_tasks = person.tasks.all()
    tasks_by_status = {}
    for value, label in PERSON_TASK_STATUSES:
        tasks_by_status[value] = sort_tasks([t for t in all_tasks if t.status == value])

    # Finished work reads better newest-first
    tasks_by_status['done'] = sorted(tasks_by_status.get('done', []),
                                     key=lambda t: t.completed_at or datetime.min,
                                     reverse=True)

    open_tasks = [t for t in all_tasks if t.status in OPEN_STATUSES]
    stats = {
        'total_tasks': len(all_tasks),
        'active_tasks': len(open_tasks),
        'overdue_tasks': len([t for t in open_tasks if t.is_overdue()]),
        'done_tasks': len(tasks_by_status.get('done', [])),
    }

    # Reminders raised against this person (not completed, soonest first)
    reminders = person.reminders.filter_by(is_completed=False).order_by(Reminder.due_date).all()

    # Calendar events from today onwards. Scoped to the viewer: a shared person
    # is visible to everyone on the instance, but calendar events are private to
    # the user who created them.
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    calendar_events = person.calendar_events.filter(
        CalendarEvent.user_id == current_user.id,
        CalendarEvent.start_at >= today_start
    ).order_by(CalendarEvent.start_at).limit(10).all()

    # Vehicles this person is connected to, scoped to what the viewer can see —
    # a shared person may be linked to another user's private vehicle
    linkable_vehicles = current_user.get_all_vehicles()
    visible_vehicle_ids = {v.id for v in linkable_vehicles}
    vehicle_links = [link for link
                     in person.vehicle_links.order_by(PersonVehicleLink.created_at)
                     if link.vehicle_id in visible_vehicle_ids]

    return render_template('people/view.html',
                           person=person,
                           tasks_by_status=tasks_by_status,
                           task_statuses=PERSON_TASK_STATUSES,
                           task_priorities=PERSON_TASK_PRIORITIES,
                           stats=stats,
                           reminders=reminders,
                           reminder_types=REMINDER_TYPES,
                           calendar_events=calendar_events,
                           vehicle_links=vehicle_links,
                           linkable_vehicles=linkable_vehicles,
                           vehicle_roles=PERSON_VEHICLE_ROLES,
                           today=today)


@bp.route('/<int:person_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(person_id):
    person = Person.query.get_or_404(person_id)

    # Check ownership
    if person.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    if request.method == 'POST':
        person.name = request.form.get('name')
        submitted_relationship = request.form.get('relationship_type')
        if submitted_relationship in dict(RELATIONSHIP_TYPES):
            person.relationship_type = submitted_relationship
        person.email = request.form.get('email') or None
        person.phone = request.form.get('phone') or None
        person.organization = request.form.get('organization') or None
        person.role_title = request.form.get('role_title') or None
        person.notes = request.form.get('notes') or None

        person.is_active = request.form.get('is_active') == 'on'
        person.is_shared = request.form.get('is_shared') == 'on'

        # Handle image upload
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                # Delete old image
                if person.image_filename:
                    old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], person.image_filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)

                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                person.image_filename = filename

        db.session.commit()
        flash(_('Person updated successfully'), 'success')
        return redirect(url_for('people.view', person_id=person.id))

    return render_template('people/form.html',
                           person=person,
                           relationship_types=RELATIONSHIP_TYPES)


@bp.route('/<int:person_id>/delete', methods=['POST'])
@login_required
def delete(person_id):
    person = Person.query.get_or_404(person_id)

    # Check ownership
    if person.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    # Delete image
    if person.image_filename:
        old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], person.image_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    db.session.delete(person)
    db.session.commit()
    flash(_('Person deleted successfully'), 'success')
    return redirect(url_for('people.index'))


@bp.route('/<int:person_id>/share', methods=['POST'])
@login_required
def share(person_id):
    """Make this person visible to every user on the instance"""
    person = Person.query.get_or_404(person_id)

    # Check ownership
    if person.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    person.is_shared = True
    db.session.commit()
    flash(_('%(name)s is now shared with everyone on this instance') % {'name': person.name}, 'success')
    return redirect(url_for('people.view', person_id=person.id))


@bp.route('/<int:person_id>/unshare', methods=['POST'])
@login_required
def unshare(person_id):
    """Stop sharing this person with other users on the instance"""
    person = Person.query.get_or_404(person_id)

    # Check ownership
    if person.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    person.is_shared = False
    db.session.commit()
    flash(_('%(name)s is no longer shared') % {'name': person.name}, 'success')
    return redirect(url_for('people.view', person_id=person.id))


@bp.route('/<int:person_id>/archive', methods=['POST'])
@login_required
def archive(person_id):
    person = Person.query.get_or_404(person_id)

    # Check ownership
    if person.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    person.is_active = False
    db.session.commit()
    flash(_('%(name)s has been archived') % {'name': person.name}, 'success')
    return redirect(url_for('people.index'))


@bp.route('/<int:person_id>/unarchive', methods=['POST'])
@login_required
def unarchive(person_id):
    person = Person.query.get_or_404(person_id)

    # Check ownership
    if person.owner_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    person.is_active = True
    db.session.commit()
    flash(_('%(name)s has been restored') % {'name': person.name}, 'success')
    return redirect(url_for('people.index'))


# --- Person Tasks CRUD ---

@bp.route('/<int:person_id>/tasks/new', methods=['GET', 'POST'])
@login_required
def new_task(person_id):
    """Add a new task for a person"""
    person = Person.query.get_or_404(person_id)

    # Check access
    if person not in current_user.get_all_people():
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    if request.method == 'POST':
        status = request.form.get('status')
        if status not in dict(PERSON_TASK_STATUSES):
            status = 'todo'
        priority = request.form.get('priority')
        if priority not in dict(PERSON_TASK_PRIORITIES):
            priority = 'normal'

        recurrence, recurrence_interval = parse_recurrence_form(request.form)

        try:
            due_date_str = request.form.get('due_date')
            task = PersonTask(
                person_id=person.id,
                user_id=current_user.id,
                title=request.form.get('title'),
                description=request.form.get('description') or None,
                status=status,
                priority=priority,
                due_date=datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None,
                recurrence=recurrence,
                recurrence_interval=recurrence_interval,
            )
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the due date.'), 'error')
            return render_template('people/task_form.html', person=person, task=None,
                                   task_statuses=PERSON_TASK_STATUSES,
                                   task_priorities=PERSON_TASK_PRIORITIES,
                                   recurrence_options=RECURRENCE_OPTIONS)

        if not task.title:
            flash(_('Please enter a task title'), 'error')
            return render_template('people/task_form.html', person=person, task=None,
                                   task_statuses=PERSON_TASK_STATUSES,
                                   task_priorities=PERSON_TASK_PRIORITIES,
                                   recurrence_options=RECURRENCE_OPTIONS)

        # Keep the timestamps consistent with the status it was created in
        apply_task_status(task, task.status)
        db.session.add(task)

        # A recurring task logged directly as done still schedules its next round
        next_task = spawn_next_occurrence(task) if task.status == 'done' else None
        db.session.commit()

        flash(_('Task "%(title)s" added successfully') % {'title': task.title}, 'success')
        if next_task:
            flash(_('Next occurrence scheduled for %(date)s') % {'date': format_user_date(next_task.due_date)}, 'success')
        return redirect(url_for('people.view', person_id=person.id))

    return render_template('people/task_form.html',
                           person=person,
                           task=None,
                           task_statuses=PERSON_TASK_STATUSES,
                           task_priorities=PERSON_TASK_PRIORITIES,
                           recurrence_options=RECURRENCE_OPTIONS)


@bp.route('/<int:person_id>/tasks/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(person_id, task_id):
    """Edit an existing task"""
    person = Person.query.get_or_404(person_id)
    task = PersonTask.query.get_or_404(task_id)

    # Check access
    if person not in current_user.get_all_people():
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    # Verify task belongs to person
    if task.person_id != person.id:
        flash(_('Task not found'), 'error')
        return redirect(url_for('people.view', person_id=person.id))

    if request.method == 'POST':
        title = request.form.get('title')
        if not title:
            flash(_('Please enter a task title'), 'error')
            return render_template('people/task_form.html', person=person, task=task,
                                   task_statuses=PERSON_TASK_STATUSES,
                                   task_priorities=PERSON_TASK_PRIORITIES,
                                   recurrence_options=RECURRENCE_OPTIONS)

        try:
            due_date_str = request.form.get('due_date')
            new_due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the due date.'), 'error')
            return render_template('people/task_form.html', person=person, task=task,
                                   task_statuses=PERSON_TASK_STATUSES,
                                   task_priorities=PERSON_TASK_PRIORITIES,
                                   recurrence_options=RECURRENCE_OPTIONS)

        if new_due_date != task.due_date:
            # Rescheduled — arm the due-date notification again
            task.notification_sent = False
        task.due_date = new_due_date

        task.title = title
        task.description = request.form.get('description') or None

        submitted_priority = request.form.get('priority')
        if submitted_priority in dict(PERSON_TASK_PRIORITIES):
            task.priority = submitted_priority

        task.recurrence, task.recurrence_interval = parse_recurrence_form(request.form)

        next_task = None
        submitted_status = request.form.get('status')
        if submitted_status in dict(PERSON_TASK_STATUSES):
            next_task = complete_with_recurrence(task, submitted_status)

        db.session.commit()

        flash(_('Task updated successfully'), 'success')
        if next_task:
            flash(_('Next occurrence scheduled for %(date)s') % {'date': format_user_date(next_task.due_date)}, 'success')
        return redirect(url_for('people.view', person_id=person.id))

    return render_template('people/task_form.html',
                           person=person,
                           task=task,
                           task_statuses=PERSON_TASK_STATUSES,
                           task_priorities=PERSON_TASK_PRIORITIES,
                           recurrence_options=RECURRENCE_OPTIONS)


@bp.route('/<int:person_id>/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(person_id, task_id):
    """Delete a task"""
    person = Person.query.get_or_404(person_id)
    task = PersonTask.query.get_or_404(task_id)

    # Check access
    if person not in current_user.get_all_people():
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    # Verify task belongs to person
    if task.person_id != person.id:
        flash(_('Task not found'), 'error')
        return redirect(url_for('people.view', person_id=person.id))

    db.session.delete(task)
    db.session.commit()

    flash(_('Task deleted successfully'), 'success')
    return redirect(url_for('people.view', person_id=person.id))


# --- Person <-> Vehicle links ---

def _link_redirect(person_id, vehicle_id):
    """Send the user back to whichever page they linked from"""
    if request.form.get('return_to') == 'vehicle' and vehicle_id:
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))
    return redirect(url_for('people.view', person_id=person_id))


@bp.route('/<int:person_id>/vehicles/link', methods=['POST'])
@login_required
def link_vehicle(person_id):
    """Associate a vehicle with this person in a given role"""
    person = Person.query.get_or_404(person_id)

    # Check access to both sides of the link
    if person not in current_user.get_all_people():
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    vehicle_id = request.form.get('vehicle_id', type=int)
    vehicle = Vehicle.query.get(vehicle_id) if vehicle_id else None
    if not vehicle or vehicle not in current_user.get_all_vehicles():
        flash(_('Vehicle not found'), 'error')
        return redirect(url_for('people.view', person_id=person.id))

    role = request.form.get('role')
    if role not in dict(PERSON_VEHICLE_ROLES):
        role = 'other'
    notes = (request.form.get('notes') or '').strip() or None

    existing = PersonVehicleLink.query.filter_by(
        person_id=person.id, vehicle_id=vehicle.id, role=role).first()
    if existing:
        flash(_('%(name)s is already linked to %(vehicle)s as %(role)s') % {
            'name': person.name, 'vehicle': vehicle.name,
            'role': existing.role_label}, 'error')
        return _link_redirect(person.id, vehicle.id)

    link = PersonVehicleLink(person_id=person.id, vehicle_id=vehicle.id,
                             role=role, notes=notes)
    db.session.add(link)
    try:
        db.session.commit()
    except IntegrityError:
        # Concurrent submit lost the race against the unique constraint
        db.session.rollback()
        flash(_('%(name)s is already linked to %(vehicle)s as %(role)s') % {
            'name': person.name, 'vehicle': vehicle.name,
            'role': dict(PERSON_VEHICLE_ROLES).get(role, role)}, 'error')
        return _link_redirect(person.id, vehicle.id)

    flash(_('%(name)s linked to %(vehicle)s as %(role)s') % {
        'name': person.name, 'vehicle': vehicle.name, 'role': link.role_label}, 'success')
    return _link_redirect(person.id, vehicle.id)


@bp.route('/<int:person_id>/vehicles/<int:link_id>/unlink', methods=['POST'])
@login_required
def unlink_vehicle(person_id, link_id):
    """Remove a person-vehicle association.

    Access to either end of the link suffices: the person page shows the
    control to people-viewers, the vehicle page to vehicle-viewers, and a
    vehicle owner must be able to clear links shown on their own vehicle.
    """
    person = Person.query.get_or_404(person_id)
    link = PersonVehicleLink.query.get_or_404(link_id)

    if link.person_id != person.id:
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    can_see_person = person in current_user.get_all_people()
    can_see_vehicle = link.vehicle in current_user.get_all_vehicles()
    if not (can_see_person or can_see_vehicle or current_user.is_admin):
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    vehicle_id = link.vehicle_id
    db.session.delete(link)
    db.session.commit()

    flash(_('Link removed'), 'success')
    return _link_redirect(person.id, vehicle_id)


@bp.route('/<int:person_id>/tasks/<int:task_id>/status', methods=['POST'])
@login_required
def task_status(person_id, task_id):
    """Move a task to another column on the board"""
    person = Person.query.get_or_404(person_id)
    task = PersonTask.query.get_or_404(task_id)

    # Check access
    if person not in current_user.get_all_people():
        flash(_('Access denied'), 'error')
        return redirect(url_for('people.index'))

    # Verify task belongs to person
    if task.person_id != person.id:
        flash(_('Task not found'), 'error')
        return redirect(url_for('people.view', person_id=person.id))

    status = request.form.get('status')
    if status not in dict(PERSON_TASK_STATUSES):
        flash(_('Invalid status'), 'error')
        return redirect(url_for('people.view', person_id=person.id))

    next_task = complete_with_recurrence(task, status)
    db.session.commit()

    flash(_('Task "%(title)s" moved to %(status)s') % {
        'title': task.title,
        'status': dict(PERSON_TASK_STATUSES)[status]
    }, 'success')
    if next_task:
        flash(_('Next occurrence scheduled for %(date)s') % {'date': format_user_date(next_task.due_date)}, 'success')
    return redirect(url_for('people.view', person_id=person.id))
