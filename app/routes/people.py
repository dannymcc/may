import os
import uuid
from datetime import datetime, date
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _
from werkzeug.utils import secure_filename
from app import db
from app.models import Person, PersonTask, Reminder, CalendarEvent, RELATIONSHIP_TYPES, PERSON_TASK_STATUSES, PERSON_TASK_PRIORITIES, REMINDER_TYPES

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

    apply_task_status(task, status)
    db.session.commit()

    return {'ok': True, 'task_id': task.id, 'status': task.status}


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

    return render_template('people/view.html',
                           person=person,
                           tasks_by_status=tasks_by_status,
                           task_statuses=PERSON_TASK_STATUSES,
                           task_priorities=PERSON_TASK_PRIORITIES,
                           stats=stats,
                           reminders=reminders,
                           reminder_types=REMINDER_TYPES,
                           calendar_events=calendar_events,
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
            )
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the due date.'), 'error')
            return render_template('people/task_form.html', person=person, task=None,
                                   task_statuses=PERSON_TASK_STATUSES,
                                   task_priorities=PERSON_TASK_PRIORITIES)

        if not task.title:
            flash(_('Please enter a task title'), 'error')
            return render_template('people/task_form.html', person=person, task=None,
                                   task_statuses=PERSON_TASK_STATUSES,
                                   task_priorities=PERSON_TASK_PRIORITIES)

        # Keep the timestamps consistent with the status it was created in
        apply_task_status(task, task.status)

        db.session.add(task)
        db.session.commit()

        flash(_('Task "%(title)s" added successfully') % {'title': task.title}, 'success')
        return redirect(url_for('people.view', person_id=person.id))

    return render_template('people/task_form.html',
                           person=person,
                           task=None,
                           task_statuses=PERSON_TASK_STATUSES,
                           task_priorities=PERSON_TASK_PRIORITIES)


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
                                   task_priorities=PERSON_TASK_PRIORITIES)

        try:
            due_date_str = request.form.get('due_date')
            new_due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None
        except (ValueError, TypeError):
            flash(_('Invalid data submitted. Please check the due date.'), 'error')
            return render_template('people/task_form.html', person=person, task=task,
                                   task_statuses=PERSON_TASK_STATUSES,
                                   task_priorities=PERSON_TASK_PRIORITIES)

        if new_due_date != task.due_date:
            # Rescheduled — arm the due-date notification again
            task.notification_sent = False
        task.due_date = new_due_date

        task.title = title
        task.description = request.form.get('description') or None

        submitted_priority = request.form.get('priority')
        if submitted_priority in dict(PERSON_TASK_PRIORITIES):
            task.priority = submitted_priority

        submitted_status = request.form.get('status')
        if submitted_status in dict(PERSON_TASK_STATUSES):
            apply_task_status(task, submitted_status)

        db.session.commit()

        flash(_('Task updated successfully'), 'success')
        return redirect(url_for('people.view', person_id=person.id))

    return render_template('people/task_form.html',
                           person=person,
                           task=task,
                           task_statuses=PERSON_TASK_STATUSES,
                           task_priorities=PERSON_TASK_PRIORITIES)


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

    apply_task_status(task, status)
    db.session.commit()

    flash(_('Task "%(title)s" moved to %(status)s') % {
        'title': task.title,
        'status': dict(PERSON_TASK_STATUSES)[status]
    }, 'success')
    return redirect(url_for('people.view', person_id=person.id))
