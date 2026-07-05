"""Bot Health aggregation endpoint — one honest operational snapshot. Every
field comes from real engine / ledger / watchdog / skip-log state."""
import pytest


def test_health_bot_endpoint_shape_is_real():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)

    r = client.get("/health/bot").json()
    # all Bot Health sections present
    for key in ("engine", "data_source", "broker", "last_candle", "last_signal",
                "last_rejected", "open_positions", "daily_pnl", "risk",
                "watchdog", "errors"):
        assert key in r, f"missing {key}"

    # honest defaults: paper only, live locked, no faked broker
    assert r["broker"]["connected"] is False
    assert r["broker"]["live_locked"] is True
    assert r["engine"]["strategy"]  # real strategy label
    assert isinstance(r["errors"], list)
    assert isinstance(r["risk"]["exposure_pct"], (int, float))


def test_health_bot_surfaces_last_rejection_from_skip_log():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    sec = {"X-Webhook-Secret": webhook_api.settings.webhook_secret}

    # force a rejection through the real pipeline, then it must appear in health
    client.post("/controls/stop-all", headers=sec)
    client.post("/webhook/tradingview", headers=sec, json={
        "alert_id": "health-rej", "symbol": "BTCUSDT", "side": "BUY",
        "entry": 100.0, "stop": 95.0})
    client.post("/controls/resume", headers=sec)

    lr = client.get("/health/bot").json()["last_rejected"]
    assert lr is not None
    assert lr["stage"] == "controls" and "stopped" in lr["reason"].lower()
