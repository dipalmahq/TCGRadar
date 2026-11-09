"""Regressions for the five findings in the November quality review."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.adapters import ADAPTERS
from app.adapters.base import ScanResult, ShopAdapter, ShopClient, SourceError, SourceOffer, retry_after_seconds
from app.adapters.structured_html import StructuredHtmlAdapter
from app.db import utcnow
from app.domain import classify
from app.events import ingest
from app.main import create_app
from app.models import Merchant, Offer, OfferEvent, WatchTarget
from app.scanner import scan_shop

BASE = "https://fixture.example"


def source(id="1"):
    return SourceOffer(id, "Pokemon Booster Deutsch", BASE + "/products/booster?variant=" + id, 499, "EUR", "in_stock")


def ld(data):
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>'


def shop_client(settings, handler):
    def route(request):
        return httpx.Response(404) if request.url.path == "/robots.txt" else handler(request)
    return ShopClient(BASE, settings, httpx.MockTransport(route))


def test_full_catalog_outage_invalidates_public_stock_and_recovers_without_false_restock(factory, settings):
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop.config = {"full_catalog": True}
        id = shop.id
        db.commit()
    blocked = False
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if blocked:
            return httpx.Response(403)
        return httpx.Response(200, json={"products": [{"id": 1, "title": "Pokemon Booster Deutsch", "handle": "booster",
                                                       "variants": [{"id": 1, "price": "4.99", "available": True}]}]})
    scan_shop(factory, id, settings, httpx.MockTransport(handler), force=True)
    blocked = True
    assert "error" in scan_shop(factory, id, settings, httpx.MockTransport(handler), force=True)
    with TestClient(create_app(settings, factory)) as api:
        offer, = api.get("/api/offers", headers={"X-Radar-Key": settings.api_key}).json()["items"]
        assert offer["availability"] == "unknown" and offer["source_error"]
    blocked = False
    result = scan_shop(factory, id, settings, httpx.MockTransport(handler), force=True)
    assert result["events"] == 0
    with factory() as db:
        offer = db.scalar(select(Offer))
        assert offer.availability == "in_stock" and offer.source_error is None
        assert db.scalar(select(func.count(OfferEvent.id))) == 1


def test_partial_outage_keeps_only_independently_verified_offers(factory, settings, monkeypatch):
    class PartialAdapter(ShopAdapter):
        def discover_batch(self, cursor=None):
            return ScanResult(offers=[source("1")], complete=False, next_cursor={"page": 2},
                              source_error="Source returned HTTP 503")
    monkeypatch.setitem(ADAPTERS, "partial", PartialAdapter)
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop.adapter, shop.config = "partial", {"full_catalog": True}
        id = shop.id
        ingest(db, shop, source("1"))
        ingest(db, shop, source("2"))
        db.commit()
    scan_shop(factory, id, settings, httpx.MockTransport(lambda r: httpx.Response(404)), force=True)
    with factory() as db:
        offers = {o.external_id: o for o in db.scalars(select(Offer))}
        assert offers["1"].availability == "in_stock" and offers["1"].source_error is None
        assert offers["2"].availability == "unknown" and offers["2"].source_error
        assert db.get(Merchant, id).crawl_state["cursor"] == {"page": 2}


@pytest.mark.parametrize("title,game", [("Pokemon Testset", ""), ("Testset", "Pokemon")])
def test_description_evidence_is_used_before_discovery_prefilter(settings, title, game):
    product = {"@type": "Product", "name": title, "url": BASE + "/product",
               "description": "Display mit 36 Booster, Deutsch", "offers": {"@type": "Offer", "price": "129.95"}}
    a = StructuredHtmlAdapter(shop_client(settings, lambda r: httpx.Response(200, text=ld(product))),
                              {"full_catalog": True, "categories": [{"path": "/category", "game": game}]})
    result = a.discover_batch()
    assert result.complete and len(result.offers) == 1 and not result.warnings
    assert classify(result.offers[0], "fixture").product_type == "display"


def variants(named=True):
    return {"@type": "Product", "name": "Pokemon Booster / Display", "url": BASE + "/products/testset",
            "description": "Display mit 36 Booster, Deutsch", "offers": [
                {"@type": "Offer", "url": BASE + "/products/testset?variant=1", "price": "4.99", **({"name": "Booster"} if named else {})},
                {"@type": "Offer", "url": BASE + "/products/testset?variant=2", "price": "129.95", **({"name": "Display"} if named else {})},
            ]}


@pytest.mark.parametrize("variant,price,type,count", [("1", 499, "booster", 1), ("2", 12995, "display", 36)])
def test_exact_variant_selects_own_price_and_packaging(settings, variant, price, type, count):
    a = StructuredHtmlAdapter(shop_client(settings, lambda r: httpx.Response(404)), {"markup": "shopify"})
    offer, = a.parse(ld(variants()), BASE + "/products/testset?variant=" + variant, detail=True)
    identity = classify(offer, "fixture")
    assert offer.external_id == variant and offer.price_minor == price
    assert (identity.product_type, identity.booster_count) == (type, count)


def test_root_discovery_keeps_all_resolved_variants_instead_of_only_last(settings):
    page = ld(variants())
    a = StructuredHtmlAdapter(shop_client(settings, lambda r: httpx.Response(200, text=page)),
                              {"markup": "shopify", "full_catalog": True, "categories": [{"path": "/category"}]})
    result = a.discover_batch()
    assert result.complete and {o.external_id for o in result.offers} == {"1", "2"}
    assert result.scanned_count == 1


def test_unresolved_mixed_pack_sizes_and_duplicate_variant_ids_still_rejected(settings):
    a = StructuredHtmlAdapter(shop_client(settings, lambda r: httpx.Response(404)), {"markup": "shopify"})
    assert a.parse(ld(variants(named=False)), BASE + "/products/testset?variant=1", detail=True) == []
    data = variants()
    data["offers"][1]["url"] = data["offers"][0]["url"]
    assert a.parse(ld(data), BASE + "/products/testset?variant=1", detail=True) == []


@pytest.mark.parametrize("label", ["Default Title", "English"])
def test_variant_label_must_resolve_mixed_packaging(settings, label):
    data = variants()
    data["offers"][0]["name"] = label
    a = StructuredHtmlAdapter(shop_client(settings, lambda r: httpx.Response(404)), {"markup": "shopify"})
    assert a.parse(ld(data), BASE + "/products/testset?variant=1", detail=True) == []


def test_shared_parent_gtin_not_assigned_to_each_variant(settings):
    data = variants()
    data["gtin13"] = "4006381333931"
    a = StructuredHtmlAdapter(shop_client(settings, lambda r: httpx.Response(404)), {"markup": "shopify"})
    assert all(o.gtin is None for o in a.parse(ld(data), BASE + "/products/testset", detail=True))


def trader_form(category):
    return f'''<form id="esFilterList"><input name="cl" value="alist"><input name="fnc" value="executefilter">
      <input name="cnid" value="{category}"><input name="lang" value="0"></form>'''


def trader_handler(calls, repeat=False):
    def handler(request):
        if request.method == "POST":
            assert request.url.path == "/index.php"
            fields = parse_qs(request.content.decode())
            assert fields["cl"] == ["alist"] and fields["fnc"] == ["executefilter"]
            assert fields["ajax"] == ["1"]
            category, page = fields["cnid"][0], int(fields["attrfilter[page]"][0])
            calls.append((category, page))
            id = (1 if page == 0 or repeat else 2) if category == "pokemon" else 3
            nav = '<ul class="pagination">' + ''.join(f'<li class="{"active" if n == page + 1 else ""}"><span data-page-number="{n}">{n}</span></li>' for n in (1, 2)) + '</ul>' if category == "pokemon" else ''
            card = f'<div class="product-card"><a class="stretched-link" href="{BASE}/item-{id}"></a><div class="card-title">Pokemon Display {id} Deutsch</div><div class="grid-price">129,95 €</div></div>'
            return httpx.Response(200, json={"filters": nav, "productList": card})
        if request.url.path in ("/pokemon", "/one-piece"):
            return httpx.Response(200, text=trader_form(request.url.path[1:]) + '<link rel="next" href="2">')
        if request.url.path.startswith("/item-"):
            return httpx.Response(200, text='<h1>Pokemon Display Deutsch</h1><div id="productPrice"><span class="price">129,95 €</span></div><div class="info-delivery-stock">Sofort lieferbar</div>')
        return httpx.Response(404)
    return handler


def test_trader_ajax_pagination_advances_and_reaches_next_category(settings):
    calls, cursor, offers = [], None, []
    config = {"markup": "trader", "pagination": "trader_ajax", "full_catalog": True,
              "categories": [{"path": "/pokemon"}, {"path": "/one-piece"}]}
    for _ in range(3):
        result = StructuredHtmlAdapter(shop_client(settings, trader_handler(calls)), config).discover_batch(cursor)
        assert not result.source_error
        offers.extend(result.offers)
        cursor = result.next_cursor
    assert result.complete and len(offers) == 3
    assert calls == [("pokemon", 0), ("pokemon", 1), ("one-piece", 0)]


def test_trader_repeated_ajax_page_is_not_mistaken_for_complete(settings):
    config = {"markup": "trader", "pagination": "trader_ajax", "full_catalog": True,
              "categories": [{"path": "/pokemon"}]}
    first = StructuredHtmlAdapter(shop_client(settings, trader_handler([])), config).discover_batch()
    repeated = StructuredHtmlAdapter(shop_client(settings, trader_handler([], repeat=True)), config).discover_batch(first.next_cursor)
    assert "repeated" in repeated.source_error and not repeated.complete
    assert repeated.next_cursor == first.next_cursor


def test_trader_filter_still_obeys_robots_and_blocks_cart_actions(settings):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="User-agent: *\nDisallow: /index.php")
    c = ShopClient(BASE, settings, httpx.MockTransport(handler))
    fields = {"cl": "alist", "fnc": "executefilter", "cnid": "fixture", "ajax": "1", "attrfilter[page]": "0"}
    with pytest.raises(SourceError, match="disallows"):
        c.trader_catalog(fields)
    assert not any(r.method == "POST" for r in requests)
    with pytest.raises(SourceError, match="Invalid read-only"):
        c.trader_catalog({**fields, "fnc": "tobasket"})


@pytest.mark.parametrize("value,expected", [("120", 120), (" 120 ", 120), ("bad-date", 30), ("", 30)])
def test_retry_after_delay_and_invalid_values(value, expected):
    assert retry_after_seconds(value) == expected


def test_retry_after_http_date_and_past_date():
    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    assert retry_after_seconds(format_datetime(now + timedelta(minutes=20), usegmt=True), now) == 1200
    assert retry_after_seconds(format_datetime(now - timedelta(minutes=20), usegmt=True), now) == 0


@pytest.mark.parametrize("full_catalog,status", [(True, 429), (False, 429), (True, 503), (False, 503)])
def test_retry_after_absolute_deadline_is_preserved_by_scanner(factory, settings, full_catalog, status):
    deadline = (utcnow() + timedelta(minutes=30)).replace(microsecond=0)
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop.config = {"full_catalog": full_catalog, "max_pages": 1}
        id = shop.id
        db.commit()
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(status, headers={"Retry-After": format_datetime(deadline, usegmt=True)})
    assert "error" in scan_shop(factory, id, settings, httpx.MockTransport(handler), force=True)
    with factory() as db:
        next_check = db.get(Merchant, id).next_check_at
        if next_check.tzinfo is None:
            next_check = next_check.replace(tzinfo=timezone.utc)
        assert next_check >= deadline


def test_watches_do_not_bypass_retry_after_from_catalog(factory, settings):
    requests = []
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop.config = {"full_catalog": True}
        id = shop.id
        db.add(WatchTarget(merchant_id=id, url=BASE + "/products/booster?variant=1"))
        db.commit()
    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(429, headers={"Retry-After": "1200"})
    scan_shop(factory, id, settings, httpx.MockTransport(handler), force=True)
    assert requests == ["/robots.txt", "/products.json"]
    with factory() as db:
        assert db.scalar(select(WatchTarget)).last_error
