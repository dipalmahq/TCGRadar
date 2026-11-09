from datetime import timedelta
from contextlib import nullcontext
from threading import Barrier, local
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.adapters.base import ShopClient, SourceOffer
from app.config import Settings
from app.db import utcnow
from app.events import ingest
from app.main import create_app
from app.models import Expansion, Game, Merchant, Notification, Offer, Product, SearchRule, WatchTarget
from app.notifications import deliver_pending, enqueue_event
from app.scanner import aware, scan_shop
import app.worker as worker

BASE = 'https://fixture.example'


def offer(id='1', status='out_of_stock'):
    return SourceOffer(id, 'One Piece OP77 Display 24 Packs English', BASE + '/products/test?variant=' + id, 10000, 'EUR', status)


def prepare(factory, direct=True):
    with factory() as db:
        m = db.scalar(select(Merchant))
        m.config = {'full_catalog': True}
        m.next_check_at = utcnow() + timedelta(hours=1)
        m.crawl_state = {'cursor': {'page': 19}, 'pages': 18, 'scanned': 4500,
                         'refresh': {'next_at': (utcnow()+timedelta(hours=1)).isoformat()}}
        item, _ = ingest(db, m, offer())
        item.last_seen_at = utcnow() - timedelta(minutes=10)
        if direct:
            db.add(WatchTarget(merchant_id=m.id, url=item.url, channels=[]))
        db.commit()
        return m.id, item.id


def transport(calls, response=None):
    def handler(r):
        calls.append(r.url.path)
        if r.url.path == '/robots.txt': return httpx.Response(404)
        assert r.url.path == '/products/test.js'
        return response or httpx.Response(200, json={'title': 'One Piece OP77 Display 24 Packs English', 'handle': 'test',
            'variants': [{'id': 1, 'price': 10000, 'available': True}]})
    return httpx.MockTransport(handler)


def test_watch_deadline_bypasses_catalog_and_normal_refresh_schedule(factory, settings):
    id, oid = prepare(factory)
    calls = []
    result = scan_shop(factory, id, settings, transport(calls), refresh_only=True, watch_only=True)
    assert result['refreshed'] == 1 and result['job'] == 'watch'
    with factory() as db:
        m = db.get(Merchant, id);w = db.scalar(select(WatchTarget))
        assert m.crawl_state['cursor'] == {'page': 19} and m.crawl_state['pages'] == 18
        assert w.last_checked_at and w.last_attempt_at
        assert aware(w.next_check_at) >= utcnow()+timedelta(seconds=290)
        assert m.next_check_at.replace(tzinfo=utcnow().tzinfo) > utcnow()+timedelta(minutes=30)
    assert calls == ['/robots.txt', '/products/test.js']
    assert scan_shop(factory, id, settings, transport(calls), refresh_only=True, watch_only=True) == {'skipped': True}


def test_search_rule_checks_sold_out_and_over_budget_products(factory, settings):
    id, oid = prepare(factory, direct=False)
    with factory() as db:
        db.add(SearchRule(name='Waiting for price drop', query='OP77', max_price_minor=5000, include_preorders=True, channels=[]))
        db.commit()
    calls = []
    assert scan_shop(factory,id,settings,transport(calls),refresh_only=True,watch_only=True)['refreshed']==1
    with factory() as db:
        assert db.get(Offer,oid).availability=='in_stock'
        assert aware(db.get(Offer,oid).next_stock_check_at)<utcnow()+timedelta(minutes=6)


def test_shopify_watch_variants_share_one_product_request(factory, settings):
    id, oid = prepare(factory)
    with factory() as db:
        db.add(WatchTarget(merchant_id=id,url=BASE+'/products/test?variant=2',channels=[]))
        db.add(WatchTarget(merchant_id=id,url=BASE+'/products/test?variant=999',channels=[]))
        db.commit()
    calls=[]
    response=httpx.Response(200,json={'title':'One Piece OP77 Display 24 Packs English','handle':'test',
        'variants':[{'id':1,'price':10000,'available':True},{'id':2,'price':11000,'available':False}]})
    assert scan_shop(factory,id,settings,transport(calls,response),refresh_only=True,watch_only=True)['refreshed']==1
    with factory() as db:
        watches=list(db.scalars(select(WatchTarget).order_by(WatchTarget.id)))
        assert all(w.last_checked_at for w in watches[:2])
        assert watches[2].last_checked_at is None and watches[2].last_error
    assert calls==['/robots.txt','/products/test.js']


def test_removed_product_does_not_advance_last_successful_observation(factory, settings):
    id, oid=prepare(factory)
    with factory() as db:previous=db.get(Offer,oid).last_seen_at
    calls=[]
    scan_shop(factory,id,settings,transport(calls,httpx.Response(404)),refresh_only=True,watch_only=True)
    with factory() as db:
        o=db.get(Offer,oid);w=db.scalar(select(WatchTarget))
        assert o.last_seen_at==previous and o.availability=='unknown' and o.source_error
        assert o.stock_attempted_at and aware(o.next_stock_check_at)>utcnow()
        assert w.last_checked_at is None and w.last_attempt_at and w.last_error


