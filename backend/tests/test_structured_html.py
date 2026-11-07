"""Synthetic markup: variant, recommendation and online-stock regressions."""
import json

import httpx
import pytest

from app.adapters.base import ShopClient, SourceError
from app.adapters.structured_html import StructuredHtmlAdapter
from app.domain import classify

BASE = "https://fixture.example"
URL = BASE + "/pokemon-display"


def adapter(settings, config=None, routes=None):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        content = (routes or {}).get(request.url.path)
        return httpx.Response(200, text=content) if content is not None else httpx.Response(404)
    return StructuredHtmlAdapter(ShopClient(BASE, settings, httpx.MockTransport(handler)), config or {})


def ld(product):
    return '<script type="application/ld+json">' + json.dumps(product) + '</script>'


def product(**changes):
    return {"@type": "Product", "name": "Pokemon Display Deutsch", "url": URL,
            "sku": "SYNTHETIC", "offers": {"@type": "Offer", "price": "129.95",
            "priceCurrency": "EUR", "availability": "https://schema.org/InStock"}, **changes}


def test_jsonld_item_list_and_detail_have_same_identity(settings):
    a = adapter(settings)
    listing = ld({"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "item": product()}]})
    discovery = a.parse(listing, BASE + "/category")
    detail = a.parse(ld(product(sku="CHANGED-SKU")), URL, detail=True)
    assert len(discovery) == len(detail) == 1
    assert discovery[0].external_id == detail[0].external_id
    assert detail[0].price_minor == 12995
    assert detail[0].availability == "in_stock"


@pytest.mark.parametrize("offers", [
    {"@type": "AggregateOffer", "lowPrice": "4.99", "highPrice": "129.95"},
    [{"@type": "Offer", "price": "4.99"}, {"@type": "Offer", "price": "129.95"}],
])
def test_jsonld_ambiguous_variant_prices_are_not_imported(settings, offers):
    assert adapter(settings).parse(ld(product(offers=offers)), URL, detail=True) == []


def test_detail_does_not_substitute_recommendation_or_shop_rating(settings):
    a = adapter(settings)
    page = ld([product(url=BASE + "/recommendation"), {"@type": "Product", "name": "Shop rating"}])
    assert a.parse(page, URL, detail=True) == []


def test_nested_brand_and_related_product_do_not_replace_title_or_stock(settings):
    page = f'''<div itemscope itemtype="https://schema.org/Product">
      <meta itemprop="url" content="{URL}">
      <div itemprop="brand" itemscope itemtype="https://schema.org/Brand"><meta itemprop="name" content="Pokemon"></div>
      <h2 itemprop="name">Pokemon Display Deutsch</h2>
      <link itemprop="availability" href="https://schema.org/OutOfStock">
      <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
        <meta itemprop="price" content="129.95"><meta itemprop="priceCurrency" content="EUR">
      </div>
      <div itemprop="isRelatedTo" itemscope itemtype="https://schema.org/Product">
        <meta itemprop="url" content="{BASE}/other"><span itemprop="name">Pokemon Booster</span>
        <div class="delivery-status">Auf Lager</div>
        <div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><meta itemprop="price" content="4.99"></div>
      </div>
    </div>'''
    offer, = adapter(settings).parse(page, URL, detail=True)
    assert (offer.title, offer.price_minor, offer.availability) == ("Pokemon Display Deutsch", 12995, "out_of_stock")


def test_microdata_variant_range_is_skipped_but_single_price_is_accepted(settings):
    template = f'''<div itemscope itemtype="https://schema.org/Product">
      <h1 itemprop="name">Pokemon Display</h1><meta itemprop="url" content="{URL}">
      <div itemprop="offers" itemtype="https://schema.org/Offer" itemscope>
        <meta itemprop="minPrice" content="4.99"><meta itemprop="maxPrice" content="MAX">
        <meta itemprop="price" content="4.99">
      </div></div>'''
    a = adapter(settings)
    assert a.parse(template.replace("MAX", "129.95"), URL, detail=True) == []
    offer, = a.parse(template.replace("MAX", "4.99"), URL, detail=True)
    assert offer.price_minor == 499
    assert offer.availability == "unknown"


@pytest.mark.parametrize("availability, expected", [("OutOfStock", "out_of_stock"), ("PreOrder", "preorder"), (None, "unknown")])
def test_jsonld_does_not_infer_online_stock_from_store_pickup(settings, availability, expected):
    offer = {"@type": "Offer", "price": 5.99, "availability": availability and "https://schema.org/" + availability}
    page = '<span>In die Filiale lieferbar</span>' + ld(product(offers=[offer]))
    actual, = adapter(settings).parse(page, URL, detail=True)
    assert actual.availability == expected


def test_discovery_fetches_details_and_deduplicates_category_overlap(settings):
    category = ld({"@graph": [product()]})
    detail = ld(product(offers={"@type": "Offer", "price": "139.95", "availability": "https://schema.org/OutOfStock"}))
    a = adapter(settings, {"categories": [{"path": "/category"}, {"path": "/category2"}]},
                {"/category": category, "/category2": category, "/pokemon-display": detail})
    result = a.discover()
    assert len(result.offers) == result.scanned_count == 1
    assert result.offers[0].price_minor == 13995
    assert result.offers[0].availability == "out_of_stock"
    assert result.coverage_limited


def test_all_failed_details_fail_scan_instead_of_reporting_success(settings):
    a = adapter(settings, {"categories": [{"path": "/category"}]}, {"/category": ld(product())})
    with pytest.raises(SourceError, match="No concrete product"):
        a.discover()


def test_access_challenge_and_foreign_product_urls_are_rejected(settings):
    a = adapter(settings)
    with pytest.raises(SourceError, match="access challenge"):
        a.parse("<title>Pardon Our Interruption</title>", URL)
    with pytest.raises(SourceError, match="outside configured"):
        a.parse(ld(product(url="https://evil.example/product")), URL)


def test_trader_detail_uses_own_price_stock_and_game_not_recommendations(settings):
    page = '''<h1>OP-17 Booster Display (24 Booster) englisch</h1>
      <div id="productPrice"><span class="price-from"></span><span class="price">1.299,95 €</span></div>
      <div class="info-delivery-stock"><span class="stockFlag">Sofort lieferbar</span></div>
      <div class="product-card"><span class="card-title">Pokemon Booster</span></div>'''
    url = BASE + "/pokemon/display.html"
    offer, = adapter(settings, {"markup": "trader"}).parse(page, url, detail=True)
    assert (offer.price_minor, offer.availability) == (129995, "in_stock")
    assert classify(offer, "fixture").product_type == "display"


def test_trader_sold_out_page_is_not_overwritten_by_in_stock_recommendation(settings):
    page = f'''<h1>Pokemon Booster Display</h1>
      <div id="productPrice"><span class="price">129,95 €</span></div>
      <div class="delivery-alarm info-delivery-stock">Dieser Artikel ist nicht auf Lager.</div>
      <div class="product-card"><a class="stretched-link" href="{URL}"></a>
        <span class="card-title">Pokemon Booster Display</span>
        <div class="grid-price">99,95 €</div><span class="stockFlag">Sofort lieferbar</span></div>'''
    offer, = adapter(settings, {"markup": "trader"}).parse(page, URL, detail=True)
    assert (offer.price_minor, offer.availability) == (12995, "out_of_stock")


def test_shopify_html_discovery_canonicalizes_collection_links_and_skips_ambiguous_variants(settings):
    category = '<a href="/collections/displays/products/pokemon-display"><img alt="Pokemon Display"></a>'
    category += '<a href="/products/pokemon-display">Pokemon Display</a>'
    detail = ld(product())
    a = adapter(settings, {"markup": "shopify", "categories": [{"path": "/category"}]},
                {"/category": category, "/pokemon-display": detail})
    candidates = a.candidate_links(category, BASE + "/category")
    assert len(candidates) == 1
    assert candidates[0].url == BASE + "/products/pokemon-display"


def test_rate_limit_ends_scan_without_trying_other_products(settings):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/category":
            return httpx.Response(200, text=ld([product(), product(url=BASE + "/other")]))
        return httpx.Response(429, headers={"Retry-After": "60"})
    a = StructuredHtmlAdapter(ShopClient(BASE, settings, httpx.MockTransport(handler)),
                              {"categories": [{"path": "/category"}]})
    with pytest.raises(SourceError, match="rate limit"):
        a.discover()
    assert BASE + "/other" not in paths
    assert "/other" not in paths


def test_shopify_single_variant_keeps_variant_id_for_direct_watch_matching(settings):
    a = adapter(settings, {"markup": "shopify"})
    page = ld(product(offers={"@type": "Offer", "price": "129.95", "url": URL + "?variant=123"}))
    offer, = a.parse(page, URL, detail=True)
    assert offer.external_id == "123"
    assert a.parse(page, URL + "?variant=999", detail=True) == []
