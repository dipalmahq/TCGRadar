from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from datetime import timedelta

from app.adapters.base import SourceOffer
from app.db import utcnow
from app.domain import classify, plain
from app.models import Expansion, Game, Observation, Offer, OfferEvent, Product


def state(offer):
    return {"price_minor": offer.price_minor, "currency": offer.currency, "availability": offer.availability}


def get_or_create(db, model, conditions, values):
    row = db.scalar(select(model).where(*conditions))
    if row is not None:
        return row
    try:
        with db.begin_nested():
            row = model(**values)
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        # Another merchant can discover the same expansion/product concurrently.
        row = db.scalar(select(model).where(*conditions))
        if row is None:
            raise
        return row


def ingest(db, merchant, source: SourceOffer, refresh_interval_seconds=1800) -> tuple[Offer | None, list[OfferEvent]]:
    identity = classify(source, merchant.slug)
    if identity is None:
        return None, []
    game = db.scalar(select(Game).where(Game.slug == identity.game))
    if game is None:
        raise RuntimeError("Game catalog has not been initialized")
    expansion = None
    if identity.set_code:
        expansion = get_or_create(db, Expansion, [Expansion.game_id == game.id, Expansion.code == identity.set_code],
                                  dict(game_id=game.id, code=identity.set_code, name=identity.set_name))
    product = get_or_create(db, Product, [Product.identity_key == identity.identity_key], dict(
            game_id=game.id, expansion_id=expansion.id if expansion else None,
            identity_key=identity.identity_key, name=plain(source.title)[:500],
            language=identity.language, product_type=identity.product_type,
            booster_count=identity.booster_count, condition=identity.condition,
            edition=identity.edition, gtin=identity.gtin, match_confidence=identity.confidence,
        ))
    offer = db.scalar(select(Offer).where(Offer.merchant_id == merchant.id, Offer.external_id == source.external_id))
    now = utcnow()
    previous = state(offer) if offer else None
    kinds = []
    if offer is None:
        offer = Offer(merchant_id=merchant.id, external_id=source.external_id, product_id=product.id, title=plain(source.title)[:500], url=source.url, revision=1)
        db.add(offer)
        kinds.append("new")
    else:
        if source.availability in ("in_stock", "preorder") and offer.last_known_availability == "out_of_stock":
            kinds.append("restock")
        if source.availability == "preorder" and offer.last_known_availability != "preorder":
            kinds.append("preorder")
        if source.price_minor is not None and offer.price_minor is not None and source.currency == offer.currency and source.price_minor != offer.price_minor:
            kinds.append("price_drop" if source.price_minor < offer.price_minor else "price_increase")
        if previous != {"price_minor": source.price_minor, "currency": source.currency, "availability": source.availability}:
            offer.revision += 1
            offer.last_changed_at = now
    offer.product_id = product.id
    offer.title = plain(source.title)[:500]
    offer.url = source.url
    offer.price_minor = source.price_minor
    offer.currency = source.currency
    offer.availability = source.availability
    if source.availability != "unknown":
        offer.last_known_availability = source.availability
    offer.last_seen_at = now
    offer.stock_attempted_at = now
    offer.next_stock_check_at = now + timedelta(seconds=refresh_interval_seconds)
    offer.source_error = source.availability_error
    offer.excluded = False
    db.flush()
    current = state(offer)
    db.add(Observation(offer_id=offer.id, observed_at=now, **current))
    # One event can contain both a restock and a price change. One notification per channel.
    events = []
    if kinds:
        priority = next((kind for kind in ("new", "restock", "preorder", "price_drop", "price_increase") if kind in kinds))
        event = OfferEvent(offer_id=offer.id, revision=offer.revision, kind=priority, previous=previous, current={**current, "changes": kinds})
        db.add(event)
        db.flush()
        events.append(event)
    return offer, events
