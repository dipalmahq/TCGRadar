from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
from sqlalchemy import func, select

from app.db import utcnow
from app.events import ingest
from app.main import create_app
from app.models import Game, Merchant, Notification, Offer, SearchRule
from app.notifications import enqueue_event, rule_matches
from app.rule_templates import prepare_templates
from app.scanner import scan_shop
from test_api_worker import catalog_transport
from test_domain import source


def populate(factory):
    with factory() as db:
        first = db.scalar(select(Merchant))
        second = Merchant(slug="fixture-two", name="Fixture Two", base_url="https://two.example", country="DE", adapter="shopify", config={})
        db.add(second)
        db.flush()
        variants = [
            (first, source()),
            (second, replace(source("One Piece OP-17 Booster [DE]"), external_id="2")),
            (second, replace(source("Pokemon Testset Display 36 Booster [DE]"), external_id="3")),
            (first, replace(source("Dragon Ball Fusion World FB02 Display 24 Booster [ENG]"), external_id="4", availability="out_of_stock")),
            (first, replace(source("Pokemon Testset Booster [ENG]"), external_id="5")),
        ]
        for merchant, item in variants:
            offer, _ = ingest(db, merchant, item)
            if item.external_id == "5":
                offer.last_seen_at = utcnow() - timedelta(hours=2)
        db.commit()
        return first.id, second.id


def test_offer_multiselect_or_within_and_between_groups(factory, settings):
    first, second = populate(factory)
    with TestClient(create_app(settings, factory)) as client:
        headers = {"X-Radar-Key": settings.api_key}
        params = [("game", "one-piece"), ("game", "pokemon"), ("language", "en"), ("language", "de"), ("product_type", "booster"), ("product_type", "display"), ("merchant_id", first), ("merchant_id", second), ("availability", "in_stock")]
        result = client.get("/api/offers", params=params, headers=headers).json()
        assert result["total"] == 3
        assert {r["game"] for r in result["items"]} == {"pokemon", "one-piece"}
        assert client.get("/api/offers", params=params + [("set_code", "OP-17"), ("set_code", "FB-02")], headers=headers).json()["total"] == 2
        assert client.get("/api/offers", params=[("availability", "in_stock"), ("availability", "unknown")], headers=headers).json()["total"] == 4
        unknown = client.get("/api/offers?availability=unknown", headers=headers).json()
        assert unknown["total"] == 1 and unknown["items"][0]["stale"]
        assert client.get("/api/offers?game=one-piece&language=de", headers=headers).json()["total"] == 1
        assert client.get("/api/offers", params=[("game", "one-piece")] * 51, headers=headers).status_code == 422
        pages = [client.get("/api/offers", params=params + [("limit", 2), ("offset", offset)], headers=headers).json() for offset in (0, 2)]
        ids = [row["id"] for page in pages for row in page["items"]]
        assert len(ids) == len(set(ids)) == 3


def test_saved_rule_multiselect_editing_and_notification_dedup(factory, settings):
    first, second = populate(factory)
    with factory() as db:
        games = [g.id for g in db.scalars(select(Game).where(Game.slug.in_(["one-piece", "pokemon"])))]
    payload = {"name": "Crew selection", "game_ids": games, "merchant_ids": [first, second], "languages": ["de", "en", "en"], "product_types": ["booster", "display"], "set_codes": ["OP17", "sv08"], "max_price_minor": 13000, "enabled": False}
    with TestClient(create_app(settings, factory)) as client:
        headers = {"X-Radar-Key": settings.api_key}
        response = client.post("/api/rules", json=payload, headers=headers)
        assert response.status_code == 201
        rule_id = response.json()["id"]
        assert response.json()["languages"] == ["de", "en"]
        updated = client.put(f"/api/rules/{rule_id}", json={**payload, "enabled": True}, headers=headers)
        assert updated.status_code == 200 and updated.json()["enabled"]
        assert client.get("/api/rules", headers=headers).json()[0]["game_ids"] == games
        assert client.post("/api/rules", json={**payload, "game_id": games[0]}, headers=headers).status_code == 422
        assert client.put(f"/api/rules/{rule_id}", json={**payload, "merchant_ids": [999999]}, headers=headers).status_code == 404
    with factory() as db:
        rule = db.get(SearchRule, rule_id)
        shop = db.get(Merchant, first)
        item = replace(source(), external_id="new-rule-offer", price_minor=12500)
        offer, events = ingest(db, shop, item)
        assert rule_matches(rule, offer, offer.product)
        assert len(enqueue_event(db, events[0])) == 1
        assert enqueue_event(db, events[0]) == []
        # A different set fails even though the game/language/type match.
        different, _ = ingest(db, shop, replace(item, external_id="different-set", title="One Piece OP18 Display 24 Booster ENG"))
        assert not rule_matches(rule, different, different.product)
        assert db.scalar(select(func.count(Notification.id))) == 1


def test_templates_are_paused_and_repeatable_without_resetting_edits(factory):
    with factory() as db:
        assert prepare_templates(db) == 8
        rows = list(db.scalars(select(SearchRule)))
        assert all(not r.enabled and r.max_price_minor is None and r.channels == ["discord"] for r in rows)
        rows[0].max_price_minor = 10000
        db.commit()
        assert prepare_templates(db) == 0
        assert db.get(SearchRule, rows[0].id).max_price_minor == 10000


def test_woocommerce_direct_watch_accepts_english_product_permalink(factory, settings):
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop.adapter = "woocommerce"
        db.commit()
    with TestClient(create_app(settings, factory)) as client:
        response = client.post("/api/watches", headers={"X-Radar-Key": settings.api_key}, json={"url": "https://fixture.example/product/pokemon-booster/"})
        assert response.status_code == 201
        assert response.json()["url"].endswith("/product/pokemon-booster")


def test_rejected_old_import_is_hidden_but_history_is_retained(factory, settings):
    with factory() as db:
        shop_id = db.scalar(select(Merchant.id))
    assert scan_shop(factory, shop_id, settings, catalog_transport(), force=True)["offers"] == 1
    catalog = json.loads((Path(__file__).parent / "fixtures/shopify.json").read_text())
    catalog["products"] = catalog["products"][:1]
    catalog["products"][0]["title"] = "The Acrylic Box One Piece OP17 Display Acrylcase"
    transport = httpx.MockTransport(lambda request: httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, json=catalog))
    assert scan_shop(factory, shop_id, settings, transport, force=True)["offers"] == 0
    with factory() as db:
        offer = db.scalar(select(Offer))
        assert offer.excluded
        offer_id, product_id = offer.id, offer.product_id
    with TestClient(create_app(settings, factory)) as client:
        headers = {"X-Radar-Key": settings.api_key}
        assert client.get("/api/offers", headers=headers).json()["total"] == 0
        assert client.get("/api/overview", headers=headers).json()["offers"] == 0
        assert client.get("/api/activity", headers=headers).json()["events"] == []
        assert client.get(f"/api/products/{product_id}/compare", headers=headers).json()["items"] == []
        assert client.get(f"/api/offers/{offer_id}/history", headers=headers).json()
    # A later corrected source can be accepted again without deleting history.
    assert scan_shop(factory, shop_id, settings, catalog_transport(), force=True)["offers"] == 1
    with factory() as db:
        assert not db.get(Offer, offer_id).excluded
