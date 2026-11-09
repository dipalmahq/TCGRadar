"""Real migration keeps observations/cursors and backfills only schedules."""
from datetime import timedelta
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from app.db import utcnow
from app.scanner import aware


def test_worker_migration_preserves_stock_and_catalog_progress(factory,tmp_path):
    with factory() as db:engine=db.get_bind()
    postgres=engine.dialect.name=='postgresql'
    if not postgres:engine=sa.create_engine('sqlite:///'+str(tmp_path/'migration.db'))
    schema='migration_'+uuid.uuid4().hex
    path=Path('backend/alembic.ini')
    cfg=Config(str(path.resolve()))
    past=(utcnow()-timedelta(hours=2)).replace(microsecond=0)
    with engine.connect() as conn, conn.begin():
        if postgres:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
        cfg.attributes['connection']=conn
        command.upgrade(cfg,'81a4f3c26b90')
        metadata=sa.MetaData()
        tables={name:sa.Table(name,metadata,autoload_with=conn) for name in ('games','merchants','products','offers','watch_targets')}
        def values(table,overrides=None):
            result={}
            for col in table.columns:
                if col.nullable:continue
                if isinstance(col.type,sa.Boolean):result[col.name]=False
                elif isinstance(col.type,sa.Integer):result[col.name]=1
                elif isinstance(col.type,sa.DateTime):result[col.name]=past
                elif isinstance(col.type,sa.JSON):result[col.name]={}
                elif isinstance(col.type,sa.Numeric):result[col.name]=1
                elif isinstance(col.type,sa.String):result[col.name]='fixture'[:col.type.length or 7]
                else:result[col.name]='fixture'
            return {**result,**(overrides or {})}
        for name in ('games','merchants','products','offers','watch_targets'):
            override={}
            if name=='merchants':override={'crawl_state':{'cursor':{'page':7},'pages':6},'enabled':True}
            if name=='offers':override={'availability':'in_stock','last_known_availability':'in_stock','excluded':False,'last_seen_at':past,'currency':'EUR'}
            conn.execute(tables[name].insert().values(**values(tables[name],override)))
        command.upgrade(cfg,'head')
        offer=conn.execute(sa.text('SELECT availability,last_seen_at,next_stock_check_at,stock_attempted_at FROM offers')).mappings().one()
        assert offer['availability']=='in_stock' and offer['stock_attempted_at'] is None
        # Reflect new timestamp columns to obtain typed values on both dialects.
        migrated=sa.Table('offers',sa.MetaData(),autoload_with=conn)
        row=conn.execute(sa.select(migrated)).mappings().one()
        assert aware(row['last_seen_at'])==past
        assert aware(row['next_stock_check_at'])==past+timedelta(minutes=30)
        merchant=sa.Table('merchants',sa.MetaData(),autoload_with=conn)
        assert conn.execute(sa.select(merchant.c.crawl_state)).scalar()=={'cursor':{'page':7},'pages':6}
        command.check(cfg)
        command.downgrade(cfg,'81a4f3c26b90')
        assert 'next_stock_check_at' not in {c['name'] for c in sa.inspect(conn).get_columns('offers')}
        assert conn.execute(sa.text('SELECT availability FROM offers')).scalar()=='in_stock'
        if postgres:conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    if not postgres:engine.dispose()
