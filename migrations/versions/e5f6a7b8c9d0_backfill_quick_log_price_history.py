"""backfill fuel price history for quick-log entries (#252)

Quick Fuel Log entries never wrote a FuelPriceHistory row, so they were
counted in a station's "used N times" overview but were missing from the
station chart/price-history view. The route is now fixed to record the row
at save time; this migration repairs existing data so historic quick logs
show up in the chart without the user having to re-edit each one.

The repair is model-driven: for every fuel log that names a saved station and
has a price, we recreate the missing price-history row (matching what the
route now does). It only touches logs that resolve to a station and have no
matching price-history row yet, so full-form logs (which already have one) and
unmatched free-text stations are left untouched. The station usage counter is
deliberately not changed — quick saves already incremented it, so recreating
only the price-history row brings the chart back in step with the overview.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-15 00:00:00.000000

"""
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.orm import Session

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    tables = inspector.get_table_names()
    if 'fuel_logs' not in tables or 'fuel_stations' not in tables \
            or 'fuel_price_history' not in tables:
        return

    # Import lazily so the migration only depends on the models when it runs.
    from app.models import FuelLog, FuelStation, FuelPriceHistory

    session = Session(bind=bind)
    try:
        stations = session.query(FuelStation).all()
        if not stations:
            session.close()
            return

        # Resolve a log's free-text station name to a saved station. The quick
        # dropdown stored either the plain name or "Name (Brand)", so index both
        # forms per owning user.
        station_lookup = {}
        for station in stations:
            if not station.name:
                continue
            station_lookup.setdefault((station.user_id, station.name), station)
            if station.brand:
                combined = '%s (%s)' % (station.name, station.brand)
                station_lookup.setdefault((station.user_id, combined), station)

        logs = session.query(FuelLog).filter(
            FuelLog.station.isnot(None),
            FuelLog.price_per_unit.isnot(None),
        ).all()

        for log in logs:
            if not log.station or not log.price_per_unit or not log.date:
                continue
            station = station_lookup.get((log.user_id, log.station))
            if not station:
                continue

            existing = session.query(FuelPriceHistory).filter_by(
                station_id=station.id,
                user_id=log.user_id,
                date=log.date,
                price_per_unit=log.price_per_unit,
            ).first()
            if existing:
                continue

            fuel_type = log.fuel_type
            if not fuel_type and log.vehicle is not None:
                fuel_type = log.vehicle.fuel_type
            fuel_type = fuel_type or 'petrol'

            session.add(FuelPriceHistory(
                station_id=station.id,
                user_id=log.user_id,
                date=log.date,
                fuel_type=fuel_type,
                price_per_unit=log.price_per_unit,
            ))

        session.commit()
    except Exception:
        # A data backfill must never break the upgrade chain. If anything goes
        # wrong, leave existing data untouched; users can still repair a log by
        # re-selecting its station in the editor.
        session.rollback()
    finally:
        session.close()


def downgrade():
    # Data-only backfill; there is nothing to reverse.
    pass
