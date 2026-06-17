"""Engine inactivity diagnosis — the 'why isn't the bot trading?' logic."""
from services.auto_engine import explain_inactivity


def _kw(**over):
    base = dict(running=True, trading_state="Active", mode="live", timeframe="4h",
                bars=500, signals=3, trades=2, rejections=1,
                data_source="live (ccxt)", last_activity_age_s=100.0)
    base.update(over)
    return base


def test_stopped():
    assert explain_inactivity(**_kw(running=False))["status"] == "stopped"


def test_halted():
    assert explain_inactivity(**_kw(trading_state="Paused"))["status"] == "halted"


def test_no_data():
    assert explain_inactivity(**_kw(bars=0))["status"] == "no_data"


def test_stale_live_feed_is_critical():
    v = explain_inactivity(**_kw(mode="live", data_source="bundled sample"))
    assert v["status"] == "stale_feed" and v["severity"] == "critical"
    assert "Binance" in v["detail"] or "cloud" in v["detail"]


def test_waiting_candles_on_high_timeframe():
    # last candle ~ a day ago on 4h -> infrequent by design
    v = explain_inactivity(**_kw(mode="live", data_source="live (ccxt)",
                                 last_activity_age_s=86400.0))
    assert v["status"] == "waiting_candles"


def test_no_setup_when_no_signals():
    v = explain_inactivity(**_kw(mode="replay", data_source="synthetic",
                                 signals=0, trades=0, rejections=0, last_activity_age_s=5.0))
    assert v["status"] == "no_setup"


def test_all_blocked():
    v = explain_inactivity(**_kw(mode="replay", data_source="synthetic",
                                 signals=5, trades=0, rejections=5, last_activity_age_s=5.0))
    assert v["status"] == "all_blocked" and v["severity"] == "warning"


def test_active():
    v = explain_inactivity(**_kw(mode="replay", data_source="synthetic", last_activity_age_s=5.0))
    assert v["status"] == "active"


def test_endpoint():
    import pytest
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    body = TestClient(app).get("/engine/diagnostics").json()
    assert "status" in body and "headline" in body and "detail" in body
