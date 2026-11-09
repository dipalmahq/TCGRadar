"""Set-independent preorder, discovery fairness and known-product refresh."""
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.adapters.availability import preorder_evidence
from app.adapters.base import ShopClient, SourceOffer
from app.adapters.shopify import ShopifyAdapter
from app.adapters.structured_html import StructuredHtmlAdapter
from app.config import Settings
from app.db import utcnow
from app.domain import classify
from app.events import ingest
from app.main import create_app
from app.models import Game, Merchant, Offer, SearchRule, WatchTarget
from app.scanner import aware, scan_shop

BASE = 'https://fixture.example'


def client(settings, handler):
    return ShopClient(BASE, settings, httpx.MockTransport(lambda r: httpx.Response(404) if r.url.path == '/robots.txt' else handler(r)))


@pytest.mark.parametrize('title,description,expected', [
    ('Pokemon Display Vorverkauf', '', True),
    ('One Piece Display Presale', '', True),
    ('Pokemon Display', 'This item is a pre-order item.', True),
    ('Pokemon Display', 'Dieses Produkt ist eine Vorbestellung.', True),
    ('Pokemon Display', 'Release: 27.11.2030', True),
    ('Pokemon Display', 'Release: 27.11.2020', False),
    ('Pokemon Display', 'Release: 99.99.2030', False),
    ('Pokemon Display', 'Orders containing pre-order items ship together.', False),
    ('Pokemon Display', 'Dieser Artikel ist nicht vorbestellbar.', False),
])
def test_general_preorder_evidence(title, description, expected):
    assert preorder_evidence(title, description, datetime(2026, 11, 7, tzinfo=timezone.utc)) is expected


@pytest.mark.parametrize('available,expected', [(True, 'preorder'), (False, 'out_of_stock'), (None, 'unknown')])
def test_release_announcement_never_overrides_shopify_purchase_status(settings, available, expected):
    a = ShopifyAdapter(client(settings, lambda r: httpx.Response(404)), {})
    item = {'title': 'Pokemon Display Englisch', 'handle': 'test', 'body_html': 'Release: 27.11.2030',
            'variants': [{'id': 1, 'price': '99.99', 'available': available}]}
    assert a.parse_product(item)[0].availability == expected


@pytest.mark.parametrize('name,kind,count', [('Dragon Ball Super Box B33 ENG (20 packs)', 'display', 20),
    ('Pokemon Gift Box 20 Packs English', 'collection', 20), ('One Piece Booster Box OP18 24 Packs English', 'display', 24)])
def test_packaging_with_explicit_box_and_pack_count(name, kind, count):
    item = SourceOffer('1', name, BASE + '/test', 10000, 'EUR', 'out_of_stock')
    identity = classify(item, 'fixture')
    assert (identity.product_type, identity.booster_count) == (kind, count)


@pytest.mark.parametrize('button,notify,expected', [(True, False, 'preorder'), ('implicit', False, 'preorder'), (False, True, 'out_of_stock'), (False, False, 'unknown')])
def test_shopware_buy_box_overrides_misleading_schema_preorder(settings, button, notify, expected):
    page = '<div itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">Pokemon Display English</h1>'
    page += '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><meta itemprop="price" content="99.99"><link itemprop="availability" href="https://schema.org/PreOrder"></div></div>'
    page += '<div class="product-detail-buy">'
    if button:
        attr = '' if button == 'implicit' else 'type="submit"'
        page += '<form data-add-to-cart><button ' + attr + '>Jetzt vorbestellen</button></form>'
    if notify:
        page += '<form data-stock-notification-form>Benachrichtigen</form>'
    page += '</div><aside><form data-add-to-cart><button type="submit">In den Warenkorb</button></form></aside>'
    offer, = StructuredHtmlAdapter(client(settings, lambda r: httpx.Response(404)), {}).parse(page, BASE + '/test', True)
    assert offer.availability == expected


def test_shopware_discovery_and_pagination(settings):
    page = '<div class="product-box"><a class="product-name" href="/test">Pokemon Display English</a></div>'
    page += '<ul class="pagination"><input name="p" value="1"><input name="p" value="2"><input name="p" value="3"></ul>'
    a = StructuredHtmlAdapter(client(settings, lambda r: httpx.Response(404)), {'pagination': 'shopware'})
    assert a.candidate_links(page, BASE + '/category')[0].url == BASE + '/test'
    assert a.page_links(page, BASE + '/category?p=2', 'Pokemon')[0]['path'] == BASE + '/category?p=3'
    assert a.page_links(page, BASE + '/category?p=3', 'Pokemon') == []
    anchors = '<ul class="pagination"><a data-page="1" href="?p=1">1</a><a data-page="2" href="?p=2">2</a><a aria-disabled="true" data-page="99" href="?p=99">Last</a></ul>'
    assert a.page_links(anchors, BASE + '/category', 'Pokemon')[0]['path'] == BASE + '/category?p=2'
    assert a.page_links(anchors, BASE + '/category?p=2', 'Pokemon') == []


def test_zero_price_shopify_placeholder_is_not_a_free_offer(settings):
    a = ShopifyAdapter(client(settings, lambda r: httpx.Response(404)), {})
    offer, = a.parse_product({'title': 'Pokemon Display English', 'handle': 'placeholder',
                             'variants': [{'id': 1, 'price': '0.00', 'available': False}]})
    assert offer.price_minor is None and offer.availability == 'out_of_stock'


