"""Multi-asset / multi-timeframe sweep.

Contract: every cell is a real backtest, skipped cells are reported with a
reason, thin cells never win a ranking, and a truncated sweep says so."""
import pytest

from services.strategy_sweep import sweep

SPEC = {"symbol": "BTCUSDT", "timeframe": "4h", "entry": {"op": "AND", "rules": []}}


def _res(net_r, trades=20, **kw):
    d = {"trades": [{"r": 1.0}] * trades, "total_trades": trades, "net_r": net_r,
         "win_rate": 50.0, "profit_factor": 1.5, "net_pct": net_r,
         "max_drawdown_r": -5.0, "expectancy_r": 0.2}
    d.update(kw)
    return d


def test_ranks_assets_and_timeframes_by_real_results():
    table = {("BTCUSDT", "4h"): _res(20.0), ("BTCUSDT", "1h"): _res(5.0),
             ("ETHUSDT", "4h"): _res(-3.0), ("ETHUSDT", "1h"): _res(1.0)}
    out = sweep(SPEC, ["BTCUSDT", "ETHUSDT"], ["4h", "1h"],
                lambda s, sym, tf: table[(sym, tf)])
    assert out["available"] is True and len(out["cells"]) == 4
    assert out["cells"][0]["net_r"] == 20.0          # ranked best-first
    assert out["best_asset"]["symbol"] == "BTCUSDT"
    assert out["worst_asset"]["symbol"] == "ETHUSDT"
    assert out["best_timeframe"]["timeframe"] == "4h"


def test_cells_without_data_are_skipped_with_a_reason():
    def runner(s, sym, tf):
        return _res(10.0) if sym == "BTCUSDT" else None
    out = sweep(SPEC, ["BTCUSDT", "DOGEUSDT"], ["4h"], runner)
    assert len(out["cells"]) == 1
    assert out["skipped"][0]["symbol"] == "DOGEUSDT"
    assert "no trades" in out["skipped"][0]["why"]


def test_a_failing_cell_does_not_kill_the_sweep():
    def runner(s, sym, tf):
        if sym == "BAD":
            raise RuntimeError("boom")
        return _res(7.0)
    out = sweep(SPEC, ["BAD", "BTCUSDT"], ["4h"], runner)
    assert len(out["cells"]) == 1 and out["cells"][0]["symbol"] == "BTCUSDT"
    assert "backtest failed" in out["skipped"][0]["why"]


def test_thin_cells_are_flagged_and_cannot_win_a_ranking():
    """Two lucky trades must not crown an asset."""
    table = {("THIN", "4h"): _res(99.0, trades=2), ("SOLID", "4h"): _res(10.0, trades=40)}
    out = sweep(SPEC, ["THIN", "SOLID"], ["4h"], lambda s, sym, tf: table[(sym, tf)])
    assert out["cells"][0]["symbol"] == "THIN"        # still shown, ranked by net R
    assert out["cells"][0]["thin"] is True
    assert out["best_asset"]["symbol"] == "SOLID"     # but never crowned


def test_truncation_is_reported():
    out = sweep(SPEC, [f"S{i}" for i in range(10)], ["4h", "1h"],
                lambda s, sym, tf: _res(1.0), max_cells=5)
    assert out["truncated"] is True and out["max_cells"] == 5
    assert len(out["cells"]) <= 5


def test_empty_sweep_is_honest():
    out = sweep(SPEC, ["X"], ["4h"], lambda s, sym, tf: None)
    assert out["available"] is False
    assert "nothing can be ranked" in out["note"].lower()
    assert out["best_asset"] is None


def test_single_value_has_no_worst_comparison():
    """With one asset there is nothing to call 'worst'."""
    out = sweep(SPEC, ["BTCUSDT"], ["4h"], lambda s, sym, tf: _res(5.0))
    assert out["best_asset"]["symbol"] == "BTCUSDT"
    assert out["worst_asset"] is None


def test_defaults_fall_back_to_the_spec():
    out = sweep(SPEC, [], [], lambda s, sym, tf: _res(3.0))
    assert out["cells"][0]["symbol"] == "BTCUSDT"
    assert out["cells"][0]["timeframe"] == "4h"


# ------------------------------------------------------------------ endpoint

@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


def test_sweep_endpoint_runs_real_backtests(client):
    spec = {"name": "EMA", "symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
            "entry": {"op": "AND", "rules": [
                {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"}]},
            "stop": {"type": "atr", "mult": 1.5, "period": 14},
            "target": {"type": "rr", "rr": 2}, "risk_per_trade_pct": 0.01}
    r = client.post("/strategy/sweep", json={
        "spec": spec, "symbols": ["BTCUSDT", "ETHUSDT"], "timeframes": ["4h"],
        "range": "1Y"})
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is True
    assert {c["symbol"] for c in j["cells"]} <= {"BTCUSDT", "ETHUSDT"}
    for c in j["cells"]:
        assert c["trades"] is not None and c["net_r"] is not None


def test_sweep_endpoint_requires_entry_rules(client):
    assert client.post("/strategy/sweep", json={"spec": {}}).status_code == 400


# ------------------------------- timeframe-integrity guard (real data hazard)

def test_unverified_timeframes_are_excluded_from_the_tf_ranking():
    """Some sources return one fixed candle size whatever timeframe is asked
    for. Ranking timeframes on that compares a series against itself, so those
    cells must be excluded and the caveat surfaced."""
    def runner(s, sym, tf):
        r = _res(10.0 if tf == "4h" else 9.0)
        r["__tf_verified"] = (sym == "SOLUSDT")      # only SOL honours the tf
        return r
    out = sweep(SPEC, ["BTCUSDT", "SOLUSDT"], ["4h", "1h"], runner)
    assert out["timeframe_comparable"] is True
    assert out["best_timeframe"]["cells"] == 1        # SOL cells only
    assert any("BTCUSDT" in c for c in out["caveats"])
    # asset ranking is unaffected — that comparison is still valid
    assert out["best_asset"] is not None


def test_no_comparable_timeframes_is_reported_not_faked():
    def runner(s, sym, tf):
        r = _res(5.0); r["__tf_verified"] = False; return r
    out = sweep(SPEC, ["BTCUSDT"], ["4h", "1h"], runner)
    assert out["timeframe_comparable"] is False
    assert out["best_timeframe"] is None
    assert out["caveats"]


def test_timeframe_matches_detects_real_spacing():
    from datetime import datetime, timedelta, timezone
    from services.strategy_sweep import timeframe_matches

    class B:
        def __init__(self, ts): self.timestamp = ts
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    hourly = [B(t0 + timedelta(hours=i)) for i in range(8)]
    assert timeframe_matches(hourly, "1h") is True
    assert timeframe_matches(hourly, "4h") is False     # the real hazard
    four_h = [B(t0 + timedelta(hours=4 * i)) for i in range(8)]
    assert timeframe_matches(four_h, "4h") is True
