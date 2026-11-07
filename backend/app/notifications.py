from datetime import timedelta
import logging
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import select, update

from app.config import Settings
from app.db import utcnow
from app.domain import normalized, search_normalized
from app.models import Notification, Offer, Product, SearchRule, WatchTarget

log = logging.getLogger(__name__)


def configured_channels(settings: Settings) -> list[str]:
    channels = []
    if settings.discord_webhook_url:
        channels.append("discord")
    if settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append("telegram")
    return channels


def eligible_price(offer, maximum):
    return maximum is None or (offer.currency == "EUR" and offer.price_minor is not None and offer.price_minor <= maximum)


def rule_matches(rule, offer: Offer, product: Product) -> bool:
    if not rule.enabled or offer.excluded or offer.availability not in ("in_stock", "preorder"):
        return False
    if offer.availability == "preorder" and not rule.include_preorders:
        return False
    for field, actual in (("game_id", product.game_id), ("product_id", product.id), ("merchant_id", offer.merchant_id), ("language", product.language), ("product_type", product.product_type)):
        expected = getattr(rule, field)
        if expected is not None and expected != actual:
            return False
    if rule.set_code and (not product.expansion or search_normalized(rule.set_code) != search_normalized(product.expansion.code)):
        return False
    for field, actual in (("game_ids", product.game_id), ("merchant_ids", offer.merchant_id), ("languages", product.language), ("product_types", product.product_type)):
        expected = getattr(rule, field) or []
        if expected and actual not in expected:
            return False
    if rule.set_codes and (not product.expansion or search_normalized(product.expansion.code) not in {search_normalized(code) for code in rule.set_codes}):
        return False
    haystack = search_normalized(offer.title)
    if any(word not in haystack for word in search_normalized(rule.query).split()):
        return False
    return eligible_price(offer, rule.max_price_minor)


def watch_matches(watch, offer) -> bool:
    if not watch.enabled or offer.excluded or watch.merchant_id != offer.merchant_id:
        return False
    target, actual = urlsplit(watch.url), urlsplit(offer.url)
    if target.path.rstrip("/") != actual.path.rstrip("/"):
        return False
    wanted, found = parse_qs(target.query), parse_qs(actual.query)
    for key in ("variant", "variation_id"):
        if key in wanted and wanted[key] != [offer.external_id]:
            return False
    for key in wanted:
        if key.startswith("attribute_") and wanted[key] != found.get(key):
            return False
    return offer.availability in ("in_stock", "preorder") and (offer.availability != "preorder" or watch.include_preorders) and eligible_price(offer, watch.max_price_minor)


def money(value, currency="EUR"):
    return f"{value / 100:.2f} {currency}" if value is not None else "Preis unbekannt"


def event_payload(event, offer, product):
    labels = {"new": "Neues Angebot", "restock": "Wieder verfügbar", "preorder": "Vorbestellung", "price_drop": "Preis gesunken", "price_increase": "Preis gestiegen"}
    unit = money(round(offer.price_minor / product.booster_count), offer.currency) + "/Booster" if offer.price_minor is not None and product.booster_count else "Boosteranzahl unbekannt"
    return {
        "title": labels.get(event.kind, event.kind),
        "text": f"{offer.title}\n{offer.merchant.name} · {money(offer.price_minor, offer.currency)} · {unit}\nStatus: {offer.availability} · Versandkosten unbekannt\nPrüfzeitpunkt: {utcnow().isoformat()}",
        "url": offer.url,
        "event_id": event.id,
    }


def enqueue_event(db, event):
    if event.kind == "price_increase":
        return []
    offer = db.get(Offer, event.offer_id)
    product = db.get(Product, offer.product_id)
    channels = set()
    for rule in db.scalars(select(SearchRule).where(SearchRule.enabled.is_(True))):
        if rule_matches(rule, offer, product):
            channels.update(rule.channels)
    for watch in db.scalars(select(WatchTarget).where(WatchTarget.enabled.is_(True), WatchTarget.merchant_id == offer.merchant_id)):
        if watch_matches(watch, offer):
            channels.update(watch.channels)
    created = []
    for channel in sorted(channels & {"discord", "telegram"}):
        if db.scalar(select(Notification.id).where(Notification.event_id == event.id, Notification.channel == channel)):
            continue
        item = Notification(event_id=event.id, channel=channel, payload=event_payload(event, offer, product))
        db.add(item)
        created.append(item)
    db.flush()
    return created