def test_watch_retry_after_blocks_other_merchant_jobs(factory, settings):
    id,oid=prepare(factory)
    calls=[]
    result=scan_shop(factory,id,settings,transport(calls,httpx.Response(429,headers={'Retry-After':'1200'})),refresh_only=True,watch_only=True)
    assert result['error']
    assert scan_shop(factory,id,settings,transport(calls),refresh_only=True,watch_only=True)=={'skipped':True}
    with factory() as db:
        assert aware(db.get(Merchant,id).next_check_at)>=utcnow()+timedelta(seconds=1190)
    assert calls==['/robots.txt','/products/test.js']


def test_old_normal_offer_is_not_starved_by_newer_preorders(factory, settings):
    id,oid=prepare(factory,direct=False)
    with factory() as db:
        m=db.get(Merchant,id);m.crawl_state={'cursor':{'page':19}}
        first=db.get(Offer,oid);first.next_stock_check_at=utcnow()-timedelta(hours=2)
        second,_=ingest(db,m,offer('2','preorder'));second.url=BASE+'/products/later?variant=2'
        second.next_stock_check_at=utcnow()-timedelta(minutes=1)
        db.commit()
    calls=[]
    scan_shop(factory,id,settings.model_copy(update={'refresh_batch_size':1}),transport(calls),refresh_only=True)
    assert calls==['/robots.txt','/products/test.js']


@pytest.mark.parametrize('age,expected,stale',[(23,'in_stock',False),(25,'unknown',True)])
def test_24_hour_expiry_keeps_age_visible_and_stock_count_consistent(factory,settings,age,expected,stale):
    id,oid=prepare(factory,direct=False)
    with factory() as db:
        o=db.get(Offer,oid);o.availability='in_stock';o.last_seen_at=utcnow()-timedelta(hours=age);db.commit()
    config=settings.model_copy(update={'stale_after_minutes':1440})
    with TestClient(create_app(config,factory)) as api:
        headers={'X-Radar-Key':settings.api_key}
        item=api.get('/api/offers',headers=headers).json()['items'][0]
        assert item['availability']==expected and item['stale'] is stale and not item['fresh']
        assert item['observed_availability']=='in_stock'
        assert api.get('/api/overview',headers=headers).json()['in_stock']==(0 if stale else 1)
        assert api.get('/api/offers?availability=in_stock',headers=headers).json()['total']==(0 if stale else 1)
    assert Settings(_env_file=None,environment='development').stale_after_minutes==1440


@pytest.mark.parametrize('excluded,error', [(True,None),(False,'Source unavailable')])
def test_stock_overview_ignores_excluded_or_failed_sources(factory,settings,excluded,error):
    id,oid=prepare(factory,direct=False)
    with factory() as db:
        item=db.get(Offer,oid);item.availability='in_stock';item.excluded=excluded;item.source_error=error;db.commit()
    with TestClient(create_app(settings,factory)) as api:
        result=api.get('/api/overview',headers={'X-Radar-Key':settings.api_key}).json()
        assert result['in_stock']==0


def test_new_watch_requests_own_schedule_without_resetting_catalog(factory,settings):
    id,oid=prepare(factory,direct=False)
    with factory() as db:previous=db.get(Merchant,id).next_check_at
    with TestClient(create_app(settings,factory)) as api:
        response=api.post('/api/watches',headers={'X-Radar-Key':settings.api_key},json={'url':BASE+'/products/test?variant=1'})
        assert response.status_code==201 and response.json()['next_check_at']
    with factory() as db:
        m=db.get(Merchant,id)
        assert m.watch_requested_at and m.next_check_at==previous and m.crawl_state['cursor']=={'page':19}


def test_one_merchant_turn_never_waits_for_or_dispatches_other_shop(factory,settings,monkeypatch):
    id,oid=prepare(factory)
    with factory() as db:
        db.add(Merchant(slug='other',name='Other',base_url='https://other.example',country='DE',adapter='shopify',config={}))
        db.commit()
    calls=[]
    monkeypatch.setattr(worker,'scan_shop',lambda factory,shop,settings,**kw:calls.append((shop,kw)) or {'ok':True})
    monkeypatch.setattr(worker,'deliver_pending',lambda *a:pytest.fail('Merchant worker must not deliver messages'))
    worker.run_merchant_once(id,factory,settings)
    assert len(calls)==1 and calls[0][0]==id and calls[0][1]['watch_only']
    with factory() as db:
        assert db.get(Merchant,id).worker_heartbeat_at
        assert db.scalar(select(Merchant).where(Merchant.slug=='other')).worker_heartbeat_at is None


def test_catalog_and_refresh_alternate_when_both_are_due(factory,settings,monkeypatch):
    id,oid=prepare(factory,direct=False);calls=[]
    with factory() as db:
        m=db.get(Merchant,id);m.next_check_at=utcnow()-timedelta(seconds=1)
        m.crawl_state={'cursor':{'page':19},'watch':{'next_at':(utcnow()+timedelta(hours=1)).isoformat()}}
        db.commit()
    monkeypatch.setattr(worker,'scan_shop',lambda factory,shop,settings,**kw:calls.append(kw) or {'ok':True})
    worker.run_merchant_once(id,factory,settings)
    with factory() as db:
        m=db.get(Merchant,id);m.crawl_state={**m.crawl_state,'last_job':'refresh'};db.commit()
    worker.run_merchant_once(id,factory,settings)
    assert calls[0]['refresh_only'] and calls[1]['include_watches'] is False


