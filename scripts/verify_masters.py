"""Read-only verification of the running Masters integration; no alerts."""
from collections import Counter
from datetime import datetime, timezone
import json
import logging

import httpx
from sqlalchemy import select

from app.adapters import ADAPTERS
from app.adapters.base import ShopClient
from app.config import get_settings
from app.db import SessionLocal
from app.domain import classify
from app.models import Game, Merchant, SearchRule

logging.getLogger("httpx").setLevel(logging.WARNING)
settings = get_settings()
with httpx.Client(base_url="http://127.0.0.1:8000", headers={"X-Radar-Key": settings.api_key}, trust_env=False) as client:
    meta = client.get("/api/meta").json()
    game = next(g for g in meta["games"] if g["slug"] == "dragon-ball-masters")
    response = client.get("/api/offers", params={"game": game["slug"], "limit": 100})
    response.raise_for_status()
    offers = response.json()
    assert offers["total"] > 0, "No real Masters offers imported"
    assert all(o["game"] == game["slug"] for o in offers["items"])
samples = []
with SessionLocal() as db:
    rules = [r for r in db.scalars(select(SearchRule)) if r.game_id == game["id"] or game["id"] in r.game_ids]
    assert len(rules) >= 2 and all(not r.enabled for r in rules), "Expected paused Masters templates"
    for merchant in db.scalars(select(Merchant).order_by(Merchant.id)):
        offer = next((o for o in offers["items"] if o["merchant_id"] == merchant.id), None)
        if offer is None:
            continue
        shop_client = ShopClient(merchant.base_url, settings)
        try:
            fetched = ADAPTERS[merchant.adapter](shop_client, merchant.config).fetch_url(offer["url"])
            fresh = next((f for f in fetched if classify(f, merchant.slug) and classify(f, merchant.slug).game == game["slug"] and f.url.rstrip("/") == offer["url"].rstrip("/")), None)
            assert fresh is not None, "Selected Masters variant missing"
            assert fresh.price_minor == offer["price_minor"] and fresh.availability == offer["observed_availability"], "Direct source changed since import"
            samples.append({"merchant": merchant.name, "title": offer["title"], "url": offer["url"], "set_code": offer["set_code"], "price_minor": offer["price_minor"], "availability": offer["availability"], "direct_source_match": True})
        finally:
            shop_client.close()
print(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "masters_offers": offers["total"],
                  "by_merchant": dict(Counter(o["merchant"] for o in offers["items"])),
                  "availability": dict(Counter(o["availability"] for o in offers["items"])),
                  "sets": sorted({o["set_code"] for o in offers["items"] if o["set_code"]}),
                  "paused_masters_templates": len(rules), "samples": samples}, ensure_ascii=True, indent=2))
