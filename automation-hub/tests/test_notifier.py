"""Telegram notifier — fail-safe, gated, and the /notifications endpoints."""
import pytest

from services.notifier import Notifier


def test_not_configured_is_noop():
    n = Notifier("", "")
    assert n.configured is False
    assert n.send("hi") is False           # no network call, no crash
    n.dispatch("trade", "x", "y")          # silently does nothing


def test_dispatch_respects_event_flags(monkeypatch):
    n = Notifier("tok", "chat")
    sent = []
    monkeypatch.setattr(n, "send_async", lambda t: sent.append(t))
    n.notify_trades = False
    n.dispatch("trade", "open", "BTC")     # trades off -> nothing
    assert sent == []
    n.notify_trades = True
    n.dispatch("trade", "open", "BTC")
    assert sent and "open" in sent[0]
    n.notify_risk = False
    n.dispatch("risk", "halt", "")         # risk off -> nothing
    assert len(sent) == 1


def test_send_never_raises_on_bad_host():
    # unreachable/invalid token -> returns False, never raises
    assert Notifier("bad", "bad").send("x") is False


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI()
    app.include_router(webhook_api.router)
    yield TestClient(app)
    webhook_api.engine.stop()


SECRET = "dev-webhook-secret"


def test_notifications_endpoints(client):
    s = client.get("/notifications/status").json()
    assert "telegram_configured" in s and "notify_trades" in s
    assert client.post("/notifications", json={"notify_trades": False}).status_code == 401
    r = client.post("/notifications", json={"notify_trades": False}, headers={"X-Webhook-Secret": SECRET})
    assert r.json()["notify_trades"] is False
    # test send (not configured by default) -> sent False, no crash
    t = client.post("/notifications/test", headers={"X-Webhook-Secret": SECRET})
    assert t.status_code == 200 and "sent" in t.json()
