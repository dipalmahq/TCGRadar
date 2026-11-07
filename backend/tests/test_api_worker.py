from datetime import timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
from sqlalchemy import func, select

from app.db import utcnow
from app.main import create_app
from app.models import Merchant, Notification, Offer, OfferEvent, SearchRule
from app.scanner import claim_shop, scan_shop


def catalog_transport(available=True, price="129.95", blocked=False):
    data = json.loads((Path(__file__).parent / "fixtures/shopify.json").read_text())
    data["products"] = data["products"][:1]
    data["products"][0]["variants"][0].update(available=available, price=price)
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if blocked:
            return httpx.Response(403)
        return httpx.Response(200, json=data)
    return httpx.MockTransport(handler)


def test_discovery_persistence_api_and_restock_outbox_end_to_end(factory, settings):
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop_id = shop.id
        db.add(SearchRule(name="OP17 under 130", query="OP17", max_price_minor=13000, channels=["discord"]))
        db.commit()
    assert scan_shop(factory, shop_id, settings, catalog_transport(available=False), force=True)["offers"] == 1
    assert scan_shop(factory, shop_id, settings, catalog_transport(available=True), force=True)["events"] == 1
    assert scan_shop(factory, shop_id, settings, catalog_transport(), force=True)["events"] == 0
    with TestClient(create_app(settings, factory)) as client:
        assert client.get("/api/offers").status_code == 401
        headers = {"X-Radar-Key": settings.api_key}
        response = client.get("/api/offers?game=one-piece&product_type=display&sort=price_asc", headers=headers)
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["price_minor"] == 12995 and item["availability"] == "in_stock"
        assert item["shipping_minor"] is None
        assert client.get("/api/offers?q=OP-17", headers=headers).json()["total"] == 1
        assert client.get(f"/api/offers/{item['id']}/history", headers=headers).json()
        assert client.get(f"/api/products/{item['product_id']}/compare", headers=headers).json()["items"]
    with factory() as db:
        assert db.scalar(select(func.count(Notification.id))) == 1
        assert db.scalar(select(func.count(OfferEvent.id))) == 2


def test_failed_source_is_unknown_not_sold_out_and_recovers(factory, settings):
    with factory() as db:
        shop_id = db.scalar(select(Merchant.id))
    scan_shop(factory, shop_id, settings, catalog_transport(), force=True)
    assert "error" in scan_shop(factory, shop_id, settings, catalog_transport(blocked=True), force=True)
    with factory() as db:
        offer = db.scalar(select(Offer))
        assert offer.availability == "unknown"
        assert offer.last_known_availability == "in_stock"
    assert scan_shop(factory, shop_id, settings, catalog_transport(), force=True)["events"] == 0


def test_shop_lease_prevents_overlapping_scans(factory):
    with factory() as db:
        shop_id = db.scalar(select(Merchant.id))
    assert claim_shop(factory, shop_id, force=True)
    assert not claim_shop(factory, shop_id, force=True)


def test_bounded_catalog_absence_is_not_a_stock_change(factory, settings):
    with factory() as db:
        shop_id = db.scalar(select(Merchant.id))
    scan_shop(factory, shop_id, settings, catalog_transport(), force=True)
    data = {"products": [{"id": 999, "title": "Unrelated product", "handle": "unrelated", "variants": []}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, json=data))
    scan_shop(factory, shop_id, settings, transport, force=True)
    with factory() as db:
        assert db.scalar(select(Offer)).availability == "in_stock"
        assert db.scalar(select(func.count(OfferEvent.id))) == 1


def test_rule_crud_link_validation_and_test_alarm(factory, settings):
    headers = {"X-Radar-Key": settings.api_key}
    with TestClient(create_app(settings, factory)) as client:
        rule = client.post("/api/rules", headers=headers, json={"name": "My watch", "query": "OP17", "max_price_minor": 10000}).json()
        assert rule["id"]
        assert client.patch(f"/api/rules/{rule['id']}", headers=headers, json={"enabled": False}).json()["enabled"] is False
        assert client.delete(f"/api/rules/{rule['id']}", headers=headers).status_code == 204
        assert client.post("/api/watches", headers=headers, json={"url": "http://127.0.0.1/admin"}).status_code == 422
        assert client.post("/api/watches", headers=headers, json={"url": "https://evil.example/products/test"}).status_code == 422
        assert client.post("/api/watches", headers=headers, json={"url": "https://fixture.example:invalid/products/test"}).status_code == 422
        response = client.post("/api/watches", headers=headers, json={"url": "https://fixture.example/products/test?variant=201&utm_source=ignored"})
        assert response.status_code == 201
        assert response.json()["url"] == "https://fixture.example/products/test?variant=201"
        alarm = client.post("/api/notifications/test", headers=headers, json={"channel": "discord"})
        assert alarm.status_code == 202 and alarm.json()["status"] == "pending"
        assert client.post("/api/notifications/test", headers=headers, json={"channel": "telegram"}).status_code == 409


def test_stale_data_is_explicitly_unknown_in_api(factory, settings):
    with factory() as db:
        shop_id = db.scalar(select(Merchant.id))
    scan_shop(factory, shop_id, settings, catalog_transport(), force=True)
    with factory() as db:
        offer = db.scalar(select(Offer))
        offer.last_seen_at = utcnow() - timedelta(hours=2)
        db.commit()
    with TestClient(create_app(settings, factory)) as client:
        response = client.get("/api/offers?availability=unknown", headers={"X-Radar-Key": settings.api_key})
        assert response.json()["items"][0]["stale"] is True
        assert response.json()["items"][0]["availability"] == "unknown"
