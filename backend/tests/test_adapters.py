import gzip
import json
from pathlib import Path

import httpx
import pytest

from app.adapters.base import ScanResult, ShopClient, SourceError
from app.adapters.shopify import ShopifyAdapter
from app.adapters.woocommerce import WooCommerceAdapter
from app.domain import classify

FIXTURES = Path(__file__).parent / "fixtures"


def transport_for(routes):
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        response = routes.get(request.url.path)
        return httpx.Response(200, json=response) if response is not None else httpx.Response(404)
    return httpx.MockTransport(handle)


def test_shopify_discovery_and_known_url(settings):
    data = json.loads((FIXTURES / "shopify.json").read_text())
    detail = {**data["products"][0], "variants": [{**data["products"][0]["variants"][0], "price": 12995}]}
    client = ShopClient("https://fixture.example", settings, transport_for({"/products.json": data, "/products/one-piece-op17-display.js": detail}))
    adapter = ShopifyAdapter(client, {"max_pages": 1})
    result = adapter.discover()
    assert len(result.offers) == 2
    assert result.offers[0].price_minor == 12995
    assert result.offers[1].availability == "preorder"
    assert len(adapter.fetch_url("https://fixture.example/products/one-piece-op17-display?variant=201")) == 1
    assert adapter.fetch_url("https://fixture.example/products/one-piece-op17-display?variant=201")[0].price_minor == 12995
    assert adapter.fetch_url("https://fixture.example/products/one-piece-op17-display?variant=999") == []


def test_woocommerce_expands_variants_without_using_parent_min_price(settings):
    data = json.loads((FIXTURES / "woocommerce.json").read_text())
    client = ShopClient("https://fixture.example", settings, transport_for({"/wp-json/wc/store/v1/products/302": data["booster"], "/wp-json/wc/store/v1/products/303": data["display"]}))
    adapter = WooCommerceAdapter(client, {})
    result = ScanResult()
    assert adapter.parse_product(data["parent"]) is None
    offers = adapter.expand_product(data["parent"], result)
    assert len(offers) == 2
    assert [o.price_minor for o in offers] == [499, 13999]
    assert [classify(o, "a").product_type for o in offers] == ["booster", "display"]
    assert [classify(o, "a").booster_count for o in offers] == [1, 36]
    assert offers[1].availability == "out_of_stock"


def test_failed_variants_are_skipped_not_cheap_displays(settings):
    data = json.loads((FIXTURES / "woocommerce.json").read_text())
    client = ShopClient("https://fixture.example", settings, transport_for({}))
    result = ScanResult()
    assert WooCommerceAdapter(client, {}).expand_product(data["parent"], result) == []
    assert len(result.warnings) == 2


def test_same_origin_and_robots_restrictions(settings):
    client = ShopClient("https://fixture.example", settings, transport_for({}))
    for url in ("http://fixture.example/x", "https://evil.example/a", "https://fixture.example@evil.example/a", "https://fixture.example:444/x"):
        with pytest.raises(SourceError):
            client.get(url)
    with pytest.raises(SourceError, match="disallows"):
        client.get("/private/catalog")


def test_compressed_responses_are_not_decoded_twice(settings):
    payload = gzip.compress(b'{"products": []}')
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=payload)
    client = ShopClient("https://fixture.example", settings, httpx.MockTransport(handler))
    assert client.json("/products.json") == {"products": []}


def test_foreign_redirect_is_blocked(settings):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})
    client = ShopClient("https://fixture.example", settings, httpx.MockTransport(handler))
    with pytest.raises(SourceError, match="origin"):
        client.get("/products.json")
