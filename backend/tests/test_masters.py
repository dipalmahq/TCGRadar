from dataclasses import replace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.domain import classify, search_normalized
from app.events import ingest
from app.main import create_app
from app.models import Game, Merchant, SearchRule
from app.notifications import rule_matches
from test_domain import source


@pytest.mark.parametrize("code", ["B27", "BT27", "B-27", "DBS-B27", "BT-27"])
def test_masters_booster_code_aliases_and_pack_quantity(code):
    identity = classify(source(f"Dragon Ball Super {code} History of Z Booster ENG"), "fixture")
    assert (identity.game, identity.set_code, identity.product_type, identity.booster_count) == ("dragon-ball-masters", "B-27", "booster", 1)
    assert search_normalized(code).endswith("b27")


def test_masters_and_fusion_never_merge_or_inherit_mixed_categories():
    masters = source("Dragon Ball Super Masters B27 Display 24 Booster ENG", labels="Dragon Ball Fusion World & Masters")
    fusion = source("Dragon Ball Super Fusion World FB27 Display 24 Booster ENG", labels="Dragon Ball Fusion World & Masters")
    a, b = classify(masters, "one"), classify(fusion, "two")
    assert a.game == "dragon-ball-masters" and b.game == "dragon-ball-fusion-world"
    assert a.identity_key != b.identity_key
    assert a.identity_key == classify(replace(masters, title="Dragon Ball Super BT27 Display 24 Booster ENG"), "two").identity_key
    assert classify(source("Dragon Ball Super Masters Fusion World B27 FB27 Display ENG"), "one") is None
    assert classify(source("Dragon Ball Super Display ENG"), "one") is None


@pytest.mark.parametrize("title", ["Dragon Ball Super BT27-001 Son Goku Booster ENG", "DBS B24-010 Beyond Generations Card Booster ENG", "Dragon Ball Masters B27 Sleeves", "Dragon Ball Masters B27 Display opened ENG"])
def test_masters_singles_accessories_and_opened_products_are_excluded(title):
    assert classify(source(title), "fixture") is None


def test_masters_separate_filter_set_and_saved_rule(factory, settings):
    with factory() as db:
        merchant = db.scalar(select(Merchant))
        masters, _ = ingest(db, merchant, source("Dragon Ball Super Masters B27 Display 24 Booster ENG"))
        fusion, _ = ingest(db, merchant, replace(source("Dragon Ball Super Fusion World FB27 Display 24 Booster ENG"), external_id="fusion"))
        master_game = db.scalar(select(Game).where(Game.slug == "dragon-ball-masters"))
        rule = SearchRule(name="Masters B27", game_ids=[master_game.id], set_codes=["BT27"], product_types=["display"], channels=["discord"], max_price_minor=13000)
        db.add(rule)
        db.flush()
        assert rule_matches(rule, masters, masters.product)
        assert not rule_matches(rule, fusion, fusion.product)
        db.commit()
    with TestClient(create_app(settings, factory)) as client:
        headers = {"X-Radar-Key": settings.api_key}
        games = client.get("/api/meta", headers=headers).json()
        assert len(games["games"]) == 4
        assert any(s["code"] == "B-27" and s["game_id"] == master_game.id for s in games["sets"])
        for query in ("game=dragon-ball-masters", "q=BT27", "q=B-27", "game=dragon-ball-masters&set_code=B-27"):
            result = client.get("/api/offers?" + query, headers=headers).json()
            assert result["total"] == 1
            assert result["items"][0]["game"] == "dragon-ball-masters"
        assert client.get("/api/offers?game=dragon-ball-masters&game=dragon-ball-fusion-world", headers=headers).json()["total"] == 2
