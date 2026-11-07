import json

from sqlalchemy import select

from app.config import Settings
from app.models import Game, Merchant

GAMES = [
    ("one-piece", "One Piece", "One Piece Card Game"),
    ("pokemon", "Pokémon", "Pokémon TCG"),
    ("dragon-ball-fusion-world", "Dragon Ball", "Dragon Ball Super Card Game: Fusion World"),
    ("dragon-ball-masters", "Dragon Ball Masters", "Dragon Ball Super Card Game: Masters"),
]


def seed(db, settings: Settings):
    for slug, name, line in GAMES:
        if not db.scalar(select(Game).where(Game.slug == slug)):
            db.add(Game(slug=slug, name=name, product_line=line))
    if settings.shops_file.exists():
        for data in json.loads(settings.shops_file.read_text(encoding="utf-8")):
            merchant = db.scalar(select(Merchant).where(Merchant.slug == data["slug"]))
            if merchant is None:
                db.add(Merchant(**data))
            else:
                for key in ("name", "base_url", "adapter", "country", "config", "interval_seconds"):
                    setattr(merchant, key, data[key])
    db.commit()
