"""Full catalogs continue past former caps and survive worker/network interruptions."""
from datetime import datetime
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.adapters.base import ShopClient
from app.adapters.shopify import ShopifyAdapter
from app.adapters.structured_html import StructuredHtmlAdapter
from app.adapters.woocommerce import WooCommerceAdapter
from app.models import Merchant, Offer, OfferEvent
from app.scanner import scan_shop
from app.domain import classify
from app.main import create_app

BASE = "https://fixture.example"


def client(settings, handler):
    def route(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return handler(request)
    return ShopClient(BASE, settings, httpx.MockTransport(route))


def shopify_product(id):
    return {"id": id, "title": "Pokemon Booster Deutsch", "handle": f"booster-{id}",
            "variants": [{"id": id, "price": "4.99", "available": True}]}


def html_product(id):
    return {"@type": "Product", "name": "Pokemon Booster Deutsch", "url": f"{BASE}/booster-{id}",
            "offers": {"@type": "Offer", "price": "4.99", "availability": "https://schema.org/InStock"}}


def html(data):
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>'


def test_shopify_all_pages_including_pages_beyond_former_maximum(settings):
    pages = []
    def handler(request):
        page = int(request.url.params["page"])
        pages.append(page)
        return httpx.Response(200, json={"products": [shopify_product(page * 2), shopify_product(page * 2 + 1)] if page <= 5 else []})
    cursor, found = None, []
    for _ in range(6):
        result = ShopifyAdapter(client(settings, handler), {"full_catalog": True, "page_size": 2}).discover_batch(cursor)
        found.extend(result.offers)
        cursor = result.next_cursor
        if result.complete:
            break
    assert pages == [1, 2, 3, 4, 5, 6]
    assert len({o.external_id for o in found}) == 10
    assert result.complete and cursor is None


def test_shopify_rate_limit_retains_current_page_and_detects_ignored_pagination(settings):
    data = {"products": [shopify_product(1)]}
    first = ShopifyAdapter(client(settings, lambda r: httpx.Response(200, json=data)),
                           {"full_catalog": True, "page_size": 1}).discover_batch()
    limited = ShopifyAdapter(client(settings, lambda r: httpx.Response(429, headers={"Retry-After": "120"})),
                             {"full_catalog": True, "page_size": 1}).discover_batch(first.next_cursor)
    assert limited.next_cursor == first.next_cursor
    assert limited.retry_after_seconds == 120 and not limited.complete
    repeated = ShopifyAdapter(client(settings, lambda r: httpx.Response(200, json=data)),
                              {"full_catalog": True, "page_size": 1}).discover_batch(first.next_cursor)
    assert "repeated" in repeated.source_error and not repeated.complete


def test_woocommerce_resumes_all_variants_beyond_twelve_across_request_batches(settings):
    fixture = json.loads((Path(__file__).parent / "fixtures/woocommerce.json").read_text())
    parent = {**fixture["parent"], "variations": [{"id": n} for n in range(100, 130)]}
    calls = []
    def handler(request):
        if request.url.path.endswith("/products"):
            return httpx.Response(200, headers={"X-WP-TotalPages": "1"}, json=[parent])
        id = int(request.url.path.rsplit("/", 1)[-1])
        calls.append(id)
        return httpx.Response(200, json={**fixture["booster"], "id": id})
    config = {"full_catalog": True}
    first = WooCommerceAdapter(client(settings, handler), config).discover_batch()
    assert not first.complete and first.next_cursor["pending"]
    second = WooCommerceAdapter(client(settings, handler), config).discover_batch(first.next_cursor)
    assert second.complete and second.next_cursor is None
    assert len(first.offers + second.offers) == 30
    assert calls == list(range(100, 130))


def test_woocommerce_total_pages_finishes_exact_full_last_page(settings):
    fixture = json.loads((Path(__file__).parent / "fixtures/woocommerce.json").read_text())["booster"]
    def handler(request):
        page = int(request.url.params["page"])
        assert page <= 2
        return httpx.Response(200, headers={"X-WP-TotalPages": "2"}, json=[{**fixture, "id": page}])
    config = {"full_catalog": True, "page_size": 1}
    first = WooCommerceAdapter(client(settings, handler), config).discover_batch()
    second = WooCommerceAdapter(client(settings, handler), config).discover_batch(first.next_cursor)
    assert not first.complete and second.complete


def test_html_all_products_and_pages_survive_new_adapter_instances(settings):
    detail_ids = []
    def handler(request):
        if request.url.path == "/category":
            return httpx.Response(200, text='<link rel="next" href="/category?page=2">' + html([html_product(n) for n in range(30)])) if "page" not in request.url.params else httpx.Response(200, text=html(html_product(30)))
        id = int(request.url.path.rsplit("-", 1)[-1])
        detail_ids.append(id)
        return httpx.Response(200, text=html(html_product(id)))
    config = {"full_catalog": True, "categories": [{"path": "/category"}]}
    cursor, results = None, []
    for _ in range(5):
        result = StructuredHtmlAdapter(client(settings, handler), config).discover_batch(cursor)
        assert not result.source_error
        results.append(result)
        cursor = result.next_cursor
        if result.complete:
            break
    assert result.complete
    assert sum(len(r.offers) for r in results) == 31
    assert sum(r.pages_scanned for r in results) == 2
    assert detail_ids == list(range(31))


def test_html_follows_subcategories_without_importing_category_as_product(settings):
    def handler(request):
        if request.url.path == "/category":
            return httpx.Response(200, text='<a href="/leaf"><img src="/media/image/category/1/sm/test.jpg" alt="Displays"></a>')
        if request.url.path == "/leaf":
            return httpx.Response(200, text=html(html_product(1)))
        return httpx.Response(200, text=html(html_product(1)))
    config = {"full_catalog": True, "crawl_subcategories": True, "categories": [{"path": "/category"}]}
    first = StructuredHtmlAdapter(client(settings, handler), config).discover_batch()
    assert not first.complete and not first.offers
    second = StructuredHtmlAdapter(client(settings, handler), config).discover_batch(first.next_cursor)
    assert second.complete and len(second.offers) == 1


def test_mueller_final_short_page_does_not_generate_extra_pages(settings):
    a = StructuredHtmlAdapter(client(settings, lambda r: httpx.Response(404)), {"pagination": "page", "html_page_size": 60})
    page = html({"@type": "ItemList", "numberOfItems": 123, "itemListElement": [html_product(n) for n in range(3)]})
    assert not a.page_links(page, BASE + "/category?page=3", "")
    links = a.page_links(page, BASE + "/category?page=2", "")
    assert links[0]["path"] == BASE + "/category?page=3"


def test_subcategory_discovery_ignores_global_navigation_and_footer(settings):
    page = '<header><a href="/yugioh"><img src="/media/image/category/2/x.jpg"></a></header>'
    page += '<div id="result-wrapper"><a href="/pokemon"><img src="/media/image/category/1/x.jpg"></a></div>'
    a = StructuredHtmlAdapter(client(settings, lambda r: httpx.Response(404)), {"crawl_subcategories": True})
    assert a.page_links(page, BASE + "/category", "Pokemon") == [{"path": BASE + "/pokemon", "game": "Pokemon"}]


@pytest.mark.parametrize("title", ["Yu-Gi-Oh Booster Display", "Magic The Gathering Booster", "Disney Lorcana Display", "Gundam Card Game Booster"])
def test_other_games_are_not_mislabeled_by_broad_category_hints(title, settings):
    a = StructuredHtmlAdapter(client(settings, lambda r: httpx.Response(404)), {})
    offer = a.offer(title, BASE + "/other", "4.99", "EUR", "in_stock", labels="Pokemon")
    assert classify(offer, "fixture") is None


def test_scanner_commits_partial_import_and_resumes_after_rate_limit(factory, settings):
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop.adapter = "structured_html"
        shop.config = {"full_catalog": True, "categories": [{"path": "/category"}]}
        id = shop.id
        db.commit()
    blocked = True
    calls = []
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/category":
            return httpx.Response(200, text=html([html_product(1), html_product(2), html_product(3)]))
        calls.append(request.url.path)
        if request.url.path == "/booster-2" and blocked:
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, text=html(html_product(int(request.url.path.rsplit("-", 1)[-1]))))
    result = scan_shop(factory, id, settings, httpx.MockTransport(handler), force=True)
    assert result["offers"] == 1 and "error" in result and not result["catalog_complete"]
    with factory() as db:
        shop = db.get(Merchant, id)
        assert shop.crawl_state["completed_at"] is None
        assert shop.crawl_state["cursor"]["pending"][0]["url"].endswith("booster-2")
        assert db.scalar(select(Offer)).availability == "in_stock"
    blocked = False
    result = scan_shop(factory, id, settings, httpx.MockTransport(handler), force=True)
    assert result["catalog_complete"] and result["offers"] == 2
    with factory() as db:
        shop = db.get(Merchant, id)
        assert shop.crawl_state["cursor"] is None
        assert datetime.fromisoformat(shop.crawl_state["completed_at"])
        assert shop.last_offer_count == 3
        assert db.scalar(select(func.count(Offer.id))) == 3
        assert db.scalar(select(func.count(OfferEvent.id))) == 3
    assert calls == ["/booster-1", "/booster-2", "/booster-2", "/booster-3"]
    with TestClient(create_app(settings, factory)) as api:
        response = api.get("/api/shops", headers={"X-Radar-Key": settings.api_key}).json()[0]
        assert response["catalog_progress"]["in_progress"] is False
        assert response["catalog_progress"]["scanned"] == 3
        assert "cursor" not in response["catalog_progress"]
        assert "pending" not in response["catalog_progress"]
