from datetime import timedelta
import httpx
from sqlalchemy import select

from app.db import utcnow
from app.models import Notification
from app.notifications import deliver_pending


def test_discord_delivers_once_and_disables_mentions(factory, settings):
    calls = []
    def handler(request):
        calls.append(request)
        assert b'"allowed_mentions":{"parse":[]}' in request.content
        return httpx.Response(200, json={"id": "message-id"})
    with factory() as db:
        db.add(Notification(channel="discord", payload={"title": "Test", "text": "@everyone Must not ping"}))
        db.commit()
    transport = httpx.MockTransport(handler)
    deliver_pending(factory, settings, transport)
    deliver_pending(factory, settings, transport)
    assert len(calls) == 1
    with factory() as db:
        item = db.scalar(select(Notification))
        assert item.status == "sent" and item.sent_at is not None


def test_rate_limit_retries_and_read_timeout_does_not_replay(factory, settings):
    with factory() as db:
        db.add(Notification(channel="discord", payload={"title": "Test", "text": "Test"}))
        db.commit()
    deliver_pending(factory, settings, httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "5"})))
    with factory() as db:
        item = db.scalar(select(Notification))
        assert item.status == "pending" and item.attempts == 1
        item.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
    def timeout(request):
        raise httpx.ReadTimeout("response lost", request=request)
    deliver_pending(factory, settings, httpx.MockTransport(timeout))
    with factory() as db:
        assert db.scalar(select(Notification)).status == "uncertain"
    deliver_pending(factory, settings, httpx.MockTransport(lambda _: (_ for _ in ()).throw(AssertionError("Must not resend"))))


def test_telegram_uses_bot_api_and_checks_ok(factory, settings):
    settings = settings.model_copy(update={"telegram_bot_token": "test-token", "telegram_chat_id": "123"})
    def handler(request):
        assert request.url.host == "api.telegram.org"
        assert request.url.path.endswith("/sendMessage")
        assert b'"chat_id":"123"' in request.content
        return httpx.Response(200, json={"ok": True, "result": {}})
    with factory() as db:
        db.add(Notification(channel="telegram", payload={"title": "Test", "text": "Test"}))
        db.commit()
    deliver_pending(factory, settings, httpx.MockTransport(handler))
    with factory() as db:
        assert db.scalar(select(Notification)).status == "sent"


def test_disabled_channels_do_not_replay_old_alerts_when_enabled(factory, settings):
    with factory() as db:
        db.add(Notification(channel="discord", payload={"title": "Old event", "text": "Old event"}))
        db.commit()
    deliver_pending(factory, settings.model_copy(update={"notifications_enabled": False}))
    deliver_pending(factory, settings, httpx.MockTransport(lambda _: (_ for _ in ()).throw(AssertionError("No historical flood"))))
    with factory() as db:
        assert db.scalar(select(Notification)).status == "muted"
