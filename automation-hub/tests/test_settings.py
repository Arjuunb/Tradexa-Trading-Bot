"""Runtime settings: real values, validation, and cross-session persistence."""
import pytest

from services.runtime_settings import load_overrides, save_overrides


def test_save_and_load_overrides_roundtrip(tmp_path):
    path = str(tmp_path / "s.json")
    save_overrides(path, {"risk_per_trade_pct": 0.02, "exposure_limit_pct": 0.1,
                          "max_drawdown_pct": 0.15, "ignored": 9})
    out = load_overrides(path)
    assert out == {"risk_per_trade_pct": 0.02, "exposure_limit_pct": 0.1, "max_drawdown_pct": 0.15}


def test_load_missing_file_is_empty(tmp_path):
    assert load_overrides(str(tmp_path / "nope.json")) == {}


@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import webhook_api
    from config import settings
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.controls import TradingControl
    from services.signal_pipeline import SignalPipeline
    from services.auto_engine import AutoStrategyEngine

    settings.settings_path = str(tmp_path / "runtime.json")
    led = SqliteLedger(":memory:")
    webhook_api.ledger = led
    webhook_api.controls = TradingControl()
    webhook_api.paper = PaperExecutionEngine(led, 10_000)
    webhook_api.pipeline = SignalPipeline(led, webhook_api.paper, webhook_api.controls,
                                          equity=10_000, risk_per_trade_pct=0.01,
                                          exposure_limit_pct=0.05, max_drawdown_pct=0.20)
    webhook_api.engine = AutoStrategyEngine(webhook_api.pipeline, webhook_api.paper, led,
                                            symbols=["BTCUSDT"], interval=0.01)
    app = FastAPI()
    app.include_router(webhook_api.router)
    yield TestClient(app)
    webhook_api.engine.stop()


SECRET = "dev-webhook-secret"


def test_get_settings_returns_real_values(client):
    s = client.get("/settings").json()
    assert s["editable"]["risk_per_trade_pct"] == 0.01
    assert s["readonly"]["mode"] == "paper"
    assert s["readonly"]["broker_connected"] is False


def test_post_settings_requires_secret_and_persists(client, tmp_path):
    assert client.post("/settings", json={"risk_per_trade_pct": 0.02}).status_code == 401
    r = client.post("/settings", json={"risk_per_trade_pct": 0.02, "max_drawdown_pct": 0.1},
                    headers={"X-Webhook-Secret": SECRET})
    assert r.status_code == 200 and r.json()["saved"] is True
    # applied live
    import webhook_api
    assert webhook_api.pipeline.risk_per_trade_pct == 0.02
    assert webhook_api.pipeline.max_drawdown_pct == 0.1
    # persisted to disk
    assert load_overrides(str(tmp_path / "runtime.json"))["risk_per_trade_pct"] == 0.02


def test_post_settings_validates_range(client):
    r = client.post("/settings", json={"risk_per_trade_pct": 5},
                    headers={"X-Webhook-Secret": SECRET})
    assert r.status_code == 400
