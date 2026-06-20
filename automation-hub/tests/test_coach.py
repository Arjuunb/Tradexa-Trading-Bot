"""AI Coach + Explainability + Attribution: buckets, narrative, per-trade why."""
import pytest

from services.coach import attribution, explain_trade, coach_review, _setup_tag


def _t(tid, side, rr, regime, hour, reasons, result):
    return {"id": tid, "side": side, "rr": rr, "regime": regime,
            "entry_time": f"2024-01-01T{hour:02d}:00:00+00:00", "entry_reasons": reasons,
            "result": result, "score": 70, "symbol": "BTCUSDT",
            "loss_analysis": ("Entered in choppy / unclear conditions." if rr < 0 else None),
            "mtf": {"aligned": True, "reason": "higher-timeframe aligned"}}


TRADES = [
    _t(1, "long", 2.0, "Trending", 14, ["4H bullish", "Daily bullish"], "Winner"),
    _t(2, "long", 1.5, "Trending", 15, ["liquidity sweep"], "Winner"),
    _t(3, "short", -1.0, "Ranging", 3, ["Daily bearish"], "Loser"),
    _t(4, "short", -1.0, "Ranging", 4, ["structure shift (BOS/CHoCH)"], "Loser"),
    _t(5, "long", -1.0, "Ranging", 2, ["4H bullish"], "Loser"),
]
STATS = {"trades": 5, "win_rate": 40.0, "profit_factor": 1.75, "net_r": 0.5, "max_drawdown_r": 1.5}


def test_setup_tag_classification():
    assert _setup_tag(["liquidity sweep"]) == "Liquidity sweep"
    assert _setup_tag(["structure shift (BOS/CHoCH)"]) == "Structure shift"
    assert _setup_tag(["EMA 8 over EMA 30 cross"]) == "EMA cross"
    assert _setup_tag([]) == "Other confluence"


def test_attribution_buckets_sum_and_rank():
    a = attribution(TRADES)
    for key in ("by_session", "by_regime", "by_setup", "by_side", "by_symbol"):
        assert key in a
    # net R across all session buckets equals total net R
    total = round(sum(b["net_r"] for b in a["by_session"]), 2)
    assert total == round(sum(t["rr"] for t in TRADES), 2)
    # regimes: Trending positive, Ranging negative
    reg = {b["key"]: b["net_r"] for b in a["by_regime"]}
    assert reg["Trending"] > 0 and reg["Ranging"] < 0
    # buckets are sorted best-first
    assert a["by_regime"][0]["net_r"] >= a["by_regime"][-1]["net_r"]


def test_explain_trade_answers_why_whynot_whytrust():
    e = explain_trade(TRADES[0])     # winner
    assert e["why"].startswith("Entered long") and "70/100" in e["why"]
    assert "target" in e["why_not"].lower() or e["rr"] > 0
    assert "confidence" not in e and "why_trust" in e and "validate" in e["why_trust"].lower()
    loser = explain_trade(TRADES[2])
    assert "choppy" in loser["why_not"].lower()


def test_coach_review_narrative_and_scores():
    r = coach_review(TRADES, STATS, symbol="BTCUSDT", strategy="Decision Brain")
    assert r["trades"] == 5 and r["net_r"] == 0.5
    assert "Decision Brain" in r["headline"] and "BTCUSDT" in r["headline"]
    assert any("Trending" in w for w in r["why_won"])      # trending made money
    assert any("Ranging" in w for w in r["why_lost"])      # ranging lost money
    assert "Ranging (regime)" in r["weak_conditions"]
    # common mistake aggregated from loss_analysis
    assert r["common_mistakes"] and r["common_mistakes"][0]["count"] == 3
    assert 0 <= r["confidence_score"] <= 100 and 0 <= r["stability_score"] <= 100
    assert r["suggestions"]
    assert r["sample_explanations"]                         # per-trade explanations attached


def test_coach_review_handles_no_trades():
    r = coach_review([], {"trades": 0}, symbol="BTCUSDT", strategy="EMA 20/50")
    assert r["trades"] == 0 and r["confidence_score"] == 0 and r["suggestions"]


# ───────────────────────── endpoints (real replay) ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_coach_review_endpoint(client):
    body = client.get("/coach/review", params={"symbol": "BTCUSDT", "strategy": "EMA 8/30",
                                               "timeframe": "15m", "limit": 600}).json()
    assert body["available"] is True
    for k in ("headline", "why_won", "why_lost", "common_mistakes", "weak_conditions",
              "suggestions", "confidence_score", "attribution", "sample_explanations"):
        assert k in body


def test_coach_leaderboard_ranks_strategies(client):
    body = client.get("/coach/leaderboard", params={"symbols": "BTCUSDT", "timeframe": "15m",
                                                    "strategies": "EMA 8/30,EMA 20/50", "limit": 600}).json()
    assert "grid" in body and "by_strategy" in body and "by_symbol" in body
    assert len(body["grid"]) == 2                          # 1 symbol × 2 strategies
    nets = [r["net_r"] for r in body["grid"]]
    assert nets == sorted(nets, reverse=True)              # ranked best-first
