"""Run independently: python -m app.worker [--once]."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import timedelta
import logging
import signal
import threading

from sqlalchemy import delete, select, text

from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.models import Merchant, Observation
from app.notifications import deliver_pending
from app.scanner import aware, refresh_due, scan_shop
from app.refresh import source_blocked, watch_due
from app.seed import seed

stop = threading.Event()


def run_once(session_factory=SessionLocal, settings=None):
    settings = settings or get_settings()
    with session_factory() as db:
        ids = [m.id for m in db.scalars(select(Merchant).where(Merchant.enabled.is_(True)).order_by(Merchant.next_check_at))
               if aware(m.next_check_at) <= utcnow() or refresh_due(m)]
    results = []
    def process(shop_id):
        if stop.is_set():
            return []
        refreshed = scan_shop(session_factory, shop_id, settings, refresh_only=True)
        if stop.is_set():
            return [refreshed]
        return [refreshed, scan_shop(session_factory, shop_id, settings)]
    with ThreadPoolExecutor(max_workers=max(1, min(settings.worker_concurrency, 8))) as pool:
        for future in as_completed([pool.submit(process, shop_id) for shop_id in ids]):
            results.extend(future.result())
            deliver_pending(session_factory, settings)
    deliver_pending(session_factory, settings)
    return results


def run_merchant_once(shop_id, session_factory=SessionLocal, settings=None):
    """One independent merchant turn; watched products have their own deadline."""
    settings = settings or get_settings()
    now = utcnow()
    with session_factory() as db:
        merchant = db.get(Merchant, shop_id)
        if merchant is None:
            return {'skipped': True}
        merchant.worker_heartbeat_at = now
        db.commit()
        if source_blocked(merchant, now) or (merchant.source_ready_at and aware(merchant.source_ready_at) > now):
            return {'skipped': True}
        watched = watch_due(merchant, now)
        refresh = refresh_due(merchant, now)
        catalog = aware(merchant.next_check_at) <= now
        last_job = (merchant.crawl_state or {}).get('last_job')
    if watched:
        return scan_shop(session_factory, shop_id, settings, refresh_only=True, watch_only=True)
    if refresh and (not catalog or last_job != 'refresh'):
        return scan_shop(session_factory, shop_id, settings, refresh_only=True)
    if catalog:
        return scan_shop(session_factory, shop_id, settings, include_watches=False)
    return {'skipped': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    roles = parser.add_mutually_exclusive_group()
    roles.add_argument('--merchant', help='Only this configured merchant; never sends notifications')
    roles.add_argument('--notifications-only', action='store_true', help='Only deliver queued notifications and maintain history')
    args = parser.parse_args()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Never log webhook URLs or Telegram credentials through HTTP client logging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    shop_id = None
    with SessionLocal() as db:
        if args.merchant:
            shop_id = db.scalar(select(Merchant.id).where(Merchant.slug == args.merchant))
            if shop_id is None:
                raise SystemExit('Merchant must be seeded before starting its worker')
        elif not args.notifications_only:
            seed(db, settings)
    if args.notifications_only:
        with notification_owner(SessionLocal) as acquired:
            if not acquired:
                raise SystemExit('Notification worker already running')
            serve(args, settings, shop_id)
    else:
        serve(args, settings, shop_id)


@contextmanager
def notification_owner(factory):
    with factory() as db:
        engine = db.get_bind()
    if engine.dialect.name != 'postgresql':
        yield True
        return
    with engine.connect() as connection:
        acquired = connection.execute(text('SELECT pg_try_advisory_xact_lock(1245856347, 1)')).scalar()
        yield bool(acquired)


def serve(args, settings, shop_id):
    last_cleanup = utcnow() - timedelta(days=1)
    while not stop.is_set():
        try:
            if args.notifications_only:
                deliver_pending(SessionLocal, settings)
            elif shop_id is not None:
                run_merchant_once(shop_id, settings=settings)
            else:
                run_once(settings=settings)
        except Exception as exc:
            logging.getLogger(__name__).error('worker role=%s failure=%s', args.merchant or 'notifications', type(exc).__name__)
        if args.notifications_only and utcnow() - last_cleanup > timedelta(hours=24):
            with SessionLocal() as db:
                db.execute(delete(Observation).where(Observation.observed_at < utcnow() - timedelta(days=settings.history_retention_days)))
                db.commit()
            last_cleanup = utcnow()
        if args.once:
            break
        stop.wait(settings.notification_tick_seconds if args.notifications_only else max(1, settings.worker_tick_seconds))


if __name__ == "__main__":
    main()
