"""Run inside API container. Queues exactly one requested Discord test alarm."""
import json
import logging
import time

import httpx

from app.config import get_settings

logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    settings = get_settings()
    if not settings.discord_webhook_url or not settings.notifications_enabled:
        print(json.dumps({"status": "not_configured", "channel": "discord"}))
        return 2
    headers = {"X-Radar-Key": settings.api_key}
    with httpx.Client(base_url="http://127.0.0.1:8000", headers=headers, timeout=10, trust_env=False) as client:
        queued = client.post("/api/notifications/test", json={"channel": "discord"})
        if queued.status_code != 202:
            print(json.dumps({"status": "not_queued", "http_status": queued.status_code}))
            return 1
        message_id = queued.json()["id"]
        print(json.dumps({"status": "queued", "notification_id": message_id, "channel": "discord"}), flush=True)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            response = client.get("/api/activity")
            response.raise_for_status()
            message = next((m for m in response.json()["notifications"] if m["id"] == message_id), None)
            if message and message["status"] in ("sent", "failed", "uncertain", "muted"):
                print(json.dumps({"status": message["status"], "notification_id": message_id, "sent_at": message.get("sent_at"), "channel": "discord"}))
                return 0 if message["status"] == "sent" else 1
            time.sleep(3)
        print(json.dumps({"status": "timeout", "notification_id": message_id, "note": "Check activity before retrying; no second alarm was queued."}))
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
