from datetime import timedelta
import logging

from sqlalchemy import select, text, update

from app.adapters import ADAPTERS
from app.adapters.base import ShopClient, SourceError
from app.db import utcnow
from app.events import ingest
from app.models import Merchant, Observation, Offer, WatchTarget
from app.notifications import enqueue_event

log = logging.getLogger(__name__)
SHOP_LOCK_NAMESPACE = 1245856346


def claim_shop(session_factory, shop_id: int, force=False, process_lock_held=False) -> bool:
    now = utcnow()
    with session_factory() as db:
        query = update(Merchant).where(Merchant.id == shop_id, Merchant.enabled.is_(True))
        if not process_lock_held:
            query = query.where(Merchant.locked_until.is_(None) | (Merchant.locked_until < now))
        if not force:
            query = query.where(Merchant.next_check_at <= now)
        result = db.execute(query.values(locked_until=now + timedelta(minutes=45), last_attempt_at=now, requested_at=None))
        db.commit()
        return bool(result.rowcount)


def mark_source_unknown(db, merchant, reason):
    for offer in db.scalars(select(Offer).where(Offer.merchant_id == merchant.id)):
        if offer.availability != "unknown":
            db.add(Observation(offer_id=offer.id, price_minor=offer.price_minor, currency=offer.currency, availability="unknown"))
        offer.availability = "unknown"
        offer.source_error = reason[:500]


def scan_shop(session_factory, shop_id: int, settings, transport=None, force=False) -> dict:
    with session_factory() as db:
        bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        # A separate transaction owns the process lock across ORM commits.
        # PostgreSQL releases it on connection loss, including a hard restart.
        with bind.connect() as connection:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_xact_lock(:namespace, :shop_id)"),
                {"namespace": SHOP_LOCK_NAMESPACE, "shop_id": shop_id},
            ).scalar()
            if not acquired:
                return {"skipped": True}
            return _scan_shop(session_factory, shop_id, settings, transport, force, process_lock_held=True)
    return _scan_shop(session_factory, shop_id, settings, transport, force)


def _scan_shop(session_factory, shop_id: int, settings, transport=None, force=False, process_lock_held=False) -> dict:
    if not claim_shop(session_factory, shop_id, force, process_lock_held):
        return {"skipped": True}
    with session_factory() as db:
        merchant = db.get(Merchant, shop_id)
        client = ShopClient(merchant.base_url, settings, transport=transport)
        try:
            adapter_type = ADAPTERS.get(merchant.adapter)
            if adapter_type is None:
                raise SourceError("Unknown shop adapter")
            adapter = adapter_type(client, merchant.config)
            result = adapter.discover()
            # Explicit watches cover older products outside the bounded discovery window.
            watches = list(db.scalars(select(WatchTarget).where(WatchTarget.merchant_id == shop_id, WatchTarget.enabled.is_(True))))
            for watch in watches:
                try:
                    watched = adapter.fetch_url(watch.url)
                    if not watched:
                        raise SourceError("No matching product variant found")
                    result.offers.extend(watched)
                    watch.last_checked_at = utcnow()
                    watch.last_error = None
                except SourceError as exc:
                    watch.last_error = str(exc)[:500]
                    result.warnings.append(f"Watch {watch.id}: {exc}")
            unique = {item.external_id: item for item in result.offers}
            count, event_count = 0, 0
            for item in unique.values():
                offer, events = ingest(db, merchant, item)
                if offer:
                    count += 1
                else:
                    old_offer = db.scalar(select(Offer).where(Offer.merchant_id == merchant.id, Offer.external_id == item.external_id))
                    if old_offer is not None:
                        old_offer.excluded = True
                        old_offer.availability = "unknown"
                        old_offer.source_error = "Produktzuordnung nicht ausreichend belegt; kein automatischer Preisvergleich."
                for event in events:
                    enqueue_event(db, event)
                    event_count += 1
            if result.scanned_count == 0 and not result.offers:
                raise SourceError("Empty source catalog; no successful check recorded")
            merchant.last_success_at = utcnow()
            merchant.error_count = 0
            warnings = result.warnings[:5]
            if result.coverage_limited:
                warnings.append("Katalogauszug: Ältere Produkte bitte zusätzlich per Direktlink beobachten.")
            merchant.last_error = "; ".join(warnings)[:2000] or None
            merchant.last_offer_count = count
            merchant.last_scanned_count = result.scanned_count
            merchant.next_check_at = utcnow() + timedelta(seconds=max(60, merchant.interval_seconds))
            merchant.locked_until = None
            db.commit()
            log.info("shop=%s scanned=%s relevant=%s events=%s warnings=%s", merchant.slug, result.scanned_count, count, event_count, len(result.warnings))
            return {"shop": merchant.slug, "scanned": result.scanned_count, "offers": count, "events": event_count, "warnings": warnings}
        except Exception as exc:
            db.rollback()
            merchant = db.get(Merchant, shop_id)
            reason = str(exc)[:500] if isinstance(exc, SourceError) else f"Scan failed ({type(exc).__name__}); see worker logs"
            merchant.error_count += 1
            merchant.last_error = reason
            merchant.next_check_at = utcnow() + timedelta(seconds=min(21600, max(60, merchant.interval_seconds) * 2 ** min(merchant.error_count, 6)))
            merchant.locked_until = None
            mark_source_unknown(db, merchant, reason)
            db.commit()
            log.error("shop=%s error=%s", merchant.slug, reason)
            if not isinstance(exc, SourceError):
                # Do not log arbitrary exception strings that could contain URLs/secrets.
                log.error("unexpected scan exception type=%s", type(exc).__name__)
            return {"shop": merchant.slug, "error": reason}
        finally:
            client.close()
