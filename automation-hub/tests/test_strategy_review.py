"""Evidence-based strategy review (slice 4).

Contract: every conclusion is computed from real backtest trades and carries the
statistic behind it; anything the data cannot support is declared, not guessed.
"""
import pytest

from services.strategy_review import (
    bars_for_range, evidence_review, exit_reason_breakdown, session_breakdown,
)


def _trade(r, hour, reason="Stop loss hit", bars=10, side="long"):
    return {"r": r, "side": side, "exit_reason": reason, "bars_held": bars,
            "result": "win" if r > 0 else "loss",
            "entry_time": f"2025-03-04T{hour:02d}:00:00+00:00"}


# ------------------------------------------------------------- no-backtest path

def test_review_without_results_is_honest_not_invented():
    out = evidence_review({"name": "x"}, None)
    assert out["available"] is False
    assert "Run a backtest first" in out["note"]
    assert out["strengths"] == [] and out["weaknesses"] == []


def test_review_with_empty_trades_is_also_unavailable():
    assert evidence_review({}, {"trades": []})["available"] is False


# --------------------------------------------------------- every claim has a stat

def test_every_finding_carries_its_supporting_statistic():
    trades = [_trade(2.0, 9) for _ in range(20)] + [_trade(-1.0, 9) for _ in range(10)]
    out = evidence_review({"risk_per_trade_pct": 0.01},
                          {"trades": trades, "profit_factor": 2.4, "expectancy_r": 0.5,
                           "win_rate": 66.0, "max_drawdown_r": -3.0, "net_r": 30.0})
    assert out["available"] is True
    for f in out["strengths"] + out["weaknesses"]:
        assert f["claim"] and f["stat"] and f["value"] is not None


def test_weak_edge_is_called_out():
    trades = [_trade(-1.0, 9) for _ in range(30)]
    out = evidence_review({}, {"trades": trades, "profit_factor": 0.6,
                               "expectancy_r": -0.4, "win_rate": 20.0})
    claims = " ".join(f["claim"] for f in out["weaknesses"])
    assert "no edge" in claims or "loses money" in claims
    assert "Low hit-rate" in claims


def test_small_sample_is_flagged():
    out = evidence_review({}, {"trades": [_trade(1.0, 9) for _ in range(8)]})
    assert any("Small sample" in w["claim"] for w in out["weaknesses"])


# --------------------------------------------------------------- session buckets

def test_session_breakdown_uses_real_entry_hours():
    # 8-16 UTC is London in the app's presets; 13-21 New York.
    trades = [_trade(2.0, 9) for _ in range(6)] + [_trade(-1.0, 3) for _ in range(6)]
    rows = session_breakdown(trades)
    assert rows, "expected at least one session bucket"
    assert rows[0]["net_r"] >= rows[-1]["net_r"]      # sorted best-first
    for r in rows:
        assert r["trades"] > 0 and "win_rate" in r


def test_best_session_requires_a_minimum_sample():
    """A single lucky trade in a session must not become a 'strength'."""
    out = evidence_review({}, {"trades": [_trade(5.0, 9)]})
    assert out["best_session"] is None


# ------------------------------------------------------------- losing patterns

def test_most_common_loss_is_grouped_by_real_exit_reason():
    trades = ([_trade(-1.0, 9, reason="Stop loss hit") for _ in range(12)]
              + [_trade(2.0, 9, reason="Take profit reached") for _ in range(6)])
    out = evidence_review({}, {"trades": trades})
    assert out["most_common_loss"]["exit_reason"] == "Stop loss hit"
    assert out["most_common_loss"]["trades"] == 12
    assert any("Most losses come from" in w["claim"] for w in out["weaknesses"])


def test_exit_reason_breakdown_covers_all_reasons():
    trades = [_trade(-1.0, 9, reason="A"), _trade(2.0, 9, reason="B")]
    reasons = {e["exit_reason"] for e in exit_reason_breakdown(trades)}
    assert reasons == {"A", "B"}


def test_hold_time_insight_flags_holding_losers_too_long():
    trades = ([_trade(2.0, 9, bars=5) for _ in range(6)]
              + [_trade(-1.0, 9, bars=40) for _ in range(6)])
    out = evidence_review({}, {"trades": trades})
    assert out["hold_times"]["avg_bars_losers"] > out["hold_times"]["avg_bars_winners"]
    assert any("held longer" in w["claim"] for w in out["weaknesses"])


# ------------------------------------------------ declared limits, not invented

def test_regime_breakdown_is_real_evidence_when_the_brain_tagged_trades():
    """The quality filter records the market regime at entry, so market-condition
    performance is measured, not inferred."""
    trades = ([_trade(2.0, 9) | {"regime": "Trending"} for _ in range(8)]
              + [_trade(-1.0, 9) | {"regime": "Ranging"} for _ in range(8)])
    out = evidence_review({}, {"trades": trades})
    assert out["best_regime"]["regime"] == "Trending"
    assert out["worst_regime"]["regime"] == "Ranging"
    assert any("Performs best in Trending" in s["claim"] for s in out["strengths"])
    assert any("Loses money in Ranging" in w["claim"] for w in out["weaknesses"])
    # ...and it is no longer listed as un-answerable
    assert not any("market conditions" in q["question"].lower()
                   for q in out["not_derivable"])


def test_regime_verdict_needs_a_minimum_sample():
    out = evidence_review({}, {"trades": [_trade(5.0, 9) | {"regime": "Trending"}]})
    assert out["best_regime"] is None


def test_missing_regime_tags_are_declared_with_the_reason():
    """With the quality filter off, trades carry no regime — say so and explain
    how to get it, rather than inferring conditions from price alone."""
    out = evidence_review({}, {"trades": [_trade(1.0, 9) for _ in range(10)]})
    qs = " ".join(q["question"] for q in out["not_derivable"])
    assert "market conditions" in qs.lower()
    assert any("quality filter" in q["why"] for q in out["not_derivable"])


def test_asset_ranking_is_always_declared_unanswerable():
    """A spec runs on ONE symbol, so this stays un-answerable regardless."""
    trades = [_trade(1.0, 9) | {"regime": "Trending"} for _ in range(10)]
    out = evidence_review({}, {"trades": trades})
    qs = " ".join(q["question"] for q in out["not_derivable"])
    assert "profitable asset" in qs.lower()
    for q in out["not_derivable"]:
        assert q["why"]


# ------------------------------------------------------------------ date ranges

def test_bars_for_range_respects_the_timeframe():
    """A '1Y' window must mean a year on EVERY timeframe, not a fixed bar count."""
    assert bars_for_range("4h", "1Y") == 365 * 6
    assert bars_for_range("1h", "1Y") == 365 * 24
    assert bars_for_range("1d", "1Y") == 365
    assert bars_for_range("15m", "3M") == 90 * 96


def test_bars_for_range_is_clamped_and_defaults_sanely():
    assert bars_for_range("5m", "5Y") == 10000        # capped
    assert bars_for_range("4h", "") == 3000           # unknown range -> default
    assert bars_for_range("4h", "nonsense") == 3000
    assert bars_for_range("1w", "3M") >= 300          # floor
