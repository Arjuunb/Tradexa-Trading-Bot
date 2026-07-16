"""AI Trading Intelligence — the on-demand pre-trade analysis layer.

Confirms it composes the existing engine intelligence into one verdict with a
five-category score, a confidence level, a decision, and a full risk analysis
(including margin / liquidation under leverage), and that the trader profile
distils strengths / weaknesses from the memory insights.
"""
import math

from services import ai_intelligence as ai
from data.market_data import get_bars


def _bars(symbol="BTCUSDT", n=250, tf="1h"):
    bars, _ = get_bars(symbol, n=n, timeframe=tf)
    return bars


# ─────────────────────────── confidence levels ───────────────────────────
def test_confidence_levels_map_to_bands():
    assert ai.confidence_level(90) == "Very High"
    assert ai.confidence_level(72) == "High"
    assert ai.confidence_level(60) == "Medium"
    assert ai.confidence_level(45) == "Low"
    assert ai.confidence_level(10) == "Very Low"


# ─────────────────────────── analysis shape ───────────────────────────
def test_analyze_setup_returns_full_verdict():
    out = ai.analyze_setup(symbol="BTCUSDT", timeframe="1h", bars=_bars(), equity=10_000, risk_pct=0.01)
    assert out["decision"] in ("BUY", "SELL", "WAIT", "SKIP")
    assert 0 <= out["overall_score"] <= 100
    assert out["confidence_level"] in ("Very High", "High", "Medium", "Low", "Very Low")
    # five presentation categories, each out of 20
    cats = {c["category"] for c in out["score_breakdown"]}
    assert cats == {"Trend", "Market Structure", "Volume", "Risk Management", "Confirmation"}
    assert all(0 <= c["score"] <= 20 for c in out["score_breakdown"])
    assert isinstance(out["reasons"], list)
    assert isinstance(out["market_analysis"], dict)   # the full pre-trade read is included
    assert isinstance(out["checklist"], list)


def test_weak_setup_is_rejected_below_min_score():
    # a very high min score forces SKIP unless the setup is exceptional
    out = ai.analyze_setup(symbol="BTCUSDT", timeframe="1h", bars=_bars(), side="long",
                           equity=10_000, risk_pct=0.01, min_score=99)
    assert out["allowed"] is False
    assert out["decision"] in ("SKIP", "WAIT")


# ─────────────────────────── risk analysis ───────────────────────────
def test_risk_analysis_numbers_are_consistent():
    out = ai.analyze_setup(symbol="BTCUSDT", timeframe="1h", bars=_bars(), side="long",
                           equity=10_000, risk_pct=0.01, leverage=1.0)
    r = out["risk_analysis"]
    assert r is not None
    assert r["max_loss"] >= 0 and r["expected_profit"] >= 0
    # reward:risk target is ~2 by construction
    assert r["risk_reward"] >= 1.5
    # spot (1x) -> no liquidation price
    assert r["liquidation_price"] is None
    # risk % of equity should be ~ the configured per-trade risk (1%)
    assert 0.0 <= r["risk_pct"] <= 3.0


def test_leverage_produces_margin_and_liquidation():
    out = ai.analyze_setup(symbol="BTCUSDT", timeframe="1h", bars=_bars(), side="long",
                           equity=10_000, risk_pct=0.01, leverage=10.0)
    r = out["risk_analysis"]
    assert r["leverage"] == 10.0
    assert r["liquidation_price"] is not None
    # long liquidation sits BELOW entry
    assert r["liquidation_price"] < out["setup"]["entry"]
    # margin used is notional / leverage
    assert math.isclose(r["margin_used"], round(r["notional"] / 10.0, 2), abs_tol=0.02)


def test_short_liquidation_is_above_entry():
    out = ai.analyze_setup(symbol="ETHUSDT", timeframe="1h", bars=_bars("ETHUSDT"), side="short",
                           equity=10_000, risk_pct=0.01, leverage=5.0)
    if out["setup"]:
        assert out["risk_analysis"]["liquidation_price"] > out["setup"]["entry"]


