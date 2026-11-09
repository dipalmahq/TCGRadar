"""Card-Corner editorial set overviews must not stall a saved catalog crawl."""
from copy import deepcopy
import json

import httpx
import pytest

from app.adapters.base import ShopClient, SourceError
from app.adapters.structured_html import StructuredHtmlAdapter


BASE = "https://fixture.example"
CONFIG = {
    "full_catalog": True,
    "crawl_subcategories": True,
    "categories": [{"path": "/sets", "game": "One Piece"}],
}
OVERVIEW = '''<div id="content">
  <div id="result-wrapper"><input id="product-list-type" type="hidden" value="list"></div>
  <div class="set-grid">
    <div class="set-card">
      <a href="/op-18"><img src="/media/image/opc/op18.webp" alt="One Piece OP18"></a>
      <div class="opc-Button"><a href="/op-18">ALLE PRODUKTE <span>»</span></a></div>
      <div class="opc-Button"><a href="/op-18">Alle Produkte</a></div>
      <div class="opc-Button"><a href="/card-list">Kartenliste</a></div>
    </div>
    <div class="set-card"><div class="opc-Button"><a href="/eb-05">ALLE PRODUKTE</a></div></div>
    <div class="set-card"><div class="opc-Button"><a href="/op-17">ALLE PRODUKTE</a></div></div>
  </div>
</div>'''


def adapter(settings, routes=None):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=(routes or {})[request.url.path])
    return StructuredHtmlAdapter(ShopClient(BASE, settings, httpx.MockTransport(handler)), CONFIG)


def test_editorial_set_buttons_are_discovered_outside_empty_product_list(settings):
    a = adapter(settings)
    assert a.page_links(OVERVIEW, BASE + "/sets", "One Piece") == [
        {"path": BASE + path, "game": "One Piece"}
        for path in ("/op-18", "/eb-05", "/op-17")
    ]


def test_editorial_category_resumes_existing_cursor_and_imports_all_sets(settings):
    routes = {"/sets": OVERVIEW}
    for path in ("/op-18", "/eb-05", "/op-17", "/pokemon"):
        title = "Pokemon Booster Deutsch" if path == "/pokemon" else "One Piece " + path[1:] + " Booster Display Englisch"
        routes[path] = '<script type="application/ld+json">' + json.dumps({
            "@type": "Product", "name": title, "url": BASE + path,
            "offers": {"@type": "Offer", "price": "99.95", "availability": "https://schema.org/InStock"},
        }) + '</script>'
    cursor = {"frontier": [{"path": "/sets", "game": "One Piece"},
                            {"path": "/pokemon", "game": "Pokemon"}],
              "visited": [BASE + "/already-scanned"], "seen_products": [], "pending": [], "game": "Pokemon"}
    original = deepcopy(cursor)
    first = adapter(settings, routes).discover_batch(cursor)
    assert cursor == original
    assert not first.source_error and first.pages_scanned == 1 and not first.complete
    assert not first.offers
    assert BASE + "/already-scanned" in first.next_cursor["visited"]
    cursor, offers, pages = first.next_cursor, [], first.pages_scanned
    for _ in range(4):
        result = adapter(settings, routes).discover_batch(cursor)
        assert not result.source_error
        offers.extend(result.offers)
        pages += result.pages_scanned
        cursor = result.next_cursor
    assert result.complete and cursor is None and pages == 5
    assert {o.url for o in offers} == {BASE + path for path in ("/op-18", "/eb-05", "/op-17", "/pokemon")}


def test_editorial_navigation_excludes_header_footer_and_outside_content(settings):
    card = '<div class="set-card"><div class="opc-Button"><a href="/unrelated">ALLE PRODUKTE</a></div></div>'
    page = card + '<div id="content"><header>' + card + '</header>' + OVERVIEW + '<footer>' + card + '</footer></div>'
    assert {x["path"] for x in adapter(settings).page_links(page, BASE + "/sets", "One Piece")} == {
        BASE + path for path in ("/op-18", "/eb-05", "/op-17")
    }


def test_standard_subcategory_images_outside_product_list_are_preserved(settings):
    page = '<div id="content"><div id="result-wrapper"></div><a href="/leaf"><img src="/media/image/category/1/test.jpg"></a></div>'
    assert adapter(settings).page_links(page, BASE + "/sets", "One Piece") == [
        {"path": BASE + "/leaf", "game": "One Piece"}
    ]


@pytest.mark.parametrize("page", [
    '<div id="content"><div id="result-wrapper"></div></div>',
    '<title>Just a moment</title>' + OVERVIEW,
    OVERVIEW.replace("ALLE PRODUKTE", "Kartenliste").replace("Alle Produkte", "Kartenliste"),
])
def test_empty_unrecognized_and_challenge_pages_still_fail(settings, page):
    result = adapter(settings, {"/sets": page}).discover_batch()
    assert result.source_error and not result.complete
    assert result.next_cursor["frontier"][0]["path"] == "/sets"


