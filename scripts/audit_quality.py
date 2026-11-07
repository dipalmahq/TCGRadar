"""Bounded live re-fetch of a diverse sample. Read-only; never sends alerts."""
from datetime import datetime, timezone
import json
import logging

from sqlalchemy import select

from app.adapters import ADAPTERS
from app.adapters.base import ShopClient, SourceError
from app.config import get_settings
from app.db import SessionLocal
from app.domain import classify, plain
from app.models import Merchant, Offer

logging.getLogger("httpx").setLevel(logging.WARNING)


def audit():
    settings = get_settings()
    rows = []
    with SessionLocal() as db:
        for shop in db.scalars(select(Merchant).where(Merchant.enabled.is_(True)).order_by(Merchant.id)):
            offers = list(db.scalars(select(Offer).where(Offer.merchant_id == shop.id, Offer.source_error.is_(None), Offer.excluded.is_(False)).order_by(Offer.id)))
            selected = []
            dimensions = set()
            for offer in offers:
                key = (offer.product.game_id, offer.product.product_type, offer.product.language)
                if key not in dimensions:
                    selected.append(offer)
                    dimensions.add(key)
                if len(selected) == 3:
                    break
            client = ShopClient(shop.base_url, settings)
            adapter = ADAPTERS[shop.adapter](client, shop.config)
            try:
                for offer in selected:
                    row = {"shop": shop.name, "title": offer.title, "url": offer.url,
                           "game": offer.product.game.slug, "language": offer.product.language,
                           "product_type": offer.product.product_type, "booster_count": offer.product.booster_count,
                           "price_minor": offer.price_minor, "availability": offer.availability}
                    try:
                        fetched = adapter.fetch_url(offer.url)
                        fresh = next((s for s in fetched if s.external_id == offer.external_id), None)
                        if fresh is None:
                            raise SourceError("Expected source variant missing")
                        identity = classify(fresh, shop.slug)
                        differences = []
                        for field in ("price_minor", "currency", "availability"):
                            if getattr(fresh, field) != getattr(offer, field):
                                differences.append(field)
                        if plain(fresh.title) != offer.title:
                            differences.append("title")
                        for field in ("language", "product_type", "booster_count"):
                            if identity is None or getattr(identity, field) != getattr(offer.product, field):
                                differences.append(field)
                        row.update(status="match" if not differences else "changed", differences=differences,
                                   fresh_price_minor=fresh.price_minor, fresh_availability=fresh.availability)
                    except SourceError as exc:
                        row.update(status="unverified", reason=str(exc))
                    rows.append(row)
            finally:
                client.close()
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "method": "Database vs fresh direct product response; not an independent checkout confirmation",
            "sample_count": len(rows), "matching": sum(r["status"] == "match" for r in rows),
            "changed": sum(r["status"] == "changed" for r in rows),
            "unverified": sum(r["status"] == "unverified" for r in rows), "samples": rows}


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=True, indent=2))
