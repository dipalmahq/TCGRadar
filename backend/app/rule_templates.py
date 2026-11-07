"""Explicitly install paused crew templates; never enable broad alerts by default."""
from sqlalchemy import select

from app.models import Game, SearchRule


def prepare_templates(db):
    created = 0
    for game in db.scalars(select(Game).order_by(Game.id)):
        for product_type, label in (("display", "Displays"), ("booster", "Booster")):
            name = f"Vorlage · {game.product_line} · {label}"
            if db.scalar(select(SearchRule.id).where(SearchRule.name == name)):
                continue
            db.add(SearchRule(name=name, game_ids=[game.id], product_types=[product_type],
                              channels=["discord"], enabled=False, include_preorders=False))
            created += 1
    db.commit()
    return created
