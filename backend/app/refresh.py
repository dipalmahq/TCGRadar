"""Persisted watch deadlines and fair, oldest-due stock refreshes."""
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

from app.adapters import ADAPTERS
from app.adapters.base import ShopClient, SourceError
from app.db import utcnow
from app.events import ingest
from app.models import Merchant, Offer, Product, SearchRule, WatchTarget
from app.notifications import enqueue_event, rule_targets
from app.scanner import aware, claim_shop, mark_source_unknown, set_source_ready


def source_blocked(merchant, now=None):
    now = now or utcnow()
    retry = (merchant.crawl_state or {}).get('retry_at')
    return (not merchant.enabled or bool(retry and aware(datetime.fromisoformat(retry)) > now)
            or bool(merchant.error_count and aware(merchant.next_check_at) > now))


def watch_due(merchant, now=None):
    now = now or utcnow()
    deadline = ((merchant.crawl_state or {}).get('watch') or {}).get('next_at')
    return not source_blocked(merchant, now) and (merchant.watch_requested_at is not None or not (deadline and aware(datetime.fromisoformat(deadline)) > now))


def product_url(url, merchant):
    # Shopify's product response contains all variants. Keep exact URLs on other
    # platforms, where query parameters can select distinct pack sizes.
    if merchant.adapter == 'shopify':
        p = urlsplit(url)
        return urlunsplit((p.scheme, p.netloc, p.path, '', ''))
    return url