def test_games_rotate_before_next_page_and_loop_guard_survives_rotation(settings):
    calls = []
    def handler(r):
        calls.append(r.url.path)
        game = 'Pokemon' if 'pokemon' in r.url.path else 'One Piece'
        title = game + ' Booster English'
        product = {'@type': 'Product', 'name': title, 'url': BASE + '/item-' + game.replace(' ', ''),
                   'offers': {'@type': 'Offer', 'price': '4.99'}}
        if r.url.path.startswith('/item'):
            return httpx.Response(200, text='<script type="application/ld+json">' + json.dumps(product) + '</script>')
        nav = '<link rel="next" href="/pokemon-2">' if r.url.path == '/pokemon' else ''
        return httpx.Response(200, text=nav + '<script type="application/ld+json">' + json.dumps(product) + '</script>')
    config = {'full_catalog': True, 'categories': [{'path': '/pokemon', 'game': 'Pokemon'}, {'path': '/one-piece', 'game': 'One Piece'}]}
    a = StructuredHtmlAdapter(client(settings, handler), config)
    first = a.discover_batch()
    second = a.discover_batch(first.next_cursor)
    assert '/one-piece' in calls and '/pokemon-2' not in calls
    third = a.discover_batch(second.next_cursor)
    assert 'repeated' in third.source_error and not third.complete


def populate(factory):
    with factory() as db:
        m = db.scalar(select(Merchant))
        m.config = {'full_catalog': True}
        m.next_check_at = utcnow() + timedelta(hours=1)
        m.crawl_state = {'cursor': {'page': 8}, 'pages': 7, 'scanned': 1750}
        offer, _ = ingest(db, m, SourceOffer('1', 'One Piece OP18 Display 24 Packs English', BASE + '/products/test?variant=1', 10000, 'EUR', 'out_of_stock'))
        offer.last_seen_at = utcnow() - timedelta(hours=1)
        db.add(WatchTarget(merchant_id=m.id, url=offer.url, include_preorders=True, channels=[]))
        db.commit()
        return m.id


def detail_handler(calls, limited=False):
    def handler(r):
        calls.append(r.url.path)
        if r.url.path == '/robots.txt':
            return httpx.Response(404)
        assert r.url.path == '/products/test.js'
        if limited:
            return httpx.Response(429, headers={'Retry-After': '1800'})
        return httpx.Response(200, json={'title': 'One Piece OP18 Display 24 Packs English Preorder', 'handle': 'test',
            'variants': [{'id': 1, 'price': 9999, 'available': True}]})
    return httpx.MockTransport(handler)


def test_refresh_known_product_and_watch_without_resetting_catalog(factory, settings):
    id = populate(factory)
    calls = []
    result = scan_shop(factory, id, settings, detail_handler(calls), refresh_only=True)
    assert result['refreshed'] == 1 and result['events'] == 1
    with factory() as db:
        m = db.get(Merchant, id)
        assert m.crawl_state['cursor'] == {'page': 8} and m.crawl_state['scanned'] == 1750
        assert aware(m.next_check_at) > utcnow() + timedelta(minutes=30)
        assert db.scalar(select(Offer)).availability == 'preorder'
        assert db.scalar(select(WatchTarget)).last_error is None
    assert scan_shop(factory, id, settings, detail_handler(calls), refresh_only=True) == {'skipped': True}
    assert calls == ['/robots.txt', '/products/test.js']


def test_refresh_cannot_bypass_source_retry_deadline(factory, settings):
    id = populate(factory)
    calls = []
    result = scan_shop(factory, id, settings, detail_handler(calls, limited=True), refresh_only=True)
    assert result['error']
    with factory() as db:
        m = db.get(Merchant, id)
        assert aware(m.next_check_at) >= utcnow() + timedelta(seconds=1790)
        assert db.scalar(select(Offer)).availability == 'unknown'
        assert m.crawl_state['cursor'] == {'page': 8}
    assert scan_shop(factory, id, settings, detail_handler(calls), refresh_only=True) == {'skipped': True}
    assert calls == ['/robots.txt', '/products/test.js']


def test_saved_search_shows_matching_unavailable_offers_with_its_filters(factory, settings):
    id = populate(factory)
    with factory() as db:
        game = db.scalar(select(Game).where(Game.slug == 'one-piece'))
        rule = SearchRule(name='Set wish list', game_ids=[game.id], set_codes=['OP-18'], languages=['en'], product_types=['display'],
                          max_price_minor=11000, include_preorders=True, channels=[])
        db.add(rule); db.commit(); rule_id = rule.id
    with TestClient(create_app(settings, factory)) as api:
        headers = {'X-Radar-Key': settings.api_key}
        assert api.get('/api/offers', params={'rule_id': rule_id}, headers=headers).json()['total'] == 1
        assert api.get('/api/offers', params={'rule_id': 99999}, headers=headers).status_code == 404


def test_worker_parallelizes_shops_but_refresh_precedes_own_catalog(factory, settings, monkeypatch):
    import app.worker as worker
    with factory() as db:
        db.add(Merchant(slug='second', name='Second', base_url='https://second.example', country='DE', adapter='shopify', config={}))
        db.commit()
    barrier, lock, calls = Barrier(2), Lock(), []
    def scan(factory, id, settings, refresh_only=False):
        with lock: calls.append((id, refresh_only))
        if refresh_only: barrier.wait(timeout=5)
        return {'shop_id': id}
    monkeypatch.setattr(worker, 'scan_shop', scan)
    monkeypatch.setattr(worker, 'deliver_pending', lambda *args: None)
    worker.stop.clear()
    results = worker.run_once(factory, settings.model_copy(update={'worker_concurrency': 2}))
    assert len(results) == 4
    for id in {id for id, _ in calls}:
        assert [refresh for shop, refresh in calls if shop == id] == [True, False]