def test_editorial_buttons_cannot_escape_configured_shop_origin(settings):
    with pytest.raises(SourceError, match="outside configured"):
        adapter(settings).page_links(OVERVIEW.replace('href="/op-18"', 'href="https://other.example/op-18"'), BASE + "/sets", "One Piece")


LANGUAGES = '''<div id="content"><div id="result-wrapper"></div>
  <div class="category-slider-wrapper">
    <div><a class="stretched-link" href="/sets-de"><img src="/media/image/storage/opc/de.webp">Deutsche Sets</a></div>
    <div><a class="stretched-link" href="/sets-en"><img src="/media/image/storage/opc/en.webp">Englische Sets</a></div>
    <div><a class="stretched-link" href="/sets-jp"><img src="/media/image/storage/opc/jp.webp">Japanische Sets</a></div>
  </div><div class="opc-Button"><a href="/contact">Schreib uns eine Nachricht!</a></div></div>'''


def test_language_overview_cards_with_storage_icons_are_catalog_navigation(settings):
    assert adapter(settings).page_links(LANGUAGES, BASE + '/all-sets', 'Pokemon') == [
        {'path': BASE + '/sets-' + language, 'game': 'Pokemon'} for language in ('de', 'en', 'jp')
    ]


@pytest.mark.parametrize('label', ['ZUM SET', 'Zum Set »', 'ALLE PRODUKTE'])
def test_set_buttons_do_not_require_a_set_card_wrapper(settings, label):
    page = '<div id="content"><div class="opc-Button"><a href="/set">' + label + '</a></div>'
    page += '<div class="opc-Button"><a href="/set">ZUM SET</a></div><div class="opc-Button"><a href="/cards">Kartenliste</a></div></div>'
    assert adapter(settings).page_links(page, BASE + '/sets-de', 'Pokemon') == [{'path': BASE + '/set', 'game': 'Pokemon'}]


def test_existing_cursor_resumes_through_language_and_set_overviews(settings):
    routes = {'/all-sets': LANGUAGES}
    for language in ('de', 'en', 'jp'):
        routes['/sets-' + language] = '<div id="content"><div class="opc-Button"><a href="/leaf-' + language + '">ZUM SET</a></div></div>'
        routes['/leaf-' + language] = '<script type="application/ld+json">' + json.dumps({
            '@type': 'Product', 'name': 'Pokemon Display ' + language, 'url': BASE + '/leaf-' + language,
            'offers': {'@type': 'Offer', 'price': '99.95', 'availability': 'https://schema.org/InStock'},
        }) + '</script>'
    cursor = {'frontier': [{'path': '/all-sets', 'game': 'Pokemon'}], 'pending': [],
              'visited': [BASE + '/already-visited'], 'seen_products': ['existing-product'], 'game': 'Pokemon'}
    original = deepcopy(cursor)
    initial_cursor = cursor
    offers, pages = [], 0
    for _ in range(7):
        result = adapter(settings, routes).discover_batch(cursor)
        assert not result.source_error
        offers.extend(result.offers); pages += result.pages_scanned
        cursor = result.next_cursor
        if cursor:
            assert BASE + '/already-visited' in cursor['visited'] and 'existing-product' in cursor['seen_products']
    assert initial_cursor == original
    assert result.complete and cursor is None and pages == 7
    assert {o.url for o in offers} == {BASE + '/leaf-' + language for language in ('de', 'en', 'jp')}


def test_new_navigation_remains_scoped_to_main_content(settings):
    tile = '<div class="opc-Button"><a href="/outside">ZUM SET</a></div>'
    slider = '<div class="category-slider-wrapper"><a class="stretched-link" href="/outside">Deutsche Sets</a></div>'
    page = tile + slider + '<div id="content"><header>' + tile + slider + '</header>' + LANGUAGES + '<footer>' + tile + slider + '</footer></div>'
    assert {x['path'] for x in adapter(settings).page_links(page, BASE + '/all-sets', 'Pokemon')} == {
        BASE + '/sets-' + language for language in ('de', 'en', 'jp')}


def test_language_card_cannot_escape_configured_origin(settings):
    with pytest.raises(SourceError, match='outside configured'):
        adapter(settings).page_links(LANGUAGES.replace('href="/sets-de"', 'href="https://other.example/sets-de"'), BASE + '/all-sets', 'Pokemon')


def test_contact_only_overview_still_fails_closed(settings):
    page = '<div id="content"><div id="result-wrapper"></div><div class="opc-Button"><a href="/contact">Schreib uns!</a></div></div>'
    result = adapter(settings, {'/sets': page}).discover_batch()
    assert result.source_error and not result.complete
