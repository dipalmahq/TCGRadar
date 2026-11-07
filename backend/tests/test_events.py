from dataclasses import replace
from sqlalchemy import func, select

from app.events import ingest
from app.models import Merchant, Notification, OfferEvent, SearchRule
from app.notifications import enqueue_event
from test_domain import source


def test_new_unchanged_restock_and_price_changes(factory):
    with factory() as db:
        merchant = db.scalar(select(Merchant))
        item = source()
        offer, events = ingest(db, merchant, replace(item, availability="out_of_stock"))
        assert [e.kind for e in events] == ["new"]
        assert ingest(db, merchant, replace(item, availability="out_of_stock"))[1] == []
        _, events = ingest(db, merchant, item)
        assert [e.kind for e in events] == ["restock"]
        assert ingest(db, merchant, item)[1] == []
        _, events = ingest(db, merchant, replace(item, price_minor=12000))
        assert events[0].kind == "price_drop"
        assert events[0].previous["price_minor"] == 12999
        assert ingest(db, merchant, replace(item, price_minor=13000))[1][0].kind == "price_increase"
        assert db.scalar(select(func.count(OfferEvent.id))) == 4


def test_unknown_does_not_invent_restock_and_preserves_known_state(factory):
    with factory() as db:
        merchant = db.scalar(select(Merchant))
        item = source()
        offer, _ = ingest(db, merchant, item)
        ingest(db, merchant, replace(item, availability="unknown"))
        assert offer.last_known_availability == "in_stock"
        assert ingest(db, merchant, item)[1] == []
        ingest(db, merchant, replace(item, availability="out_of_stock"))
        ingest(db, merchant, replace(item, availability="unknown"))
        assert ingest(db, merchant, item)[1][0].kind == "restock"


def test_price_limits_and_overlapping_rules_are_deduplicated(factory):
    with factory() as db:
        merchant = db.scalar(select(Merchant))
        for name in ("Rule A", "Rule B"):
            db.add(SearchRule(name=name, query="OP-17", max_price_minor=12500, channels=["discord", "telegram"]))
        db.flush()
        item = source("One Piece OP17 Display 24 Booster ENG")
        offer, events = ingest(db, merchant, item)
        assert enqueue_event(db, events[0]) == []
        _, events = ingest(db, merchant, replace(item, price_minor=12000))
        assert len(enqueue_event(db, events[0])) == 2
        assert enqueue_event(db, events[0]) == []
        db.commit()
        event_id = events[0].id
    with factory() as db:
        assert enqueue_event(db, db.get(OfferEvent, event_id)) == []
        assert db.scalar(select(func.count(Notification.id))) == 2


def test_preorders_are_opt_in(factory):
    with factory() as db:
        merchant = db.scalar(select(Merchant))
        rule = SearchRule(name="Only available", channels=["discord"], include_preorders=False)
        db.add(rule)
        db.flush()
        _, events = ingest(db, merchant, replace(source(), availability="preorder"))
        assert enqueue_event(db, events[0]) == []
        rule.include_preorders = True
        assert len(enqueue_event(db, events[0])) == 1


def test_simultaneous_restock_and_drop_produces_one_message(factory):
    with factory() as db:
        merchant = db.scalar(select(Merchant))
        db.add(SearchRule(name="Everything", channels=["discord"]))
        db.flush()
        ingest(db, merchant, replace(source(), availability="out_of_stock"))
        _, events = ingest(db, merchant, replace(source(), price_minor=10000))
        assert len(events) == 1
        assert set(events[0].current["changes"]) == {"restock", "price_drop"}
        assert len(enqueue_event(db, events[0])) == 1
