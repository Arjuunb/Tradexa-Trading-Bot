"""Quant-phase enhancements: execution realism (#9), Monte Carlo ruin/survival
(#8), strategy-health drawdown score (#6), market-memory combos + store (#1)."""
import pytest


# ───────────────────────── execution realism (#9) ─────────────────────────
def test_execution_realism_costs_and_counts():
    from services.execution_sim import apply_execution_realism
    trades = [{"rr": 2.0, "entry": 100, "sl": 95} for _ in range(50)] + \
             [{"rr": -1.0, "entry": 100, "sl": 95} for _ in range(50)]
    out = apply_execution_realism(trades, reject_prob=0.0, partial_fill_prob=0.0, seed=1)
    assert out["realistic"]["net_r"] < out["ideal"]["net_r"]   # friction costs R
    assert out["slippage_cost_r"] > 0
    # rejections drop trades; partials reduce filled size
    out2 = apply_execution_realism(trades, reject_prob=0.5, partial_fill_prob=0.0, seed=2)
    assert out2["rejected"] > 0 and out2["trades"] < 100
    out3 = apply_execution_realism(trades, reject_prob=0.0, partial_fill_prob=1.0, seed=3)
    assert out3["partial_fills"] == 100


def test_execution_realism_deterministic():
    from services.execution_sim import apply_execution_realism
    t = [{"rr": 1.0, "entry": 100, "sl": 98} for _ in range(40)]
    a = apply_execution_realism(t, seed=9)
    b = apply_execution_realism(t, seed=9)
    assert a["realistic"] == b["realistic"]


# ───────────────────────── Monte Carlo ruin/survival (#8) ─────────────────────────
def test_monte_carlo_reports_ruin_and_survival():
    from services.backtest_lab import monte_carlo
    r = monte_carlo("EMA 8/30", "BTCUSDT", "4h", bars=2800, runs=300, seed=5, ruin_r=15)
    if not r.get("available") or "error" in r:
        pytest.skip("not enough trades on the seeded series")
    for k in ("probability_of_ruin_pct", "survival_probability_pct",
              "recovery_probability_pct", "expected_return_r"):
        assert k in r
    assert abs(r["probability_of_ruin_pct"] + r["survival_probability_pct"] - 100) < 0.2
    assert 0 <= r["survival_probability_pct"] <= 100


# ───────────────────────── strategy health drawdown score (#6) ─────────────────────────
def test_health_drawdown_score_and_classification():
    from services.recovery import health_scorecard, drawdown_score
    smooth = [{"pnl": 1, "r": 1} for _ in range(12)]
    choppy = [{"pnl": r, "r": r} for r in [4, -3, 5, -4, 3, -3, 4, -3, 3, -2, 4, -3]]
    assert drawdown_score(smooth) > drawdown_score(choppy)
    card = health_scorecard(smooth)
    assert card["classification"] in ("Healthy", "Warning", "Critical")
    assert "drawdown_score" in card and "health_score" in card and card["reasons"]
    losers = [{"pnl": -1, "r": -1} for _ in range(10)]
    assert health_scorecard(losers)["classification"] == "Critical"


# ───────────────────────── market memory combos + store (#1) ─────────────────────────
def test_memory_store_persists_and_recommends(tmp_path):
    from services.memory import MemoryStore
    ms = MemoryStore(str(tmp_path / "mem.json"))
    snap = {"timeframe": "15m", "combinations": [
        {"symbol": "BTCUSDT", "regime": "Bull trend", "strategy": "Trend Following", "trades": 10, "win_rate": 63.0, "net_r": 8.0},
        {"symbol": "ETHUSDT", "regime": "Choppy market", "strategy": "Trend Following", "trades": 8, "win_rate": 31.0, "net_r": -4.0}]}
    ms.save("Trend Following", snap)
    assert ms.get("Trend Following")["combinations"][0]["win_rate"] == 63.0
    assert len(ms.list()) == 1
    rec = ms.recommendations()
    assert rec["best_strategy_by_regime"]["Bull trend"]["strategy"] == "Trend Following"
    assert rec["best_strategy_by_symbol"]["BTCUSDT"]["net_r"] == 8.0


def test_strategy_combinations_real_data():
    from services.memory import strategy_combinations
    c = strategy_combinations("EMA 8/30", "15m", symbols=("BTCUSDT", "ETHUSDT"), limit=600)
    assert "combinations" in c and "best" in c and "worst" in c
    for row in c["combinations"]:
        assert "symbol" in row and "regime" in row and 0 <= row["win_rate"] <= 100


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    from services.memory import MemoryStore
    webhook_api.memory_store = MemoryStore(str(tmp_path / "mem.json"))
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"


def test_phase_endpoints(client):
    ex = client.get("/execution/realism", params={"symbol": "BTCUSDT", "strategy": "EMA 8/30",
                                                  "timeframe": "15m", "limit": 600}).json()
    assert ex["available"] is True and "ideal" in ex and "realistic" in ex
    combos = client.get("/memory/combinations", params={"strategy": "EMA 8/30", "timeframe": "15m",
                                                        "symbols": "BTCUSDT,ETHUSDT", "limit": 600}).json()
    assert "combinations" in combos
    assert client.post("/memory/snapshot", params={"strategy": "EMA 8/30", "symbols": "BTCUSDT,ETHUSDT", "limit": 600}).status_code == 401
    snap = client.post("/memory/snapshot", params={"strategy": "EMA 8/30", "symbols": "BTCUSDT,ETHUSDT", "limit": 600},
                       headers={"X-Webhook-Secret": SECRET}).json()
    assert snap["strategy"] == "EMA 8/30"
    assert client.get("/memory/snapshots").json()["snapshots"]
    card = client.get("/health/scorecard", params={"strategy": "EMA 8/30", "symbol": "BTCUSDT",
                                                   "timeframe": "15m", "limit": 600}).json()
    assert "classification" in card and "drawdown_score" in card
