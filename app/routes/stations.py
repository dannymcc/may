from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from flask_babel import gettext as _
from app import db
from app.utils import parse_decimal
from app.models import FuelStation, FuelPriceHistory
from app.services.uk_fuel_prices import UKFuelPriceService

bp = Blueprint('stations', __name__, url_prefix='/stations')


@bp.route('/')
@login_required
def index():
    """List all fuel stations (system-wide, visible to all users)"""
    stations = FuelStation.query.order_by(
        FuelStation.is_favorite.desc(),
        FuelStation.times_used.desc()
    ).all()

    return render_template(
        'stations/index.html',
        stations=stations,
        uk_fuel_enabled=UKFuelPriceService.is_enabled(),
    )


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Add a new fuel station"""
    if request.method == 'POST':
        station = FuelStation(
            user_id=current_user.id,
            name=request.form.get('name'),
            brand=request.form.get('brand'),
            address=request.form.get('address'),
            city=request.form.get('city'),
            postcode=request.form.get('postcode'),
            notes=request.form.get('notes'),
            is_favorite=request.form.get('is_favorite') == 'on',
        )

        # Optional coordinates
        if request.form.get('latitude'):
            station.latitude = parse_decimal(request.form.get('latitude'))
        if request.form.get('longitude'):
            station.longitude = parse_decimal(request.form.get('longitude'))

        db.session.add(station)
        db.session.commit()

        flash(_('Station "%(name)s" added') % {'name': station.name}, 'success')
        return redirect(url_for('stations.index'))

    return render_template('stations/form.html', station=None)


@bp.route('/<int:station_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(station_id):
    """Edit a fuel station"""
    station = db.get_or_404(FuelStation, station_id)

    if request.method == 'POST':
        station.name = request.form.get('name')
        station.brand = request.form.get('brand')
        station.address = request.form.get('address')
        station.city = request.form.get('city')
        station.postcode = request.form.get('postcode')
        station.notes = request.form.get('notes')
        station.is_favorite = request.form.get('is_favorite') == 'on'

        if request.form.get('latitude'):
            station.latitude = parse_decimal(request.form.get('latitude'))
        else:
            station.latitude = None
        if request.form.get('longitude'):
            station.longitude = parse_decimal(request.form.get('longitude'))
        else:
            station.longitude = None

        db.session.commit()
        flash(_('Station updated'), 'success')
        return redirect(url_for('stations.index'))

    return render_template('stations/form.html', station=station)


@bp.route('/<int:station_id>/favorite', methods=['POST'])
@login_required
def toggle_favorite(station_id):
    """Toggle favorite status"""
    station = db.get_or_404(FuelStation, station_id)

    station.is_favorite = not station.is_favorite
    db.session.commit()

    return jsonify({'success': True, 'is_favorite': station.is_favorite})


@bp.route('/<int:station_id>/delete', methods=['POST'])
@login_required
def delete(station_id):
    """Delete a fuel station"""
    station = db.get_or_404(FuelStation, station_id)

    name = station.name
    db.session.delete(station)
    db.session.commit()

    flash(_('Station "%(name)s" deleted') % {'name': name}, 'success')
    return redirect(url_for('stations.index'))


@bp.route('/api/list')
@login_required
def api_list():
    """Get list of stations for autocomplete/selection"""
    stations = FuelStation.query.order_by(
        FuelStation.is_favorite.desc(),
        FuelStation.times_used.desc()
    ).all()

    return jsonify([{
        'id': s.id,
        'name': s.name,
        'brand': s.brand,
        'address': s.address,
        'is_favorite': s.is_favorite
    } for s in stations])


@bp.route('/<int:station_id>/prices')
@login_required
def price_history(station_id):
    """View price history for a station"""
    station = db.get_or_404(FuelStation, station_id)

    # Get price history ordered by date
    price_records = FuelPriceHistory.query.filter_by(station_id=station_id).order_by(
        FuelPriceHistory.date.desc()
    ).limit(50).all()

    prices = price_records
    prices_json = [
        {
            'date': p.date.isoformat() if p.date else None,
            'fuel_type': p.fuel_type,
            'price_per_unit': p.price_per_unit,
        }
        for p in price_records
    ]

    return render_template(
        'stations/prices.html',
        station=station,
        prices=prices,
        prices_json=prices_json,
        uk_fuel_enabled=UKFuelPriceService.is_enabled(),
    )


def _flash_uk_refresh(stats):
    """Summarise a UK fuel price refresh as flash messages"""
    if stats['matched']:
        flash(
            _('Updated %(prices)s live prices from %(matched)s forecourts')
            % {'prices': stats['prices'], 'matched': stats['matched']},
            'success',
        )
    else:
        flash(
            _('No matching forecourts found. Check the station postcodes.'),
            'info',
        )

    if stats['errors']:
        flash(
            _('Some retailer feeds could not be read: %(errors)s')
            % {'errors': ', '.join(stats['errors'][:3])},
            'warning',
        )


@bp.route('/uk-prices/refresh', methods=['POST'])
@login_required
def refresh_uk_prices():
    """Pull live UK forecourt prices for every saved station"""
    if not UKFuelPriceService.is_enabled():
        flash(_('UK fuel prices are not enabled. An admin can turn them on in Settings.'), 'error')
        return redirect(url_for('stations.index'))

    stats = UKFuelPriceService.refresh_prices()
    _flash_uk_refresh(stats)

    return redirect(url_for('stations.index'))


@bp.route('/<int:station_id>/uk-prices/refresh', methods=['POST'])
@login_required
def refresh_station_uk_prices(station_id):
    """Pull live UK forecourt prices for a single station"""
    station = db.get_or_404(FuelStation, station_id)

    if not UKFuelPriceService.is_enabled():
        flash(_('UK fuel prices are not enabled. An admin can turn them on in Settings.'), 'error')
        return redirect(url_for('stations.price_history', station_id=station.id))

    stats = UKFuelPriceService.refresh_prices([station])
    _flash_uk_refresh(stats)

    return redirect(url_for('stations.price_history', station_id=station.id))


@bp.route('/prices/<int:price_id>/delete', methods=['POST'])
@login_required
def delete_price(price_id):
    """Delete a single fuel price history entry.

    Lets users clean up stale or orphan rows in the Cheapest Fuel table
    (e.g. entries left behind by test logs or pre-cleanup-logic versions).
    """
    price = db.get_or_404(FuelPriceHistory, price_id)

    if price.user_id != current_user.id:
        flash(_('You can only delete your own price entries'), 'error')
        return redirect(url_for('stations.price_history', station_id=price.station_id))

    station_id = price.station_id
    db.session.delete(price)
    db.session.commit()

    flash(_('Price entry deleted'), 'success')
    return redirect(url_for('stations.price_history', station_id=station_id))


@bp.route('/cheapest')
@login_required
def cheapest():
    """Show cheapest stations based on most recent prices"""
    # Get most recent price for each station
    subquery = db.session.query(
        FuelPriceHistory.station_id,
        func.max(FuelPriceHistory.date).label('max_date')
    ).group_by(FuelPriceHistory.station_id).subquery()

    latest_prices = db.session.query(FuelPriceHistory).join(
        subquery,
        db.and_(
            FuelPriceHistory.station_id == subquery.c.station_id,
            FuelPriceHistory.date == subquery.c.max_date
        )
    ).order_by(FuelPriceHistory.price_per_unit.asc()).all()

    # Group by fuel type
    prices_by_type = {}
    for price in latest_prices:
        fuel_type = price.fuel_type
        if fuel_type not in prices_by_type:
            prices_by_type[fuel_type] = []
        prices_by_type[fuel_type].append(price)

    return render_template('stations/cheapest.html', prices_by_type=prices_by_type)
