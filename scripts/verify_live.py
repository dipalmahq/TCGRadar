"""Verify known links against the same live adapters. Never sends notifications."""
import json
from pathlib import Path

from sqlalchemy import select

from app.adapters import ADAPTERS
from app.adapters.base import ShopClient
from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.domain import classify
from app.models import Merchant, Offer


def main():
    settings = get_settings()
    results = []
    with SessionLocal() as db:
        for shop in db.scalars(select(Merchant).order_by(Merchant.id)):
            offer = db.scalar(select(Offer).where(Offer.merchant_id == shop.id, Offer.availability == "in_stock", Offer.source_error.is_(None)).order_by(Offer.id).limit(1))
            client = ShopClient(shop.base_url, settings)
            try:
                found = ADAPTERS[shop.adapter](client, shop.config).fetch_url(offer.url)
                items = [{"external_id": item.external_id, "title": item.title, "url": item.url, "price_minor": item.price_minor, "availability": item.availability, "product_type": identity.product_type if (identity := classify(item, shop.slug)) else None} for item in found]
                results.append({"shop": shop.slug, "verified_at": utcnow().isoformat(), "requested_url": offer.url, "offers": items})
            except Exception as exc:
                results.append({"shop": shop.slug, "error": type(exc).__name__})
            finally:
                client.close()
    output = Path("data/live-verification.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=True, indent=2))
    if any("error" in result or not result.get("offers") for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