def test_saved_source_cooldown_defers_a_new_client(settings,monkeypatch):
    import app.adapters.base as base
    sleeps=[];monkeypatch.setattr(base.time,'sleep',lambda seconds:sleeps.append(seconds))
    c=ShopClient(BASE,settings.model_copy(update={'request_delay_seconds':2}),httpx.MockTransport(lambda r:httpx.Response(200)))
    c.defer_until(utcnow()+timedelta(seconds=10));c._request(BASE+'/product')
    assert sleeps and sleeps[0]>=9
    c.close()


def test_notification_role_sends_without_scanning_any_shop(factory,settings,monkeypatch):
    calls=[]
    with factory() as db:db.add(Notification(channel='discord',payload={'title':'Test','text':'Test'}));db.commit()
    delivery=worker.deliver_pending
    monkeypatch.setattr(worker,'SessionLocal',factory);monkeypatch.setattr(worker,'get_settings',lambda:settings)
    monkeypatch.setattr(worker,'run_merchant_once',lambda *a,**k:pytest.fail('Notifier must never crawl'))
    monkeypatch.setattr(worker,'deliver_pending',lambda f,s:delivery(f,s,httpx.MockTransport(lambda r:calls.append(r) or httpx.Response(200,json={'id':'test'}))))
    monkeypatch.setattr(sys,'argv',['worker','--notifications-only','--once']);worker.stop.clear();worker.main()
    assert len(calls)==1
    with factory() as db:assert db.scalar(select(Notification)).status=='sent'


def test_product_alarm_is_muted_when_stock_is_no_longer_fresh(factory,settings):
    id,oid=prepare(factory,direct=False)
    with factory() as db:
        db.add(SearchRule(name='Restocks',channels=['discord']))
        _,events=ingest(db,db.get(Merchant,id),offer(status='in_stock'))
        for ev in events:enqueue_event(db,ev)
        db.get(Offer,oid).last_seen_at=utcnow()-timedelta(minutes=6);db.commit()
    calls=[]
    deliver_pending(factory,settings,httpx.MockTransport(lambda r:calls.append(r) or httpx.Response(200)))
    assert calls==[]
    with factory() as db:assert db.scalar(select(Notification)).status=='muted'


def test_generated_workers_are_one_per_slug_and_pool_is_bounded():
    path=Path('scripts/generate_merchant_workers.py')
    if not path.exists():path=Path(__file__).resolve().parents[2]/'scripts/generate_merchant_workers.py'
    if not path.exists():pytest.skip('Generator source is host-side; checked locally')
    spec=importlib.util.spec_from_file_location('worker_generator',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rendered=module.render([{'slug':'alpha'},{'slug':'beta'}])
    assert rendered.count('--merchant')==2 and rendered.count('--notifications-only')==1
    assert rendered.count('RADAR_DATABASE_MAX_OVERFLOW: "0"')==3
    with pytest.raises(ValueError):module.render([{'slug':'alpha'},{'slug':'alpha'}])


@pytest.mark.parametrize('table',['expansions','products'])
def test_postgres_concurrent_merchants_share_product_identity(factory,settings,table):
    with factory() as db:
        engine=db.get_bind()
        if engine.dialect.name!='postgresql':pytest.skip('Requires real PostgreSQL concurrency')
        first=db.scalar(select(Merchant));second=Merchant(slug='second',name='Second',base_url='https://two.example',country='DE',adapter='shopify',config={})
        db.add(second);db.flush();ids=[first.id,second.id]
        if table=='products':
            game=db.scalar(select(Game).where(Game.slug=='one-piece'));db.add(Expansion(game_id=game.id,code='OP-77',name='OP-77'))
        db.commit()
    barrier=Barrier(2);seen=local()
    def after(conn,cursor,statement,parameters,context,executemany):
        if ('FROM '+table) in statement and statement.lstrip().startswith('SELECT') and not getattr(seen,'waited',False):
            seen.waited=True;barrier.wait(timeout=10)
    def insert(id):
        with factory() as db:ingest(db,db.get(Merchant,id),offer());db.commit()
    event.listen(engine,'after_cursor_execute',after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(insert,ids))
    finally:event.remove(engine,'after_cursor_execute',after)
    with factory() as db:
        assert db.scalar(select(func.count(Product.id)))==1
        assert db.scalar(select(func.count(Offer.id)))==2


def test_postgres_single_notification_owner(factory):
    with factory() as db:
        if db.get_bind().dialect.name!='postgresql':pytest.skip('Requires PostgreSQL advisory locks')
    with worker.notification_owner(factory) as first:
        assert first
        with worker.notification_owner(factory) as second:assert not second
    with worker.notification_owner(factory) as third:assert third
