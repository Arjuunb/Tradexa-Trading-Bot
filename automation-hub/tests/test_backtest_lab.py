"""Advanced backtesting lab: walk-forward, Monte Carlo, OOS, sliced testing."""
import pytest

from services.backtest_lab import (walk_forward, monte_carlo, out_of_sample,
                                    sliced_performance)


def test_walk_forward_folds_and_verdict():
    r = walk_forward("EMA 8/30", "BTCUSDT", "4h", bars=2800, folds=3)
    assert r["available"] is True
    assert r["total_folds"] >= 2
    for f in r["folds"]:
        assert f["best_min_score"] in (50, 60, 70, 80)
        assert "train_net_r" in f and "test_net_r" in f and "test_trades" in f
    # aggregate out-of-sample R equals the sum of the fold test results
    assert r["oos_net_r"] == round(sum(f["test_net_r"] for f in r["folds"]), 2)
    assert r["verdict"] in ("robust", "fragile", "mixed")
    assert 0 <= r["positive_folds"] <= r["total_folds"]


def test_monte_carlo_distribution_is_ordered():
    r = monte_carlo("EMA 8/30", "BTCUSDT", "4h", bars=2800, runs=300, seed=7)
    assert r["available"] is True
    if "error" in r:
        pytest.skip("too few trades on the seeded series")
    n = r["net_r"]
    assert n["p5"] <= n["median"] <= n["p95"]               # percentiles ordered
    dd = r["max_drawdown_r"]
    assert dd["median"] <= dd["p95"] <= dd["worst"]
    assert 0 <= r["prob_profit_pct"] <= 100
    assert r["runs"] == 300 and r["trades"] >= 10


def test_monte_carlo_is_deterministic_with_seed():
    a = monte_carlo("EMA 8/30", "BTCUSDT", "4h", bars=2800, runs=300, seed=42)
    b = monte_carlo("EMA 8/30", "BTCUSDT", "4h", bars=2800, runs=300, seed=42)
    assert a.get("net_r") == b.get("net_r")


def test_out_of_sample_split_and_verdict():
    r = out_of_sample("Decision Brain", "BTCUSDT", "4h", bars=2800, split=0.7)
    assert r["available"] is True
    assert "train" in r and "test" in r
    assert r["verdict"] in ("holds", "overfit", "weak")
    for seg in (r["train"], r["test"]):
        assert "net_r" in seg and "trades" in seg and "profit_factor" in seg


def test_sliced_performance_buckets():
    r = sliced_performance("EMA 8/30", "15m", symbols=("BTCUSDT", "ETHUSDT"), limit=600)
    for key in ("by_regime", "by_session", "by_symbol"):
        assert key in r
    # per-symbol buckets cover the requested symbols and are net-R ranked
    syms = {b["key"] for b in r["by_symbol"]}
    assert {"BTCUSDT", "ETHUSDT"} <= syms
    nets = [b["net_r"] for b in r["by_symbol"]]
    assert nets == sorted(nets, reverse=True)
    # total trades equals the sum across symbol buckets
    assert r["total_trades"] == sum(b["trades"] for b in r["by_symbol"])


def test_unavailable_when_no_real_data(monkeypatch):
    import services.backtest_lab as lab
    monkeypatch.setattr(lab, "_fetch", lambda *a, **k: ([], "unavailable"))
    for fn in (walk_forward, monte_carlo, out_of_sample):
        r = fn("Decision Brain", "BTCUSDT", "4h", bars=2000)
        assert r["available"] is False and "error" in r


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_lab_endpoints(client):
    wf = client.get("/lab/walk-forward", params={"symbol": "BTCUSDT", "strategy": "EMA 8/30",
                                                "timeframe": "4h", "bars": 2800, "folds": 3}).json()
    assert wf["available"] is True and "folds" in wf and "verdict" in wf
    oos = client.get("/lab/out-of-sample", params={"symbol": "BTCUSDT", "strategy": "Decision Brain",
                                                   "timeframe": "4h", "bars": 2800}).json()
    assert oos["available"] is True and "train" in oos and "test" in oos
    sl = client.get("/lab/sliced", params={"strategy": "EMA 8/30", "timeframe": "15m",
                                          "symbols": "BTCUSDT,ETHUSDT", "limit": 600}).json()
    assert "by_regime" in sl and "by_symbol" in sl
