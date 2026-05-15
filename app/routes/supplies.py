from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import Supply

bp = Blueprint('supplies', __name__, url_prefix='/supplies')


@bp.route('/')
@login_required
def index():
    supplies = Supply.query.filter_by(user_id=current_user.id).order_by(Supply.name).all()
    return render_template('supplies/index.html', supplies=supplies)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        quantity = request.form.get('quantity', '').strip()
        if not name or not quantity:
            flash('Product name and quantity are required.', 'error')
            return render_template('supplies/form.html', supply=None)
        supply = Supply(user_id=current_user.id, name=name, quantity=quantity)
        db.session.add(supply)
        db.session.commit()
        flash('Supply added.', 'success')
        return redirect(url_for('supplies.index'))
    return render_template('supplies/form.html', supply=None)


@bp.route('/<int:supply_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(supply_id):
    supply = Supply.query.get_or_404(supply_id)
    if supply.user_id != current_user.id:
        abort(403)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        quantity = request.form.get('quantity', '').strip()
        if not name or not quantity:
            flash('Product name and quantity are required.', 'error')
            return render_template('supplies/form.html', supply=supply)
        supply.name = name
        supply.quantity = quantity
        db.session.commit()
        flash('Supply updated.', 'success')
        return redirect(url_for('supplies.index'))
    return render_template('supplies/form.html', supply=supply)


@bp.route('/<int:supply_id>/delete', methods=['POST'])
@login_required
def delete(supply_id):
    supply = Supply.query.get_or_404(supply_id)
    if supply.user_id != current_user.id:
        abort(403)
    db.session.delete(supply)
    db.session.commit()
    flash('Supply deleted.', 'success')
    return redirect(url_for('supplies.index'))
