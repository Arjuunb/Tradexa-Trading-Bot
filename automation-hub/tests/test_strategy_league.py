"""Strategy League: ranked by expectancy (not raw win rate), daily-return
correlations, honest no-data verdict, actionable best pairing."""
import pytest

from services.strategy_league import _daily_r, league, pearson


# ─────────────────────────── pure math ───────────────────────────
def test_pearson_basics():
    assert pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == 1.0
    assert pearson([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == -1.0
    assert pearson([1, 2], [1, 2]) is None            # too short
    assert pearson([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None  # zero variance


def test_daily_r_groups_by_exit_day():
    trades = [{"exit_time": "2026-07-01T05:00:00", "r": 1.0},
              {"exit_time": "2026-07-01T18:00:00", "r": -0.5},
              {"exit_time": "2026-07-02T03:00:00", "r": 2.0}]
    d = _daily_r(trades)
    assert d == {"2026-07-01": 0.5, "2026-07-02": 2.0}


# ─────────────────────────── the league ───────────────────────────
def test_league_honest_without_real_data(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config.settings, "market_db", str(tmp_path / "empty.db"))
    monkeypatch.setenv("HUB_REQUIRE_REAL_DATA", "1")
    rep = league(symbols=("BTCUSDT",), timeframe="1h")
    assert rep["available"] is False and "Load real Binance data" in rep["detail"]


def test_league_ranks_and_correlates():
    # synthetic allowed in tests (require_real=False); production stays honest
    rep = league(symbols=("ZZZUSDT",), timeframe="1h", bars=2000,
                 strategies=["Decision Brain", "EMA 8/30", "EMA 20/50"],
                 require_real=False)
    assert rep["available"] is True
    table = rep["table"]
    assert len(table) == 3
    for row in table:
        assert row["verdict"] in ("earning", "losing", "breakeven", "insufficient-sample")
        if row["verdict"] != "insufficient-sample":
            assert row["trades"] >= 10 and row["expectancy_r"] is not None
    # ranked: judged strategies come before insufficient samples, best expectancy first
    judged = [r for r in table if r["verdict"] != "insufficient-sample"]
    exps = [r["expectancy_r"] for r in judged]
    assert exps == sorted(exps, reverse=True)
    # correlations only among judged pairs, with a named relation
    for c in rep["correlations"]:
        assert -1.0 <= c["correlation"] <= 1.0
        assert c["relation"] in ("diversifying", "related", "redundant")
    assert any("win rate alone misleads" in g.lower() or "win rate alone" in g.lower()
               for g in rep["guidance"])


def test_league_best_combo_requires_two_earners():
    rep = league(symbols=("ZZZUSDT",), timeframe="1h", bars=2000,
                 strategies=["Decision Brain", "EMA 8/30", "EMA 20/50"],
                 require_real=False)
    combo = rep["best_combo"]
    if combo is not None:                              # depends on the series
        earners = {r["strategy"] for r in rep["table"] if r["verdict"] == "earning"}
        assert combo["a"] in earners and combo["b"] in earners


# ─────────────────────────── endpoint ───────────────────────────
def test_league_endpoint():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    body = client.get("/strategy/league", params={"symbols": "BTCUSDT", "bars": 800}).json()
    assert "available" in body