def test_excessive_risk_warns():
    # 25% per-trade risk is way over a sane limit -> excessive flag + warning
    out = ai.analyze_setup(symbol="BTCUSDT", timeframe="1h", bars=_bars(), side="long",
                           equity=10_000, risk_pct=0.25)
    assert out["risk_analysis"]["excessive"] is True
    assert out["risk_analysis"]["warning"]


# ─────────────────────────── trader profile ───────────────────────────
def test_trader_profile_from_insights():
    insights = {
        "sample": 40,
        "overall": {"win_rate": 58.0, "expectancy": 0.35, "trades": 40},
        "best_session": {"name": "London", "expectancy": 0.6},
        "worst_session": {"name": "Asia", "expectancy": -0.3},
        "by_symbol": [{"name": "BTCUSDT", "expectancy": 0.5}, {"name": "XRPUSDT", "expectancy": -0.4}],
        "by_strategy": [{"name": "Decision Brain", "expectancy": 0.4}],
        "winning_patterns": [{"name": "BOS + order block"}],
        "mistakes": [{"mistake": "entered before confirmation", "count": 6}],
        "avg_hold_seconds": 3600, "sharpe_ratio": 1.2,
    }
    prof = ai.trader_profile(insights)
    assert prof["ready"] is True and prof["sample"] == 40
    assert any("London" in s for s in prof["strengths"])
    assert any("Asia" in w for w in prof["weaknesses"])
    assert any("confirmation" in w.lower() for w in prof["weaknesses"])


def test_trader_profile_small_sample_is_honest():
    prof = ai.trader_profile({"sample": 2, "overall": {"trades": 2}})
    assert prof["ready"] is False
    assert "firms up" in prof["note"]


# ─────────────────────────── confidence accuracy ───────────────────────────
def _mem(score, result, rr=1.0, pnl=10.0):
    return {"brain_score": score, "result": result, "actual_rr": rr, "pnl": pnl}


def test_confidence_accuracy_detects_good_calibration():
    # high-confidence trades mostly win; low-confidence mostly lose -> calibrated
    rows = ([_mem(90, "win") for _ in range(8)] + [_mem(88, "loss") for _ in range(2)]
            + [_mem(30, "loss") for _ in range(8)] + [_mem(35, "win") for _ in range(2)])
    out = ai.confidence_accuracy(rows)
    assert out["ready"] is True
    assert out["calibrated"] is True
    assert out["high_conf_win_rate"] > out["low_conf_win_rate"]
    assert out["spread_pts"] > 0
    # buckets are ordered strongest-first and cover the graded trades
    assert [b["level"] for b in out["by_confidence"]][0] == "Very High"
    assert sum(b["trades"] for b in out["by_confidence"]) == 20


def test_confidence_accuracy_flags_miscalibration():
    # high-confidence trades LOSE; low-confidence win -> miscalibrated
    rows = ([_mem(90, "loss") for _ in range(8)] + [_mem(30, "win") for _ in range(8)]
            + [_mem(30, "win") for _ in range(4)])
    out = ai.confidence_accuracy(rows)
    assert out["calibrated"] is False
    assert "Miscalibrated" in out["verdict"]


def test_confidence_accuracy_small_sample_is_honest():
    out = ai.confidence_accuracy([_mem(90, "win"), _mem(30, "loss")])
    assert out["ready"] is False
    assert "firms up" in out["verdict"]


# ─────────────────────────── AI alert feed ───────────────────────────
def test_alerts_strong_and_weak_setups():
    analyses = [
        {"symbol": "BTCUSDT", "available": True, "allowed": True, "decision": "BUY",
         "overall_score": 88, "confidence_level": "Very High", "risk_analysis": {}},
        {"symbol": "XRPUSDT", "available": True, "allowed": False, "decision": "SKIP",
         "overall_score": 40, "confidence_level": "Low", "risk_analysis": {}},
    ]
    alerts = ai.evaluate_alerts(analyses, {}, min_score=60)
    types = {a["type"] for a in alerts}
    assert "strong_setup" in types and "weak_setup" in types


