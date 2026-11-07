from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hmac
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.models import Expansion, Game, Merchant, Notification, Observation, Offer, OfferEvent, Product, SearchRule, WatchTarget
from app.notifications import configured_channels
from app.schemas import RuleCreate, TestNotification, Toggle, WatchCreate
from app.seed import seed


def iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def serialize_offer(offer, settings):
    product = offer.product
    stale = utcnow() - aware(offer.last_seen_at) > timedelta(minutes=settings.stale_after_minutes)
    invalid_identity = bool(offer.source_error and offer.source_error.startswith("Produktzuordnung"))
    return {
        "id": offer.id, "product_id": product.id,
        "title": offer.title, "url": offer.url,
        "game": product.game.slug, "game_name": product.game.name,
        "set_code": product.expansion.code if product.expansion else None,
        "language": product.language, "product_type": "unknown" if invalid_identity else product.product_type,
        "booster_count": None if invalid_identity else product.booster_count, "condition": product.condition,
        "match_confidence": "isolated" if invalid_identity else product.match_confidence,
        "merchant_id": offer.merchant_id, "merchant": offer.merchant.name,
        "country": offer.merchant.country,
        "price_minor": offer.price_minor, "currency": offer.currency,
        "price_per_booster_minor": round(offer.price_minor / product.booster_count, 2) if offer.price_minor is not None and product.booster_count and not invalid_identity else None,
        "shipping_minor": offer.shipping_minor, "shipping_country": offer.shipping_country,
        "availability": "unknown" if stale else offer.availability,
        "observed_availability": offer.availability,
        "stale": stale, "source_error": offer.source_error,
        "first_seen_at": iso(offer.first_seen_at), "last_seen_at": iso(offer.last_seen_at),
        "last_changed_at": iso(offer.last_changed_at),
    }


def row_values(row, keys):
    return {key: iso(value) if isinstance(value := getattr(row, key), datetime) else value for key in keys}


RULE_KEYS = ("id", "name", "query", "game_id", "game_ids", "product_id", "merchant_id", "merchant_ids", "set_code", "set_codes", "language", "languages", "product_type", "product_types", "max_price_minor", "include_preorders", "channels", "enabled", "created_at")
WATCH_KEYS = ("id", "merchant_id", "url", "max_price_minor", "channels", "include_preorders", "enabled", "last_checked_at", "last_error", "created_at")


