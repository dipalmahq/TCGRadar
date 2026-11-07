"""Read-only checks executed INSIDE the API container; never prints secrets.

Linux / Ubuntu:
    docker compose exec -T api python - < scripts/check_deployment.py
PowerShell / WSL:
    Get-Content -Raw scripts/check_deployment.py | wsl ... --exec docker compose exec -T api python -

Waits up to three minutes for the initial real shop imports. No alerts are sent.
"""
import json
import logging
import time

import httpx
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import SessionLocal
from app.models import Notification, Offer, OfferEvent
from app.seed import GAMES

logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    settings = get_settings()
    headers = {"X-Radar-Key": settings.api_key}
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10, trust_env=False) as client:
        assert client.get("/api/health").status_code == 200, "API health failed"
        assert client.get("/api/offers").status_code == 401, "Production API is not protected"
        assert client.get("/").status_code == 200, "Dashboard missing"
        meta = client.get("/api/meta", headers=headers)
        assert meta.status_code == 200, "Team key rejected"
        assert {g["slug"] for g in meta.json()["games"]} == {slug for slug, _, _ in GAMES}, "Supported game catalog differs"
        deadline = time.monotonic() + 180
        while True:
            response = client.get("/api/shops", headers=headers)
            response.raise_for_status()
            shops = response.json()
            if len(shops) >= 2 and all(s["last_success_at"] and not s["error_count"] for s in shops if s["enabled"]):
                break
            if time.monotonic() > deadline:
                raise AssertionError("Initial shop checks did not complete successfully within three minutes")
            time.sleep(3)
        response = client.get("/api/offers", params={"limit": 1}, headers=headers)
        response.raise_for_status()
        offers = response.json()
        assert offers["total"] > 0 and offers["items"], "No real offers imported"
        offer = offers["items"][0]
        assert offer["url"].startswith("https://"), "Invalid offer link"
        assert client.get(f"/api/offers/{offer['id']}/history", headers=headers).json(), "History missing"
        overview = client.get("/api/overview", headers=headers).json()
    with SessionLocal() as db:
        version = db.execute(text("SELECT version()")).scalar()
        assert version.startswith("PostgreSQL"), "Expected actual PostgreSQL"
        results = {
            "status": "passed",
            "database": version.split(" on ")[0],
            "api_authentication": "verified",
            "dashboard": "served",
            "real_offers": db.scalar(select(func.count(Offer.id)).where(Offer.excluded.is_(False))),
            "excluded_records": db.scalar(select(func.count(Offer.id)).where(Offer.excluded.is_(True))),
            "events": db.scalar(select(func.count(OfferEvent.id))),
            "notifications": db.scalar(select(func.count(Notification.id))),
            "notification_states": [
                {"id": n.id, "channel": n.channel, "status": n.status,
                 "attempts": n.attempts, "sent_at": n.sent_at.isoformat() if n.sent_at else None}
                for n in db.scalars(select(Notification).order_by(Notification.id))
            ],
            "in_stock": overview["in_stock"],
            "preorders": overview["preorders"],
            "shops": [{"name": s["name"], "last_success_at": s["last_success_at"], "offers": s["last_offer_count"]} for s in shops],
        }
    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Avoid exception representations that could include URLs or credentials.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