def send_payload(channel, payload, settings: Settings, client):
    if channel == "discord":
        url = settings.discord_webhook_url
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ("discord.com", "discordapp.com") or not parsed.path.startswith("/api/webhooks/"):
            raise ValueError("Discord webhook URL is not configured correctly")
        embed = {"title": payload["title"][:256], "description": payload["text"][:3500], "color": 13750870}
        if payload.get("url"):
            embed["url"] = payload["url"]
        return client.post(url, params={"wait": "true"}, json={
            "username": "JoyBoyz TCG Radar", "allowed_mentions": {"parse": []},
            "embeds": [embed],
        })
    if channel == "telegram":
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise ValueError("Telegram bot token or chat ID is missing")
        return client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage", json={
            "chat_id": settings.telegram_chat_id,
            "text": f"{payload['title']}\n{payload['text']}\n{payload.get('url', '')}"[:4000],
            "link_preview_options": {"is_disabled": True},
        })
    raise ValueError("Unsupported notification channel")


def deliver_pending(session_factory, settings: Settings, transport=None):
    now = utcnow()
    with session_factory() as db:
        # A crash after sending is ambiguous. Do not automatically resend that message.
        db.execute(update(Notification).where(Notification.status == "sending", Notification.next_attempt_at < now - timedelta(minutes=5)).values(status="uncertain", last_error="Worker interrupted during delivery; check channel before retrying"))
        if not settings.notifications_enabled:
            db.execute(update(Notification).where(Notification.status == "pending").values(status="muted", last_error="Notifications were disabled when this event was processed"))
            db.commit()
            return
        ids = list(db.scalars(select(Notification.id).where(Notification.status == "pending", Notification.next_attempt_at <= now).order_by(Notification.id).limit(20)))
        db.commit()
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False, transport=transport) as client:
        for item_id in ids:
            with session_factory() as db:
                claimed = db.execute(update(Notification).where(Notification.id == item_id, Notification.status == "pending").values(status="sending", next_attempt_at=utcnow()))
                db.commit()
                if not claimed.rowcount:
                    continue
                item = db.get(Notification, item_id)
                item.attempts += 1
                try:
                    response = send_payload(item.channel, item.payload, settings, client)
                    if 200 <= response.status_code < 300 and (item.channel != "telegram" or response.json().get("ok") is True):
                        item.status, item.sent_at, item.last_error = "sent", utcnow(), None
                    elif response.status_code == 429:
                        retry = response.headers.get("Retry-After", "60")
                        if item.channel == "telegram":
                            retry = str(response.json().get("parameters", {}).get("retry_after", retry))
                        seconds = min(3600, max(5, int(float(retry))))
                        item.status = "pending" if item.attempts < 5 else "failed"
                        item.next_attempt_at = utcnow() + timedelta(seconds=seconds)
                        item.last_error = "Notification service rate limit (HTTP 429)"
                    else:
                        item.status, item.last_error = "failed", f"Notification service rejected delivery (HTTP {response.status_code})"
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    item.status = "pending" if item.attempts < 5 else "failed"
                    item.next_attempt_at = utcnow() + timedelta(seconds=min(900, 30 * 2 ** item.attempts))
                    item.last_error = "Connection to notification service failed"
                except (httpx.TimeoutException, httpx.RemoteProtocolError):
                    item.status, item.last_error = "uncertain", "Response missing; delivery may have succeeded. No automatic resend."
                except (ValueError, httpx.HTTPError):
                    item.status, item.last_error = "failed", "Notification configuration or service response invalid"
                db.commit()
                log.info("notification id=%s channel=%s status=%s", item.id, item.channel, item.status)
