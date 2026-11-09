from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import func, select, text, update

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


def mark_source_unknown(db, merchant, reason, verified_external_ids=()):
    query = select(Offer).where(Offer.merchant_id == merchant.id, Offer.excluded.is_(False))
    if verified_external_ids:
        query = query.where(Offer.external_id.not_in(verified_external_ids))
    for offer in db.scalars(query):
        if offer.availability != "unknown":
            db.add(Observation(offer_id=offer.id, price_minor=offer.price_minor, currency=offer.currency, availability="unknown"))
        offer.availability = "unknown"
        offer.source_error = reason[:500]
        offer.next_stock_check_at = utcnow()


def scan_shop(session_factory, shop_id: int, settings, transport=None, force=False, refresh_only=False, watch_only=False, include_watches=True) -> dict:
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
            return _scan_shop(session_factory, shop_id, settings, transport, force, process_lock_held=True, refresh_only=refresh_only,
                              watch_only=watch_only, include_watches=include_watches)
    return _scan_shop(session_factory, shop_id, settings, transport, force, refresh_only=refresh_only,
                      watch_only=watch_only, include_watches=include_watches)


def _scan_shop(session_factory, shop_id: int, settings, transport=None, force=False, process_lock_held=False, refresh_only=False, watch_only=False, include_watches=True) -> dict:
    if refresh_only:
        return _refresh_shop(session_factory, shop_id, settings, transport, process_lock_held, watch_only)
    if not claim_shop(session_factory, shop_id, force, process_lock_held):
        return {"skipped": True}
    with session_factory() as db:
        merchant = db.get(Merchant, shop_id)
        client = ShopClient(merchant.base_url, settings, transport=transport)
        client.defer_until(aware(merchant.source_ready_at) if merchant.source_ready_at else None)
        try:
            adapter_type = ADAPTERS.get(merchant.adapter)
            if adapter_type is None:
                raise SourceError("Unknown shop adapter")
            adapter = adapter_type(client, merchant.config)
            full_catalog = bool(merchant.config.get("full_catalog"))
            previous = merchant.crawl_state or {}
            continuing = full_catalog and previous.get("cursor") is not None
            progress = dict(previous) if continuing else {
                "started_at": utcnow().isoformat(), "completed_at": previous.get("completed_at"),
                "scanned": 0, "pages": 0, "unresolved": 0,
                "refresh": previous.get("refresh", {}), "retry_at": previous.get("retry_at"),
                "watch": previous.get("watch", {}), "last_job": previous.get("last_job"),
            }
            result = adapter.discover_batch(previous.get("cursor")) if full_catalog else adapter.discover()
            # Explicit watches cover older products outside the bounded discovery window.
            watches = list(db.scalars(select(WatchTarget).where(WatchTarget.merchant_id == shop_id, WatchTarget.enabled.is_(True)).order_by(WatchTarget.last_checked_at.asc().nulls_first(), WatchTarget.id))) if include_watches else []
            watch_requests = 0
            for watch in watches:
                if watch.last_checked_at and aware(watch.last_checked_at) > utcnow() - timedelta(seconds=settings.watch_interval_seconds):
                    continue
                if result.retry_after_seconds is not None:
                    watch.last_error = result.source_error or "Source retry delay active; watch deferred"
                    continue
                if watch_requests >= max(1, min(settings.refresh_batch_size, 20)):
                    continue
                watch_requests += 1
                watch.last_attempt_at = utcnow()
                try:
                    watched = adapter.fetch_url(watch.url)
                    if not watched:
                        raise SourceError("No matching product variant found")
                    result.offers.extend(watched)
                    watch.last_checked_at = utcnow()
                    watch.last_error = None
                    watch.next_check_at = utcnow() + timedelta(seconds=settings.watch_interval_seconds)
                except SourceError as exc:
                    result.offers.extend(getattr(exc, "offers", []))
                    watch.last_error = str(exc)[:500]
                    watch.next_check_at = utcnow() + timedelta(seconds=max(settings.watch_interval_seconds, exc.retry_after_seconds or 0))
                    result.warnings.append(f"Watch {watch.id}: {exc}")
                    if exc.retry_after_seconds is not None:
                        result.retry_after_seconds = exc.retry_after_seconds
            unique = {item.external_id: item for item in result.offers}
            count, event_count = 0, 0
            verified_ids = []
            for item in unique.values():
                offer, events = ingest(db, merchant, item, settings.refresh_interval_seconds)
                if offer:
                    count += 1
                    if item.availability_error is None and item.availability != "unknown":
                        verified_ids.append(item.external_id)
                else:
                    old_offer = db.scalar(select(Offer).where(Offer.merchant_id == merchant.id, Offer.external_id == item.external_id))
                    if old_offer is not None:
                        old_offer.excluded = True
                        old_offer.availability = "unknown"
                        old_offer.source_error = "Produktzuordnung nicht ausreichend belegt; kein automatischer Preisvergleich."
                for event in events:
                    enqueue_event(db, event)
                    event_count += 1
            if not full_catalog and result.scanned_count == 0 and not result.offers:
                raise SourceError("Empty source catalog; no successful check recorded")
            warnings = result.warnings[:5]
            if result.coverage_limited and not full_catalog:
                warnings.append("Katalogauszug: Ältere Produkte bitte zusätzlich per Direktlink beobachten.")
            if full_catalog:
                progress["scanned"] += result.scanned_count
                progress["pages"] += result.pages_scanned
                progress["unresolved"] += len(result.warnings) if result.coverage_limited else 0
                progress["cursor"] = result.next_cursor
                if result.complete and not result.source_error:
                    progress["completed_at"] = utcnow().isoformat()
                merchant.crawl_state = progress
                merchant.last_offer_count = db.scalar(select(func.count(Offer.id)).where(
                    Offer.merchant_id == merchant.id, Offer.excluded.is_(False)))
                merchant.last_scanned_count = progress["scanned"]
            else:
                merchant.last_offer_count = count
                merchant.last_scanned_count = result.scanned_count
            if result.source_error:
                mark_source_unknown(db, merchant, result.source_error, verified_ids)
                merchant.error_count += 1
                merchant.last_error = result.source_error[:2000]
                delay = max(result.retry_after_seconds or 60, min(21600, 60 * 2 ** min(merchant.error_count, 8)))
            else:
                merchant.last_success_at = utcnow()
                merchant.error_count = 0
                merchant.last_error = "; ".join(warnings)[:2000] or None
                delay = max(max(60, merchant.interval_seconds) if result.complete else 5,
                            result.retry_after_seconds or 0)
            merchant.next_check_at = utcnow() + timedelta(seconds=delay)
            if result.retry_after_seconds is not None:
                merchant.crawl_state = {**merchant.crawl_state, "retry_at": merchant.next_check_at.isoformat()}
            merchant.locked_until = None
            merchant.crawl_state = {**merchant.crawl_state, 'last_job': 'catalog'}
            set_source_ready(merchant, client)
            db.commit()
            log.info("shop=%s scanned=%s relevant=%s events=%s warnings=%s", merchant.slug, result.scanned_count, count, event_count, len(result.warnings))
            output = {"shop": merchant.slug, "scanned": result.scanned_count, "offers": count, "events": event_count, "warnings": warnings}
            if full_catalog:
                output.update(catalog_complete=result.complete, pages=progress["pages"], scanned_total=progress["scanned"])
            if result.source_error:
                output["error"] = result.source_error
            return output
        except Exception as exc:
            db.rollback()
            merchant = db.get(Merchant, shop_id)
            reason = str(exc)[:500] if isinstance(exc, SourceError) else f"Scan failed ({type(exc).__name__}); see worker logs"
            merchant.error_count += 1
            merchant.last_error = reason
            delay = max(min(21600, max(60, merchant.interval_seconds) * 2 ** min(merchant.error_count, 6)),
                        getattr(exc, "retry_after_seconds", None) or 0)
            merchant.next_check_at = utcnow() + timedelta(seconds=delay)
            merchant.locked_until = None
            mark_source_unknown(db, merchant, reason)
            set_source_ready(merchant, client)
            db.commit()
            log.error("shop=%s error=%s", merchant.slug, reason)
            if not isinstance(exc, SourceError):
                # Do not log arbitrary exception strings that could contain URLs/secrets.
                log.error("unexpected scan exception type=%s", type(exc).__name__)
            return {"shop": merchant.slug, "error": reason}
        finally:
            client.close()


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def refresh_due(merchant, now=None):
    now = now or utcnow()
    state = merchant.crawl_state or {}
    deadlines = [state.get('retry_at'), (state.get('refresh') or {}).get('next_at')]
    if not merchant.enabled or any(value and aware(datetime.fromisoformat(value)) > now for value in deadlines):
        return False
    return not (merchant.error_count and aware(merchant.next_check_at) > now)


def set_source_ready(merchant, client):
    if client.requests:
        merchant.source_ready_at = utcnow() + timedelta(seconds=max(0, client.settings.request_delay_seconds))



def _refresh_shop(session_factory, shop_id, settings, transport, process_lock_held, watch_only=False):
    from app.refresh import refresh_shop
    return refresh_shop(session_factory, shop_id, settings, transport, process_lock_held, watch_only)
