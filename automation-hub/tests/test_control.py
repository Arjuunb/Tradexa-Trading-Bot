"""Top control bar: preset resolution, real simulation, warning, compare,
versioning, and the real-data-required guard."""
import os

import pytest

from services.strategy_presets import (resolve, run_simulation, underperforming,
                                        compare, PRESETS, STRATEGY_OPTIONS, DEFAULT_TUNING)


def test_preset_resolution_builtin_and_custom():
    b = resolve("Decision Brain", "BTCUSDT", "4h", {})
    assert b["kind"] == "builtin" and b["key"] == "brain"
    c = resolve("EMA 8/30", "ETHUSDT", "15m", {"min_score": 70, "rr": 2.5})
    assert c["kind"] == "custom"
    assert c["spec"]["symbol"] == "ETHUSDT" and c["spec"]["timeframe"] == "15m"
    assert c["spec"]["min_score"] == 70 and c["spec"]["target"]["rr"] == 2.5
    assert any(r["type"] == "ema_cross" and r["fast"] == 8 for r in c["spec"]["entry"]["rules"])


def test_tuning_toggles_apply_to_spec():
    c = resolve("EMA 8/30", "BTCUSDT", "4h",
                {"volume_filter": True, "session_filter": True, "trend_filter": False,
                 "regime_filter": False, "max_trades_per_day": 3})
    spec = c["spec"]
    assert any(r["type"] == "volume" for r in spec["entry"]["rules"])   # volume filter added
    assert spec["session"] == {"start": 7, "end": 21}                  # session window
    assert spec["quality_filter"] is False                              # both brain filters off
    assert spec["max_trades_per_day"] == 3


def test_custom_strategy_requires_spec():
    assert "error" in resolve("Custom Strategy", "BTCUSDT", "4h", {})


def test_run_simulation_real_results():
    r = run_simulation("Decision Brain", "BTCUSDT", "4h", tuning={"min_score": 60}, bars=2500)
    assert r["available"] is True
    s = r["results"]
    for k in ("total_trades", "win_rate", "profit_factor", "net_r", "max_drawdown_pct",
              "equity_curve", "trades", "diagnosis"):
        assert k in s
    # warning is either a dict (weak) or None (fine)
    assert r["warning"] is None or "underperforming" in r["warning"]["message"]


def test_macro_confirmation_drive_the_mtf_gate():
    plain = run_simulation("EMA 8/30", "BTCUSDT", "5m", tuning={"min_score": 50}, bars=3000)
    gated = run_simulation("EMA 8/30", "BTCUSDT", "5m", tuning={"min_score": 50}, bars=3000,
                           macro="4h", confirmation="15m")
    assert plain["mtf_gate"] == []                       # no gate when not requested
    assert set(gated["mtf_gate"]) <= {"15m", "4h"} and gated["mtf_gate"]
    # the gate actually fired (blocked some setups) and changed the outcome
    assert gated["results"].get("blocked_count", 0) > 0
    assert gated["results"]["net_r"] != plain["results"]["net_r"]


def test_underperforming_fires_on_weak_stats():
    weak = {"total_trades": 30, "profit_factor": 0.8, "win_rate": 35, "max_drawdown_pct": 40}
    w = underperforming(weak)
    assert w and "underperforming" in w["message"]
    strong = {"total_trades": 30, "profit_factor": 1.6, "win_rate": 55, "max_drawdown_pct": 10}
    assert underperforming(strong) is None
    assert underperforming({"total_trades": 4}) is None   # too few trades


def test_compare_picks_winner():
    c = compare({"strategy": "Decision Brain", "symbol": "BTCUSDT", "timeframe": "4h"},
                {"strategy": "EMA 8/30", "symbol": "BTCUSDT", "timeframe": "4h"}, bars=2500)
    assert c["winner"] in ("A", "B")
    assert c["a"]["available"] and c["b"]["available"]


def test_real_data_required_message(monkeypatch):
    # simulate the production 'no real data' case without reloading any modules
    import data.market_data as md
    monkeypatch.setattr(md, "get_bars",
                        lambda *a, **k: ([], "unavailable (real data required — run /data/sync)"))
    r = run_simulation("Decision Brain", "BTCUSDT", "4h", bars=1000)
    assert r["available"] is False
    assert "Historical data not available" in r["error"]


# ---- endpoints ----
@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.evolution import StrategyVersionStore
    import webhook_api
    webhook_api.version_store = StrategyVersionStore(str(tmp_path / "v.json"))
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"


def test_options_endpoint(client):
    o = client.get("/control/options").json()
    assert o["strategies"] == STRATEGY_OPTIONS
    assert "BTCUSDT" in o["symbols"] and "1w" in o["timeframes"]
    assert o["default_tuning"]["min_score"] == DEFAULT_TUNING["min_score"]


def test_simulate_endpoint(client):
    body = client.post("/control/simulate", json={"strategy": "Decision Brain", "symbol": "BTCUSDT",
                                                  "timeframe": "4h", "tuning": {"min_score": 60}, "bars": 2000}).json()
    assert body["available"] is True and "results" in body


def test_save_version_endpoint_is_gated(client):
    payload = {"strategy": "Decision Brain", "symbol": "BTCUSDT", "timeframe": "4h", "bars": 2000}
    assert client.post("/control/save-version", json=payload).status_code == 401
    v = client.post("/control/save-version", json=payload, headers={"X-Webhook-Secret": SECRET}).json()
    assert v["version"] == 1 and v["strategy"] == "Decision Brain"


def test_auto_tune_returns_honest_verdict():
    from services.strategy_presets import auto_tune
    r = auto_tune("EMA 8/30", "BTCUSDT", "5m", macro="4h", confirmation="15m", bars=3000)
    assert r["available"] is True
    assert r["verdict"] in ("improvement", "overfit", "no_improvement")
    assert set(("min_score", "rr")) <= set(r["best_tuning"])
    # validation is the unseen test slice; baseline_test is the default on the same slice
    for k in ("validation", "baseline_test", "train", "trials"):
        assert k in r
    # never claims improvement unless out-of-sample net R actually beat the baseline
    if r["verdict"] == "improvement":
        assert r["validation"]["net_r"] > r["baseline_test"]["net_r"]
        assert r["validation"]["profit_factor"] >= 1


def test_auto_tune_endpoint(client):
    body = client.post("/control/auto-tune", json={"strategy": "EMA 8/30", "symbol": "BTCUSDT",
                                                   "timeframe": "5m", "macro": "4h",
                                                   "confirmation": "15m", "bars": 2500}).json()
    assert body["available"] is True and "best_tuning" in body and "verdict" in body
