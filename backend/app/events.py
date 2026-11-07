from sqlalchemy import select

from app.adapters.base import SourceOffer
from app.db import utcnow
from app.domain import classify, plain
from app.models import Expansion, Game, Observation, Offer, OfferEvent, Product


def state(offer):
    return {"price_minor": offer.price_minor, "currency": offer.currency, "availability": offer.availability}


def ingest(db, merchant, source: SourceOffer) -> tuple[Offer | None, list[OfferEvent]]:
    identity = classify(source, merchant.slug)
    if identity is None:
        return None, []
    game = db.scalar(select(Game).where(Game.slug == identity.game))
    if game is None:
        raise RuntimeError("Game catalog has not been initialized")
    expansion = None
    if identity.set_code:
        expansion = db.scalar(select(Expansion).where(Expansion.game_id == game.id, Expansion.code == identity.set_code))
        if expansion is None:
            expansion = Expansion(game_id=game.id, code=identity.set_code, name=identity.set_name)
            db.add(expansion)
            db.flush()
    product = db.scalar(select(Product).where(Product.identity_key == identity.identity_key))
    if product is None:
        product = Product(
            game_id=game.id, expansion_id=expansion.id if expansion else None,
            identity_key=identity.identity_key, name=plain(source.title)[:500],
            language=identity.language, product_type=identity.product_type,
            booster_count=identity.booster_count, condition=identity.condition,
            edition=identity.edition, gtin=identity.gtin, match_confidence=identity.confidence,
        )
        db.add(product)
        db.flush()
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
    offer.source_error = None
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
