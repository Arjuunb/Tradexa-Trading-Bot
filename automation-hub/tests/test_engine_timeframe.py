"""Engine timeframe switching: UI-selectable 1m/5m/15m/1h/4h/1d, applied live
via engine restart and persisted so it survives redeploys."""
import pytest

from services.runtime_settings import load_overrides, save_overrides


def test_engine_timeframe_persists_as_string(tmp_path):
    p = str(tmp_path / "runtime.json")
    save_overrides(p, {"engine_timeframe": "15m", "risk_per_trade_pct": 0.01})
    out = load_overrides(p)
    assert out["engine_timeframe"] == "15m"           # string, not mangled to float
    assert out["risk_per_trade_pct"] == 0.01


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    monkeypatch.setattr(webhook_api.settings, "settings_path",
                        str(tmp_path / "runtime.json"))
    app = FastAPI(); app.include_router(webhook_api.router)
    yield TestClient(app)
    webhook_api.engine.stop()                          # never leak a running thread


SECRET = "dev-webhook-secret"


def test_timeframe_endpoint_switches_restarts_and_persists(client, tmp_path):
    import webhook_api
    # requires the secret
    assert client.post("/engine/timeframe?timeframe=5m").status_code == 401
    # rejects unsupported values with the option list
    bad = client.post("/engine/timeframe?timeframe=7m",
                      headers={"X-Webhook-Secret": SECRET})
    assert bad.status_code == 400 and "1m" in bad.json()["detail"]
    # applies + restarts + persists
    r = client.post("/engine/timeframe?timeframe=5m",
                    headers={"X-Webhook-Secret": SECRET}).json()
    assert r["applied"] is True and r["timeframe"] == "5m"
    assert set(r["options"]) >= {"1m", "5m", "15m", "1h", "4h", "1d"}
    assert webhook_api.engine.timeframe == "5m"
    assert client.get("/engine/status").json()["timeframe"] == "5m"
    # persisted for the next boot
    assert load_overrides(str(tmp_path / "runtime.json"))["engine_timeframe"] == "5m"
    # restore the default so later tests see the usual config
    client.post("/engine/timeframe?timeframe=4h", headers={"X-Webhook-Secret": SECRET})


def test_boot_apply_setting_restores_timeframe():
    import webhook_api
    prev = webhook_api.engine.timeframe
    try:
        webhook_api._apply_setting("engine_timeframe", "1h")
        assert webhook_api.engine.timeframe == "1h"
    finally:
        webhook_api.engine.timeframe = prev
