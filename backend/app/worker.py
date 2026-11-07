"""Run independently: python -m app.worker [--once]."""
import argparse
from datetime import timedelta
import logging
import signal
import threading

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.models import Merchant, Observation
from app.notifications import deliver_pending
from app.scanner import scan_shop
from app.seed import seed

stop = threading.Event()


def run_once(session_factory=SessionLocal, settings=None):
    settings = settings or get_settings()
    with session_factory() as db:
        ids = list(db.scalars(select(Merchant.id).where(Merchant.enabled.is_(True), Merchant.next_check_at <= utcnow()).order_by(Merchant.next_check_at)))
    results = []
    for shop_id in ids:
        if stop.is_set():
            break
        results.append(scan_shop(session_factory, shop_id, settings))
        deliver_pending(session_factory, settings)
    deliver_pending(session_factory, settings)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Never log webhook URLs or Telegram credentials through HTTP client logging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with SessionLocal() as db:
        seed(db, settings)
    last_cleanup = utcnow() - timedelta(days=1)
    while not stop.is_set():
        run_once(settings=settings)
        if utcnow() - last_cleanup > timedelta(hours=24):
            with SessionLocal() as db:
                db.execute(delete(Observation).where(Observation.observed_at < utcnow() - timedelta(days=settings.history_retention_days)))
                db.commit()
            last_cleanup = utcnow()
        if args.once:
            break
        stop.wait(max(1, settings.worker_tick_seconds))


if __name__ == "__main__":
    main()
