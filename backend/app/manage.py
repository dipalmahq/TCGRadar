import argparse
import json
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Merchant
from app.scanner import scan_shop
from app.seed import seed
from app.rule_templates import prepare_templates


def main():
    parser = argparse.ArgumentParser(description="JoyBoyz Radar administration")
    parser.add_argument("command", choices=["init", "migrate", "seed", "scan", "templates"])
    parser.add_argument("--shop", help="Configured shop slug; all enabled shops if omitted")
    parser.add_argument("--force", action="store_true", help="Run before next due time, keeping the shop lease")
    args = parser.parse_args()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command in ("init", "migrate"):
        config_path = Path("backend/alembic.ini")
        if not config_path.exists():
            config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
        command.upgrade(Config(str(config_path.resolve())), "head")
    if args.command in ("init", "seed"):
        with SessionLocal() as db:
            seed(db, settings)
    if args.command == "scan":
        with SessionLocal() as db:
            stmt = select(Merchant.id).where(Merchant.enabled.is_(True))
            if args.shop:
                stmt = stmt.where(Merchant.slug == args.shop)
            ids = list(db.scalars(stmt))
        if not ids:
            raise SystemExit("No configured shop matched")
        for shop_id in ids:
            result = scan_shop(SessionLocal, shop_id, settings, force=args.force)
            print(json.dumps(result, ensure_ascii=True), flush=True)
            if "error" in result:
                raise SystemExit(1)
    if args.command == "templates":
        with SessionLocal() as db:
            print(json.dumps({"created_paused_templates": prepare_templates(db)}))


if __name__ == "__main__":
    main()
