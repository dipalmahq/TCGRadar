from dataclasses import replace
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.events import ingest
from app.main import create_app
from app.models import Merchant
from test_domain import source


def test_cross_shop_comparison_keeps_language_and_pack_type_separate(factory, settings):
    with factory() as db:
        first_shop = db.scalar(select(Merchant))
        second_shop = Merchant(slug="second", name="Second Shop", base_url="https://second.example", country="DE", adapter="shopify")
        db.add(second_shop)
        db.flush()
        first, _ = ingest(db, first_shop, source())
        second, _ = ingest(db, second_shop, replace(source(), price_minor=12000))
        japanese, _ = ingest(db, second_shop, replace(source("One Piece OP17 Display 24 Booster JP"), external_id="jp"))
        single, _ = ingest(db, second_shop, replace(source("One Piece OP17 Booster ENG"), external_id="single", price_minor=499))
        assert first.product_id == second.product_id
        assert first.product_id not in (japanese.product_id, single.product_id)
        product_id = first.product_id
        db.commit()
    with TestClient(create_app(settings, factory)) as client:
        data = client.get(f"/api/products/{product_id}/compare", headers={"X-Radar-Key": settings.api_key}).json()
        assert len(data["items"]) == 2
        assert [item["price_minor"] for item in data["items"]] == [12000, 12999]
        assert data["confidence"] == "exact_attributes"
