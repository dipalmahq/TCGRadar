"""Spielewelt regression: generic Shopify availability can disagree with shipping."""
import json

import httpx
import pytest
from sqlalchemy import select

from app.adapters.base import AvailabilityError, ShopClient, SourceError
from app.adapters.structured_html import StructuredHtmlAdapter
from app.models import Merchant, Offer
from app.scanner import scan_shop

BASE = "https://fixture.example"
ENDPOINT = "https://fixture-shop.myshopify.com/api/2026-10/graphql.json"
VARIANT = "66340273488221"
URL = BASE + "/products/one-piece-heroines-display?variant=" + VARIANT
CONFIG = {"markup": "shopify", "shipping_availability_endpoint": ENDPOINT}


def page():
    product = {"@type": "Product", "name": "One Piece EB05 Heroines Display EN", "url": URL.split("?")[0],
               "offers": {"@type": "Offer", "price": "199.90", "priceCurrency": "EUR",
                          "url": URL, "availability": "https://schema.org/InStock"}}
    return '<script type="application/ld+json">' + json.dumps(product) + '</script><button hidden>Ausverkauft</button>'


def node(available=False, backorder=False, id=VARIANT):
    return {"id": "gid://shopify/ProductVariant/" + id, "availableForSale": available, "currentlyNotInStock": backorder}


def transport(payload=None, response_status=200):
    def handler(request):
        if request.url.host == "fixture-shop.myshopify.com":
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["query"].startswith("query ShippingAvailability") and "mutation" not in body["query"]
            assert body["variables"]["ids"] == ["gid://shopify/ProductVariant/" + VARIANT]
            assert "X-Shopify-Access-Token" not in request.headers
            return httpx.Response(response_status, json=payload if payload is not None else {}, headers={"Retry-After": "120"})
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=page())
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("available,backorder,expected", [
    (False, False, "out_of_stock"), (True, False, "in_stock"), (True, True, "preorder"),
])
def test_shipping_status_overrides_jsonld_but_hidden_sold_out_text_does_not(settings, available, backorder, expected):
    client = ShopClient(BASE, settings, transport({"data": {"nodes": [node(available, backorder)]}}))
    offer, = StructuredHtmlAdapter(client, CONFIG).fetch_url(URL)
    assert offer.external_id == VARIANT
    assert offer.availability == expected
    assert offer.price_minor == 19990


@pytest.mark.parametrize("payload", [
    {"errors": [{"message": "Unavailable"}]}, {"data": None}, [],
    {"data": {"nodes": []}}, {"data": {"nodes": [node(id="999")]}},
    {"data": {"nodes": [{**node(), "availableForSale": "false"}]}},
])
def test_incomplete_shipping_evidence_never_falls_back_to_instock(settings, payload):
    client = ShopClient(BASE, settings, transport(payload))
    with pytest.raises(AvailabilityError) as caught:
        StructuredHtmlAdapter(client, CONFIG).fetch_url(URL)
    offer, = caught.value.offers
    assert offer.availability == "unknown"
    assert offer.availability_error.startswith("Versandverfügbarkeit nicht bestätigt")


def test_missing_storefront_variant_matches_website_unavailable_behavior(settings):
    client = ShopClient(BASE, settings, transport({"data": {"nodes": [None]}}))
    offer, = StructuredHtmlAdapter(client, CONFIG).fetch_url(URL)
    assert offer.availability == "out_of_stock"


@pytest.mark.parametrize("endpoint", [
    "http://fixture-shop.myshopify.com/api/2026-10/graphql.json",
    "https://evil.example/api/2026-10/graphql.json",
    "https://fixture-shop.myshopify.com.evil.example/api/2026-10/graphql.json",
    "https://fixture-shop.myshopify.com/admin/api/2026-10/graphql.json",
    "https://fixture-shop.myshopify.com:bad/api/2026-10/graphql.json",
    "https://user:secret@fixture-shop.myshopify.com/api/2026-10/graphql.json",
])
def test_shipping_endpoint_cannot_redirect_queries_to_arbitrary_origins(settings, endpoint):
    client = ShopClient(BASE, settings, transport())
    with pytest.raises(SourceError, match="Invalid configured"):
        client.storefront_availability(endpoint, [VARIANT])
    assert client.requests == 0


def test_shipping_rate_limit_saves_unknown_status_and_resumable_cursor(factory, settings):
    with factory() as db:
        shop = db.scalar(select(Merchant))
        shop.adapter = "structured_html"
        shop.config = {**CONFIG, "full_catalog": True, "categories": [{"path": "/category"}]}
        id = shop.id
        db.commit()
    result = scan_shop(factory, id, settings, transport(response_status=429), force=True)
    assert "error" in result and not result["catalog_complete"]
    with factory() as db:
        offer = db.scalar(select(Offer))
        assert offer.availability == "unknown"
        assert offer.source_error.startswith("Versandverfügbarkeit nicht bestätigt")
        assert db.get(Merchant, id).crawl_state["cursor"]["pending"]