def test_alerts_risk_and_halt_and_session():
    analyses = [{"symbol": "BTCUSDT", "available": True, "allowed": True, "decision": "BUY",
                 "overall_score": 80, "risk_analysis": {"excessive": True, "warning": "too big"}}]
    risk = {"exposure_pct": 1.5, "exposure_limit_pct": 1.0, "auto_halted": True,
            "halt_reason": "max daily loss hit"}
    alerts = ai.evaluate_alerts(analyses, risk, in_session=False, session_window="13:00–20:00 UTC")
    types = {a["type"] for a in alerts}
    assert {"risk_exceeds_limit", "max_daily_loss", "outside_session"} <= types
    # most-severe first
    assert alerts[0]["severity"] == "critical"


def test_alerts_high_impact_news_only_when_present():
    assert not any(a["type"] == "news" for a in ai.evaluate_alerts([], {}))
    withnews = ai.evaluate_alerts([], {}, high_impact_news=[{"title": "FOMC in 30m"}])
    assert any(a["type"] == "news" and "FOMC" in a["detail"] for a in withnews)


# ─────────────────────────── live market insights ───────────────────────────
def test_market_insights_from_reads():
    reads = [{"symbol": "BTCUSDT", "ma": {
        "available": True, "bias": "Bullish", "trend": {"strength_label": "strong"},
        "structure": {"break_of_structure": "bullish", "change_of_character": False},
        "volume": {"label": "above average"}, "volatility": {"label": "normal"},
        "liquidity": {"sweep": "bullish sweep @ 100"}}}]
    ins = ai.market_insights(reads)
    texts = " ".join(i["text"] for i in ins)
    assert "BTC is trending strongly" in texts
    assert "Liquidity sweep detected on BTC" in texts
    assert "volume is rising" in texts


def test_market_insights_reversal_and_volatility():
    reads = [{"symbol": "ETH/USDT", "ma": {
        "available": True, "bias": "Neutral", "trend": {"strength_label": "weak"},
        "structure": {"break_of_structure": "none", "change_of_character": True},
        "volume": {"label": "below average"}, "volatility": {"label": "high"},
        "liquidity": {"sweep": "none detected"}}}]
    kinds = {i["kind"] for i in ai.market_insights(reads)}
    assert {"reversal", "volume", "volatility"} <= kinds


def test_market_insights_empty_when_no_data():
    assert ai.market_insights([{"symbol": "BTCUSDT", "ma": {"available": False}}]) == []


# ─────────────────────────── daily coach ───────────────────────────
def test_daily_coach_summary():
    insights = {
        "overall": {"trades": 7, "win_rate": 57.0, "expectancy_r": 0.2},
        "mistakes": [{"mistake": "entered before confirmation", "count": 4}],
        "coaching": [{"statement": "Wait for BOS before entering.", "stage": "solid"}],
        "best_session": {"name": "London"}, "worst_setup": {"name": "counter-trend fade"},
        "avg_hold_seconds": 5400,
    }
    c = ai.daily_coach(insights)
    assert c["trades"] == 7 and c["win_rate"] == 57.0
    assert c["main_mistake"] == "entered before confirmation"
    assert c["suggestion"] == "Wait for BOS before entering."
    assert c["risk_discipline"] == "Excellent"        # no risk-type mistake
    assert "7 trades" in c["headline"]


def test_daily_coach_flags_risk_discipline():
    c = ai.daily_coach({"overall": {"trades": 5, "win_rate": 40},
                        "mistakes": [{"mistake": "moved stop loss against the trade", "count": 3}]})
    assert c["risk_discipline"] == "Needs work"


def test_daily_coach_no_trades_is_honest():
    c = ai.daily_coach({})
    assert c["ready"] is False and c["trades"] == 0
    assert "No closed trades" in c["headline"]