def refresh_shop(factory, shop_id, settings, transport=None, process_lock_held=False, watch_only=False):
    key = 'watch' if watch_only else 'refresh'
    now = utcnow()
    with factory() as db:
        merchant = db.get(Merchant, shop_id)
        if merchant is None or source_blocked(merchant, now):
            return {'skipped': True}
        deadline = ((merchant.crawl_state or {}).get(key) or {}).get('next_at')
        if deadline and aware(datetime.fromisoformat(deadline)) > now and not (watch_only and merchant.watch_requested_at):
            return {'skipped': True}
    if not claim_shop(factory, shop_id, force=True, process_lock_held=process_lock_held):
        return {'skipped': True}
    with factory() as db:
        merchant = db.get(Merchant, shop_id)
        client = ShopClient(merchant.base_url, settings, transport=transport)
        client.defer_until(aware(merchant.source_ready_at) if merchant.source_ready_at else None)
        stats = dict((merchant.crawl_state or {}).get(key) or {})
        verified, checked, event_count, fresh_items, failures = [], 0, 0, [], []
        selected = []
        try:
            adapter = ADAPTERS[merchant.adapter](client, merchant.config)
            rules = list(db.scalars(select(SearchRule).where(SearchRule.enabled.is_(True))))
            watches = list(db.scalars(select(WatchTarget).where(WatchTarget.merchant_id == shop_id, WatchTarget.enabled.is_(True))))
            offers = list(db.scalars(select(Offer).where(Offer.merchant_id == shop_id, Offer.excluded.is_(False)).options(
                joinedload(Offer.product).joinedload(Product.expansion))))
            groups = {}
            deadlines = []
            def target(url, deadline, offer=None, watch=None):
                deadlines.append(deadline)
                if deadline > now:
                    return
                canonical = product_url(url, merchant)
                group = groups.setdefault(canonical, {'url': canonical, 'due': deadline, 'offers': [], 'watches': []})
                group['due'] = min(group['due'], deadline)
                if offer is not None:
                    group['offers'].append(offer)
                if watch is not None:
                    group['watches'].append(watch)
            for watch in watches:
                deadline = aware(watch.next_check_at) if watch.next_check_at else now
                target(watch.url, deadline, watch=watch)
            for offer in offers:
                watched = any(rule_targets(rule, offer, offer.product) for rule in rules)
                canonical = product_url(offer.url, merchant)
                if canonical in groups:
                    groups[canonical]['offers'].append(offer)
                    continue
                if watch_only and not watched:
                    continue
                deadline = aware(offer.next_stock_check_at) if offer.next_stock_check_at else now
                if watched and not offer.source_error:
                    deadline = min(deadline, aware(offer.last_seen_at) + timedelta(seconds=settings.watch_interval_seconds))
                target(offer.url, deadline, offer=offer)
            limit = max(1, min(settings.refresh_batch_size, 20))
            selected = sorted(groups.values(), key=lambda g: (g['due'], g['url']))[:limit]
            for group in selected:
                for offer in group['offers']:
                    offer.stock_attempted_at = utcnow()
                for watch in group['watches']:
                    watch.last_attempt_at = utcnow()
                try:
                    fetched = adapter.fetch_url(group['url'])
                    if not fetched:
                        raise SourceError('No matching product variant found')
                    fresh_items.extend(fetched)
                    present = {o.external_id for o in fetched}
                    for offer in group['offers']:
                        if offer.external_id not in present:
                            failures.append((offer, 'No matching product variant found'))
                    for watch in group['watches']:
                        # Exact-variant watches must not succeed using a sibling.
                        from urllib.parse import parse_qs
                        wanted = parse_qs(urlsplit(watch.url).query).get('variant', [None])[0]
                        watch.next_check_at = utcnow() + timedelta(seconds=settings.watch_interval_seconds)
                        if wanted and wanted not in present:
                            watch.last_error = 'No matching product variant found'
                        else:
                            watch.last_checked_at, watch.last_error = utcnow(), None
                    checked += 1
                except SourceError as error:
                    fresh_items.extend(getattr(error, 'offers', []))
                    if not any(t in str(error) for t in ('HTTP 404', 'No unambiguous', 'No matching', 'Product not found')):
                        raise
                    failures.extend((offer, str(error)) for offer in group['offers'])
                    for watch in group['watches']:
                        watch.last_error = str(error)[:500]
                        watch.next_check_at = utcnow() + timedelta(seconds=max(300, settings.watch_interval_seconds))
                    checked += 1
            # Network requests finish before shared expansion/product inserts.
            for item in {o.external_id: o for o in fresh_items}.values():
                offer, events = ingest(db, merchant, item, settings.refresh_interval_seconds)
                if offer:
                    watched = any(rule_targets(rule, offer, offer.product) for rule in rules)
                    interval = settings.watch_interval_seconds if watched else settings.refresh_interval_seconds
                    offer.next_stock_check_at = utcnow() + timedelta(seconds=interval)
                    if item.availability != 'unknown' and not item.availability_error:
                        verified.append(item.external_id)
                else:
                    old = db.scalar(select(Offer).where(Offer.merchant_id == shop_id, Offer.external_id == item.external_id))
                    if old:
                        old.excluded, old.availability = True, 'unknown'
                        old.source_error = 'Produktzuordnung nicht ausreichend belegt; kein automatischer Preisvergleich.'
                for event in events:
                    enqueue_event(db, event)
                    event_count += 1
            for offer, error in failures:
                offer.availability, offer.source_error = 'unknown', error[:500]
                offer.next_stock_check_at = utcnow() + timedelta(seconds=max(300, settings.refresh_interval_seconds))
                # last_seen_at remains the last successful source observation.
            next_at = (utcnow() + timedelta(seconds=max(1, settings.request_delay_seconds))) if len(groups) > limit else (
                min((d for d in deadlines if d > now), default=utcnow() + timedelta(seconds=60 if watch_only else settings.refresh_interval_seconds)))
            stats.update(last_at=utcnow().isoformat(), checked=checked, error=None, next_at=next_at.isoformat(), remaining_due=max(0, len(groups)-limit))
            merchant.crawl_state = {**merchant.crawl_state, key: stats, 'last_job': key}
            if watch_only:
                db.execute(update(Merchant).where(Merchant.id == shop_id, Merchant.watch_requested_at <= now).values(watch_requested_at=None))
            merchant.last_offer_count = db.scalar(select(func.count(Offer.id)).where(Offer.merchant_id == shop_id, Offer.excluded.is_(False)))
            merchant.locked_until = None
            set_source_ready(merchant, client)
            db.commit()
            return {'shop': merchant.slug, 'refreshed': checked, 'events': event_count, 'job': key}
        except Exception as error:
            # No partial ORM transaction or false notifications survive a failed
            # shared-data write. Network/429 errors retain verified observations.
            if not isinstance(error, SourceError):
                db.rollback()
                merchant = db.get(Merchant, shop_id)
                fresh_items = []
            reason = str(error)[:500] if isinstance(error, SourceError) else 'Product refresh failed; see worker logs'
            for item in {o.external_id: o for o in fresh_items}.values():
                offer, events = ingest(db, merchant, item, settings.refresh_interval_seconds)
                if offer and item.availability != 'unknown' and not item.availability_error:
                    verified.append(item.external_id)
                for event in events:
                    enqueue_event(db, event)
            mark_source_unknown(db, merchant, reason, verified)
            merchant.error_count += 1
            retry = utcnow() + timedelta(seconds=max(getattr(error, 'retry_after_seconds', None) or 0,
                min(21600, 60 * 2 ** min(merchant.error_count, 8))))
            stats.update(last_at=utcnow().isoformat(), checked=checked, error=reason, next_at=retry.isoformat())
            merchant.crawl_state = {**merchant.crawl_state, key: stats, 'retry_at': retry.isoformat(), 'last_job': key}
            merchant.last_error, merchant.next_check_at, merchant.locked_until = reason, retry, None
            for group in selected:
                for watch in group['watches']:
                    watch.last_error, watch.next_check_at = reason, retry
            set_source_ready(merchant, client)
            db.commit()
            return {'shop': merchant.slug, 'refreshed': checked, 'error': reason, 'job': key}
        finally:
            client.close()
