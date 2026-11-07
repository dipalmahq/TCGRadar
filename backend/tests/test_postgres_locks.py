from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.db import utcnow
from app.models import Merchant, Offer
from app.scanner import SHOP_LOCK_NAMESPACE, scan_shop
from test_api_worker import catalog_transport


def postgres_engine(factory):
    with factory() as db:
        engine = db.get_bind()
    if engine.dialect.name != "postgresql":
        pytest.skip("Requires real PostgreSQL advisory locks")
    return engine


def test_postgres_recovers_abandoned_lease_after_process_restart(factory, settings):
    postgres_engine(factory)
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop.locked_until = utcnow() + timedelta(minutes=45)
        shop.next_check_at = utcnow() - timedelta(minutes=1)
        shop_id = shop.id
        db.commit()
    result = scan_shop(factory, shop_id, settings, catalog_transport())
    assert result["offers"] == 1
    with factory() as db:
        assert db.get(Merchant, shop_id).locked_until is None


def test_postgres_does_not_overlap_an_active_scan(factory, settings):
    engine = postgres_engine(factory)
    with factory() as db:
        shop_id = db.scalar(select(Merchant.id))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT pg_try_advisory_xact_lock(:namespace, :shop_id)"), {"namespace": SHOP_LOCK_NAMESPACE, "shop_id": shop_id}).scalar()
        assert scan_shop(factory, shop_id, settings, catalog_transport(), force=True) == {"skipped": True}
        with factory() as db:
            assert db.scalar(select(Offer)) is None
    # Returning the connection rolls back its transaction and releases the lock.
    assert scan_shop(factory, shop_id, settings, catalog_transport(), force=True)["offers"] == 1
