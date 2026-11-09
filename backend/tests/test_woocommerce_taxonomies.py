"""TCG taxonomy union retains uncategorized cards and resumes without duplicates."""
from dataclasses import replace

import httpx
import pytest

from app.adapters.base import ShopClient, SourceOffer
from app.adapters.woocommerce import WooCommerceAdapter
from app.domain import classify

BASE='https://fixture.example'


def product(id, **extra):
    return {'id':id,'name':'Pokemon Display Deutsch','type':'simple','permalink':BASE+'/display-'+str(id),
            'prices':{'price':'9900','currency_minor_unit':2,'currency_code':'EUR'},
            'is_in_stock':True,'is_purchasable':True,**extra}


def adapter(settings,config,handler):
    def route(r):return httpx.Response(404) if r.url.path=='/robots.txt' else handler(r)
    return WooCommerceAdapter(ShopClient(BASE,settings,httpx.MockTransport(route)),{'full_catalog':True,**config})


def test_taxonomy_union_paginates_both_streams_and_deduplicates(settings):
    calls=[]
    def handler(r):
        key='category' if 'category' in r.url.params else 'tag'
        assert not ('category' in r.url.params and 'tag' in r.url.params)
        assert r.url.params[key] == ('10,11' if key=='category' else '20')
        assert r.url.params[key+'_operator']=='in'
        page=int(r.url.params['page']);calls.append((key,page))
        id=page if key=='category' else page+1
        return httpx.Response(200,headers={'X-WP-TotalPages':'2'},json=[product(id)])
    cursor=None;found=[];scanned=0
    for _ in range(4):
        a=adapter(settings,{'page_size':1,'category_ids':[10,11],'tag_ids':[20]},handler)
        try:result=a.discover_batch(cursor)
        finally:a.client.close()
        found.extend(o.external_id for o in result.offers);scanned+=result.scanned_count
        cursor=result.next_cursor
    assert result.complete and cursor is None
    assert calls==[('category',1),('category',2),('tag',1),('tag',2)]
    assert found==['1','2','3'] and scanned==3


def test_duplicate_stream_does_not_trigger_pagination_loop_error(settings):
    a=adapter(settings,{'category_ids':[10],'tag_ids':[20]},lambda r:httpx.Response(200,headers={'X-WP-TotalPages':'1'},json=[product(1)]))
    try:
        first=a.discover_batch();second=a.discover_batch(first.next_cursor)
    finally:a.client.close()
    assert second.complete and not second.source_error and second.offers==[] and second.scanned_count==0


@pytest.mark.parametrize('value', [[],[0],[-1],['10'],[True],'10',None])
def test_invalid_taxonomy_config_makes_no_request(settings,value):
    def handler(r):raise AssertionError('Invalid configuration requested source')
    a=adapter(settings,{'category_ids':value},handler)
    try:result=a.discover_batch()
    finally:a.client.close()
    assert result.source_error.startswith('Invalid WooCommerce category_ids') and not result.complete


def test_variant_resume_keeps_taxonomy_and_seen_parent(settings):
    parent=product(1,type='variable',variations=[{'id':n} for n in range(100,130)])
    calls=[]
    def handler(r):
        if r.url.path.endswith('/products'):
            calls.append(dict(r.url.params))
            return httpx.Response(200,headers={'X-WP-TotalPages':'1'},json=[parent])
        id=int(r.url.path.rsplit('/',1)[1])
        return httpx.Response(200,json=product(id))
    config={'category_ids':[10],'tag_ids':[20]}
    cursor=None;found=[]
    for _ in range(3):
        a=adapter(settings,config,handler)
        try:result=a.discover_batch(cursor)
        finally:a.client.close()
        found.extend(o.external_id for o in result.offers);cursor=result.next_cursor
        if result.complete:break
    assert result.complete and len(found)==len(set(found))==30
    assert len(calls)==2 and calls[0]['category']=='10' and calls[1]['tag']=='20'


@pytest.mark.parametrize('labels,expected',[('Panini Manga',None),('Buch Manga',None),('TCG Manga','pokemon')])
def test_manga_pack_is_not_a_card_booster(settings,labels,expected):
    a=adapter(settings,{},lambda r:httpx.Response(404))
    try:item=a.parse_product(product(1,name='Pokemon Manga Pack 19',tags=[{'name':labels}]))
    finally:a.client.close()
    identity=classify(item,'fixture')
    assert (identity.game if identity else None)==expected