def create_app(settings=None, session_factory=SessionLocal):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_):
        with session_factory() as db:
            seed(db, settings)
        yield

    app = FastAPI(title="JoyBoyz TCG Radar", version="0.1.0", lifespan=lifespan, docs_url="/docs", redoc_url=None)

    @app.middleware("http")
    async def team_access(request, call_next):
        if request.url.path.startswith("/api/") and request.url.path != "/api/health" and settings.api_key:
            supplied = request.headers.get("X-Radar-Key", "")
            if not hmac.compare_digest(supplied.encode(), settings.api_key.encode()):
                return JSONResponse({"detail": "Team-Schlüssel erforderlich"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def database():
        with session_factory() as db:
            yield db

    def get_or_404(db, cls, item_id):
        row = db.get(cls, item_id)
        if row is None:
            raise HTTPException(404, "Eintrag nicht gefunden")
        return row

    @app.get("/api/health")
    def health(db=Depends(database)):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/meta")
    def metadata(db=Depends(database)):
        return {
            "games": [row_values(g, ("id", "slug", "name", "product_line")) for g in db.scalars(select(Game).order_by(Game.id))],
            "sets": [row_values(s, ("id", "game_id", "code", "name")) for s in db.scalars(select(Expansion).order_by(Expansion.code))],
            "channels": configured_channels(settings),
            "notifications_enabled": settings.notifications_enabled,
            "authentication_enabled": bool(settings.api_key),
            "stale_after_minutes": settings.stale_after_minutes,
        }

    @app.get("/api/overview")
    def overview(db=Depends(database)):
        cutoff = utcnow() - timedelta(minutes=settings.stale_after_minutes)
        return {
            "offers": db.scalar(select(func.count(Offer.id)).where(Offer.excluded.is_(False))),
            "in_stock": db.scalar(select(func.count(Offer.id)).where(Offer.excluded.is_(False), Offer.availability == "in_stock", Offer.last_seen_at >= cutoff)),
            "preorders": db.scalar(select(func.count(Offer.id)).where(Offer.excluded.is_(False), Offer.availability == "preorder", Offer.last_seen_at >= cutoff)),
            "new_today": db.scalar(select(func.count(Offer.id)).where(Offer.excluded.is_(False), Offer.first_seen_at >= utcnow() - timedelta(hours=24))),
            "rules": db.scalar(select(func.count(SearchRule.id)).where(SearchRule.enabled.is_(True))),
            "pending_notifications": db.scalar(select(func.count(Notification.id)).where(Notification.status == "pending")),
            "last_success_at": iso(db.scalar(select(func.max(Merchant.last_success_at)))),
        }

    @app.get("/api/offers")
    def offers(
        q: str = Query("", max_length=200), game: list[str] | None = Query(None, max_length=50),
        set_code: list[str] | None = Query(None, max_length=50), merchant_id: list[int] | None = Query(None, max_length=50),
        language: list[str] | None = Query(None, max_length=50), product_type: list[str] | None = Query(None, max_length=50),
        availability: list[str] | None = Query(None, max_length=50), sort: str = "recent",
        limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
        db=Depends(database),
    ):
        stmt = select(Offer).join(Product).join(Game, Product.game_id == Game.id).outerjoin(Expansion, Product.expansion_id == Expansion.id).where(Offer.excluded.is_(False))
        for word in q.split():
            title_match = Offer.title.ilike("%" + word.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\")
            code = re.fullmatch(r"(OP|EB|PRB|FB|SB|BT|B)-?(\d{2})", word, re.I)
            prefix = code[1].upper().replace("BT", "B") if code else None
            stmt = stmt.where(title_match | (Expansion.code == f"{prefix}-{code[2]}")) if code else stmt.where(title_match)
        filters = ((game, Game.slug), (set_code, Expansion.code), (merchant_id, Offer.merchant_id), (language, Product.language))
        for value, column in filters:
            if value is not None:
                stmt = stmt.where(column.in_(value))
        invalid_identity = func.coalesce(Offer.source_error, "").like("Produktzuordnung%")
        if product_type:
            kind_conditions = [and_(Product.product_type.in_([t for t in product_type if t != "unknown"]), ~invalid_identity)]
            if "unknown" in product_type:
                kind_conditions.append(invalid_identity)
            stmt = stmt.where(or_(*kind_conditions))
        cutoff = utcnow() - timedelta(minutes=settings.stale_after_minutes)
        if availability:
            availability_conditions = [and_(Offer.availability.in_([a for a in availability if a != "unknown"]), Offer.last_seen_at >= cutoff)]
            if "unknown" in availability:
                availability_conditions.append((Offer.availability == "unknown") | (Offer.last_seen_at < cutoff))
            stmt = stmt.where(or_(*availability_conditions))
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        order = {
            "price_asc": Offer.price_minor.asc().nulls_last(),
            "price_desc": Offer.price_minor.desc().nulls_last(),
            "recent": Offer.first_seen_at.desc(),
            "updated": Offer.last_seen_at.desc(),
        }.get(sort)
        if order is None:
            raise HTTPException(422, "Unbekannte Sortierung")
        stmt = stmt.options(joinedload(Offer.product).joinedload(Product.game), joinedload(Offer.product).joinedload(Product.expansion), joinedload(Offer.merchant)).order_by(order, Offer.id.desc()).offset(offset).limit(limit)
        return {"items": [serialize_offer(o, settings) for o in db.scalars(stmt)], "total": total, "limit": limit, "offset": offset}

    @app.get("/api/offers/{offer_id}/history")
    def history(offer_id: int, db=Depends(database)):
        get_or_404(db, Offer, offer_id)
        rows = list(db.scalars(select(Observation).where(Observation.offer_id == offer_id).order_by(Observation.observed_at.desc()).limit(100)))
        return [row_values(row, ("id", "observed_at", "price_minor", "currency", "availability")) for row in reversed(rows)]

    @app.get("/api/products/{product_id}/compare")
    def compare(product_id: int, db=Depends(database)):
        product = get_or_404(db, Product, product_id)
        rows = db.scalars(select(Offer).where(Offer.product_id == product_id, Offer.source_error.is_(None), Offer.excluded.is_(False)).order_by(Offer.price_minor.asc().nulls_last()))
        return {"product_id": product_id, "confidence": product.match_confidence, "items": [serialize_offer(row, settings) for row in rows]}

    @app.get("/api/shops")
    def shops(db=Depends(database)):
        keys = ("id", "slug", "name", "base_url", "country", "adapter", "enabled", "interval_seconds", "last_attempt_at", "last_success_at", "last_error", "error_count", "last_offer_count", "last_scanned_count", "next_check_at", "requested_at", "locked_until")
        return [row_values(row, keys) for row in db.scalars(select(Merchant).order_by(Merchant.id))]

    @app.post("/api/shops/{shop_id}/check", status_code=202)
    def check_shop(shop_id: int, db=Depends(database)):
        shop = get_or_404(db, Merchant, shop_id)
        if not shop.enabled:
            raise HTTPException(409, "Shop ist pausiert")
        now = utcnow()
        if shop.locked_until and aware(shop.locked_until) > now:
            return {"status": "running"}
        if shop.requested_at and now - aware(shop.requested_at) < timedelta(seconds=60):
            return {"status": "queued"}
        if shop.last_attempt_at and now - aware(shop.last_attempt_at) < timedelta(seconds=60):
            raise HTTPException(429, "Bitte mindestens eine Minute zwischen Prüfungen warten")
        shop.requested_at = now
        shop.next_check_at = now
        db.commit()
        return {"status": "queued"}

    @app.patch("/api/shops/{shop_id}")
    def toggle_shop(shop_id: int, body: Toggle, db=Depends(database)):
        shop = get_or_404(db, Merchant, shop_id)
        shop.enabled = body.enabled
        db.commit()
        return {"id": shop.id, "enabled": shop.enabled}

    @app.get("/api/rules")
    def rules(db=Depends(database)):
        return [row_values(row, RULE_KEYS) for row in db.scalars(select(SearchRule).order_by(SearchRule.id.desc()))]

    @app.post("/api/rules", status_code=201)
    def create_rule(body: RuleCreate, db=Depends(database)):
        if db.scalar(select(func.count(SearchRule.id))) >= 100:
            raise HTTPException(409, "Maximal 100 Suchregeln im MVP")
        for value, cls in ((body.game_id, Game), (body.product_id, Product), (body.merchant_id, Merchant)):
            if value is not None:
                get_or_404(db, cls, value)
        for values, cls in ((body.game_ids, Game), (body.merchant_ids, Merchant)):
            for value in values:
                get_or_404(db, cls, value)
        rule = SearchRule(**body.model_dump())
        db.add(rule)
        db.commit()
        return row_values(rule, RULE_KEYS)

    @app.put("/api/rules/{rule_id}")
    def update_rule(rule_id: int, body: RuleCreate, db=Depends(database)):
        rule = get_or_404(db, SearchRule, rule_id)
        for value, cls in ((body.game_id, Game), (body.product_id, Product), (body.merchant_id, Merchant)):
            if value is not None:
                get_or_404(db, cls, value)
        for values, cls in ((body.game_ids, Game), (body.merchant_ids, Merchant)):
            for value in values:
                get_or_404(db, cls, value)
        for key, value in body.model_dump().items():
            setattr(rule, key, value)
        db.commit()
        return row_values(rule, RULE_KEYS)

    @app.patch("/api/rules/{rule_id}")
    def toggle_rule(rule_id: int, body: Toggle, db=Depends(database)):
        rule = get_or_404(db, SearchRule, rule_id)
        rule.enabled = body.enabled
        db.commit()
        return row_values(rule, RULE_KEYS)

    @app.delete("/api/rules/{rule_id}", status_code=204)
    def delete_rule(rule_id: int, db=Depends(database)):
        db.delete(get_or_404(db, SearchRule, rule_id))
        db.commit()

    @app.get("/api/watches")
    def watches(db=Depends(database)):
        return [row_values(row, WATCH_KEYS) for row in db.scalars(select(WatchTarget).order_by(WatchTarget.id.desc()))]

    @app.post("/api/watches", status_code=201)
    def create_watch(body: WatchCreate, db=Depends(database)):
        try:
            parsed = urlsplit(body.url)
            port = parsed.port
        except ValueError:
            raise HTTPException(422, "Ungültige Produktadresse") from None
        if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
            raise HTTPException(422, "Eine HTTPS-Produktadresse eines angebundenen Shops ist erforderlich")
        merchant = next((m for m in db.scalars(select(Merchant)) if urlsplit(m.base_url).hostname == parsed.hostname), None)
        if merchant is None:
            raise HTTPException(422, "Dieser Shop ist noch nicht angebunden")
        if (merchant.adapter == "shopify" and "/products/" not in parsed.path
                or merchant.adapter == "woocommerce" and not any(prefix in parsed.path for prefix in ("/produkt/", "/product/"))):
            raise HTTPException(422, "Bitte einen direkten Produktlink eintragen")
        params = parse_qs(parsed.query)
        variant = {key: params[key][0] for key in ("variant", "variation_id") if key in params and params[key][0].isdigit()}
        variant.update({key: value[0] for key, value in params.items() if re.fullmatch(r"attribute_[a-zA-Z0-9_-]{1,80}", key) and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value[0])})
        url = urlunsplit(("https", parsed.hostname, parsed.path.rstrip("/"), urlencode(variant), ""))
        if db.scalar(select(WatchTarget.id).where(WatchTarget.merchant_id == merchant.id, WatchTarget.url == url)):
            raise HTTPException(409, "Dieser Produktlink wird bereits überwacht")
        if db.scalar(select(func.count(WatchTarget.id))) >= 100:
            raise HTTPException(409, "Maximal 100 Produktlinks im MVP")
        watch = WatchTarget(merchant_id=merchant.id, **{**body.model_dump(), "url": url})
        db.add(watch)
        merchant.next_check_at = utcnow()
        db.commit()
        return row_values(watch, WATCH_KEYS)

    @app.delete("/api/watches/{watch_id}", status_code=204)
    def delete_watch(watch_id: int, db=Depends(database)):
        db.delete(get_or_404(db, WatchTarget, watch_id))
        db.commit()

    @app.get("/api/activity")
    def activity(db=Depends(database)):
        events = list(db.scalars(select(OfferEvent).join(Offer).where(Offer.excluded.is_(False)).order_by(OfferEvent.id.desc()).limit(30)))
        messages = list(db.scalars(select(Notification).order_by(Notification.id.desc()).limit(30)))
        return {
            "events": [{**row_values(event, ("id", "kind", "created_at", "current", "previous")), "title": event.offer.title, "url": event.offer.url, "merchant": event.offer.merchant.name} for event in events],
            "notifications": [{**row_values(item, ("id", "event_id", "channel", "status", "attempts", "last_error", "created_at", "sent_at")), "title": item.payload.get("title")} for item in messages],
        }

    @app.post("/api/notifications/test", status_code=202)
    def test_notification(body: TestNotification, db=Depends(database)):
        if body.channel not in configured_channels(settings):
            raise HTTPException(409, "Kanal nicht eingerichtet; Server-Umgebungsvariablen prüfen")
        if not settings.notifications_enabled:
            raise HTTPException(409, "Benachrichtigungen sind serverseitig deaktiviert")
        last = db.scalar(select(Notification).where(Notification.event_id.is_(None), Notification.channel == body.channel).order_by(Notification.id.desc()).limit(1))
        if last and utcnow() - aware(last.created_at) < timedelta(seconds=30):
            raise HTTPException(429, "Bitte 30 Sekunden zwischen Testalarmen warten")
        item = Notification(channel=body.channel, payload={"title": "JoyBoyz Radar · Testalarm", "text": "Die Verbindung funktioniert. Dies ist ein manuell ausgelöster Testalarm, kein Produktangebot."})
        db.add(item)
        db.commit()
        return {"id": item.id, "status": item.status}

    if Path(settings.frontend_dir).joinpath("index.html").exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="dashboard")
    else:
        @app.get("/")
        def frontend_not_built():
            return {"name": "JoyBoyz TCG Radar", "dashboard": "Build frontend/ or start the Vite development server", "docs": "/docs"}
    return app


app = create_app()
