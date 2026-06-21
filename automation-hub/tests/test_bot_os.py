"""Bot Operating System (#20): event bus + service registry."""
import pytest

from services.bot_os import BotOS, EventBus, ENGINES


def test_event_bus_publish_subscribe_and_failsafe():
    bus = EventBus()
    got = []
    bus.subscribe("risk", lambda e: got.append(e["payload"]))
    bus.subscribe("*", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))  # bad handler
    bus.publish("risk", "alert", {"x": 1})
    assert got == [{"x": 1}]                                # delivered despite the bad subscriber
    assert bus.recent()[0]["topic"] == "risk"


def test_botos_registers_nine_engines():
    os_ = BotOS()
    assert len(os_.services) == len(ENGINES) == 9
    names = {s["name"] for s in os_.services.values()}
    assert {"Market Engine", "Risk Engine", "Execution Engine", "Replay Engine",
            "Journal Engine", "AI Coach Engine"} <= names


def test_snapshot_reflects_status_fn():
    os_ = BotOS()
    os_.set_status_fn("Execution Engine", lambda: {"state": "idle", "detail": "stopped"})
    os_.set_status_fn("Risk Engine", lambda: (_ for _ in ()).throw(ValueError("x")))  # raises
    snap = os_.snapshot()
    by = {s["name"]: s for s in snap["services"]}
    assert by["Execution Engine"]["state"] == "idle"
    assert by["Risk Engine"]["state"] == "error"            # caught, surfaced
    assert snap["engines"] == 9 and snap["status"] == "degraded"


def test_recent_events_capture():
    os_ = BotOS()
    os_.bus.publish("market", "tick", {"symbol": "BTCUSDT"})
    assert os_.snapshot()["recent_events"][0]["payload"]["symbol"] == "BTCUSDT"


# ───────────────────────── endpoint ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_bot_os_endpoint(client):
    snap = client.get("/bot-os").json()
    assert snap["engines"] == 9 and "services" in snap and "recent_events" in snap
    assert "architecture" in snap
