"""Regular merchant catalogs: newest-first traversal and public purchase evidence."""
import httpx
import pytest

from app.adapters.base import ShopClient
from app.adapters.woocommerce import WooCommerceAdapter
from app.domain import classify

BASE = 'https://fixture.example'


def product(id, purchasable=True, in_stock=True):
    return {'id': id, 'name': 'OP18 The Dominance of God Display EN', 'type': 'simple',
            'permalink': BASE + '/produkt/display-' + str(id),
            'is_purchasable': purchasable, 'is_in_stock': in_stock,
            'categories': [{'name': 'TCG Produkte'}, {'name': 'One Piece Card Game'}],
            'prices': {'price': '19999', 'currency_minor_unit': 2, 'currency_code': 'EUR'}}


@pytest.mark.parametrize('order', ['asc', 'desc'])
def test_full_catalog_keeps_configured_order_across_resumed_pages(settings, order):
    calls = []
    def handler(r):
        if r.url.path == '/robots.txt':
            return httpx.Response(404)
        page = int(r.url.params['page'])
        calls.append((page, r.url.params['orderby'], r.url.params['order']))
        return httpx.Response(200, headers={'X-WP-TotalPages': '2'}, json=[product(page)])
    config = {'full_catalog': True, 'page_size': 1, 'catalog_order': order}
    first = WooCommerceAdapter(ShopClient(BASE, settings, httpx.MockTransport(handler)), config).discover_batch()
    second = WooCommerceAdapter(ShopClient(BASE, settings, httpx.MockTransport(handler)), config).discover_batch(first.next_cursor)
    assert calls == [(1, 'id', order), (2, 'id', order)]
    assert not first.complete and second.complete
    assert [o.external_id for o in first.offers + second.offers] == ['1', '2']


def test_invalid_catalog_order_fails_before_network_request(settings):
    def handler(r):
        raise AssertionError('Invalid configuration must not make a request')
    a = WooCommerceAdapter(ShopClient(BASE, settings, httpx.MockTransport(handler)),
                           {'full_catalog': True, 'catalog_order': 'unexpected'})
    result = a.discover_batch()
    assert result.source_error == 'Invalid WooCommerce catalog order' and not result.complete
    assert result.next_cursor == {'page': 1}


@pytest.mark.parametrize('purchasable,in_stock,availability', [(True, True, 'in_stock'), (False, True, 'unknown'), (True, False, 'out_of_stock')])
def test_woocommerce_category_identity_and_public_purchase_status(settings, purchasable, in_stock, availability):
    a = WooCommerceAdapter(ShopClient(BASE, settings, httpx.MockTransport(lambda r: httpx.Response(404))), {})
    offer = a.parse_product(product(1, purchasable, in_stock))
    identity = classify(offer, 'fixture')
    assert identity.game == 'one-piece' and identity.product_type == 'display' and identity.language == 'en'
    assert offer.availability == availability
