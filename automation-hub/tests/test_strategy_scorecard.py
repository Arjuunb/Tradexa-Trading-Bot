"""Strategy scorecard + optimisation suggestions.

Contract: scores are deterministic formulas over real backtest numbers; a score
is None (not a guess) when the sample can't support it; every suggestion is
derived from a measurable weakness and is never auto-applied.
"""
import pytest

from services import strategy_optimizer as opt
from services import strategy_scorecard as sc


def _t(r, hour=9, day=4, month=3, reason="Stop loss hit", side="long", regime=None):
    d = {"r": r, "side": side, "exit_reason": reason, "bars_held": 10,
         "result": "win" if r > 0 else "loss",
         "entry_time": f"2025-{month:02d}-{day:02d}T{hour:02d}:00:00+00:00"}
    if regime:
        d["regime"] = regime
    return d


def _results(trades, **kw):
    base = {"trades": trades, "total_trades": len(trades),
            "equity_curve": [{"t": None, "equity": 10000 + i * 10}
                             for i in range(len(trades) + 1)]}
    base.update(kw)
    return base


# ------------------------------------------------------------------- analytics

def test_gross_split_matches_net():
    g = sc.gross_split([_t(2.0), _t(-1.0), _t(3.0)])
    assert g["gross_profit_r"] == 5.0 and g["gross_loss_r"] == -1.0
    assert g["net_r"] == 4.0


def test_sortino_is_none_without_downside_or_sample():
    assert sc.sortino([_t(1.0) for _ in range(20)]) is None       # no losers
    assert sc.sortino([_t(1.0), _t(-1.0)]) is None                # too few trades


def test_sortino_computes_with_downside():
    trades = [_t(2.0) for _ in range(15)] + [_t(-1.0), _t(-2.0), _t(-0.5)]
    assert isinstance(sc.sortino(trades), float)


def test_day_of_week_and_monthly_breakdowns():
    trades = [_t(2.0, day=4, month=3), _t(-1.0, day=5, month=4)]
    dow = sc.day_of_week_breakdown(trades)
    assert {d["day"] for d in dow} == {"Tuesday", "Saturday"}     # 2025-03-04 / 2025-04-05
    months = sc.monthly_breakdown(trades)
    assert [m["month"] for m in months] == ["2025-03", "2025-04"]


def test_recovery_profile_detects_drawdown_and_recovery():
    res = {"equity_curve": [{"equity": e} for e in
                            [100, 120, 90, 95, 130]]}
    rec = sc.recovery_profile(res)
    assert rec["max_drawdown_abs"] == 30.0
    assert rec["recovered"] is True and rec["trades_to_recover"] is not None


def test_recovery_profile_reports_unrecovered():
    res = {"equity_curve": [{"equity": e} for e in [100, 150, 80, 85, 90]]}
    assert sc.recovery_profile(res)["recovered"] is False


# --------------------------------------------------------------------- scores

def test_no_backtest_means_no_rating():
    out = sc.scorecard({}, None)
    assert out["available"] is False and "Run a backtest first" in out["note"]


def test_small_sample_yields_no_overall_score():
    """Five trades must not produce a confident-looking A-F rating."""
    out = sc.scorecard({}, _results([_t(2.0) for _ in range(5)], profit_factor=3.0))
    assert out["available"] is True
    assert out["strategy_score"] is None and out["rating"] is None
    assert "too few to rate" in out["summary"]


def test_scores_and_rating_from_real_numbers():
    trades = [_t(2.0, month=m) for m in range(1, 7) for _ in range(4)] + \
             [_t(-1.0, month=m) for m in range(1, 7) for _ in range(2)]
    out = sc.scorecard({}, _results(trades, profit_factor=2.5, expectancy_r=0.6,
                                    net_r=36.0, max_drawdown_r=-6.0,
                                    max_consecutive_losses=3, span_days=200))
    assert out["rating"] in list("ABCDEF")
    assert 0 <= out["strategy_score"] <= 100
    assert out["scores"]["profitability"] == 100.0          # pf 2.5 -> full
    assert out["scores"]["consistency"] is not None          # 6 months of data
    # every score must be explained
    assert set(out["score_basis"]) >= {"profitability", "risk", "consistency", "overall"}


def test_negative_expectancy_caps_profitability():
    out = sc.scorecard({}, _results([_t(1.0) for _ in range(20)],
                                    profit_factor=2.0, expectancy_r=-0.2))
    assert out["scores"]["profitability"] <= 40.0


def test_consistency_is_none_below_three_months():
    out = sc.scorecard({}, _results([_t(1.0, month=3) for _ in range(20)],
                                    profit_factor=2.0))
    assert out["scores"]["consistency"] is None


def test_confidence_reflects_sample_and_span_not_profit():
    lo = sc.scorecard({}, _results([_t(5.0) for _ in range(12)], profit_factor=9.0,
                                   span_days=5))["scores"]["confidence"]
    hi = sc.scorecard({}, _results([_t(0.1) for _ in range(120)], profit_factor=1.1,
                                   span_days=400))["scores"]["confidence"]
    assert hi > lo, "confidence must track evidence, not profitability"


# --------------------------------------------------------------- suggestions

def test_no_backtest_means_no_suggestions():
    assert opt.suggestions({}, None) == []


def test_losing_side_produces_a_restrict_side_patch():
    trades = [_t(2.0) for _ in range(10)] + [_t(-1.0, side="short") for _ in range(10)]
    s = opt.suggestions({}, _results(trades, long_net_r=20.0, short_net_r=-10.0,
                                     long_trades=10, short_trades=10))
    pick = next(x for x in s if x["id"] == "restrict_side")
    assert pick["patch"] == {"side": "long"}
    assert pick["evidence"] and pick["reason"] and pick["tradeoffs"]
    assert pick["confidence"] in ("high", "medium", "low")


def test_high_drawdown_suggests_smaller_risk():
    s = opt.suggestions({"risk_per_trade_pct": 0.02},
                        _results([_t(1.0) for _ in range(20)],
                                 net_r=10.0, max_drawdown_r=-9.0))
    pick = next(x for x in s if x["id"] == "reduce_risk")
    assert pick["patch"]["risk_per_trade_pct"] == 0.01


def test_long_losing_streak_suggests_a_guard():
    s = opt.suggestions({}, _results([_t(1.0) for _ in range(20)],
                                     max_consecutive_losses=8))
    pick = next(x for x in s if x["id"] == "streak_guard")
    assert pick["patch"]["max_consecutive_losses"] == 6


def test_every_suggestion_is_fully_justified():
    trades = [_t(2.0) for _ in range(10)] + [_t(-1.0, side="short") for _ in range(10)]
    s = opt.suggestions({"risk_per_trade_pct": 0.02},
                        _results(trades, long_net_r=20.0, short_net_r=-10.0,
                                 long_trades=10, short_trades=10,
                                 net_r=10.0, max_drawdown_r=-9.0))
    assert s, "expected suggestions from this data"
    for x in s:
        assert x["reason"] and x["expected_benefit"] and x["tradeoffs"]
        assert x["evidence"] and all(e["stat"] for e in x["evidence"])
        assert x["confidence"] in ("high", "medium", "low")


def test_healthy_strategy_gets_no_padding():
    """No addressable weakness -> an empty list, not generic advice."""
    trades = [_t(2.0) for _ in range(30)]
    s = opt.suggestions({"risk_per_trade_pct": 0.01,
                         "stop": {"type": "atr"}, "target": {"type": "rr", "rr": 2}},
                        _results(trades, net_r=60.0, max_drawdown_r=-5.0,
                                 max_consecutive_losses=2, long_net_r=60.0,
                                 short_net_r=0.0, long_trades=30, short_trades=0,
                                 avg_rr=2.0))
    assert all(x["id"] != "reduce_risk" for x in s)


def test_apply_patch_never_mutates_the_original():
    spec = {"side": "long", "risk_per_trade_pct": 0.02}
    out = opt.apply_patch(spec, {"risk_per_trade_pct": 0.01})
    assert out["risk_per_trade_pct"] == 0.01
    assert spec["risk_per_trade_pct"] == 0.02, "the user's strategy must be untouched"


def test_compare_reports_deltas():
    c = opt.compare({"net_r": 10.0, "win_rate": 40.0},
                    {"net_r": 15.0, "win_rate": 45.0})
    by = {r["metric"]: r for r in c["rows"]}
    assert by["net_r"]["delta"] == 5.0 and by["win_rate"]["delta"] == 5.0


# --------------------------------- interactive insights: the affected trades

def test_suggestions_carry_the_real_trades_they_affect():
    """'Affected trades' must be the actual rows, not a count or a description —
    so a user can inspect what a change would really have removed."""
    trades = ([_t(2.0) for _ in range(10)]
              + [_t(-1.0, side="short") for _ in range(10)])
    s = opt.suggestions({}, _results(trades, long_net_r=20.0, short_net_r=-10.0,
                                     long_trades=10, short_trades=10))
    pick = next(x for x in s if x["id"] == "restrict_side")
    aff = pick["affected"]
    assert aff["count"] == 10                    # the ten short trades
    assert aff["net_r"] == -10.0                 # and their real net R
    assert aff["sample"], "expected example rows"
    for row in aff["sample"]:
        assert row["side"] == "short"
        assert "r" in row and "entry_time" in row


def test_every_suggestion_has_an_affected_block():
    trades = [_t(-1.0) for _ in range(20)]
    for x in opt.suggestions({"risk_per_trade_pct": 0.02},
                             _results(trades, net_r=-5.0, max_drawdown_r=-9.0,
                                      max_consecutive_losses=8)):
        assert "affected" in x and "count" in x["affected"]


def test_affected_sample_is_capped():
    trades = [_t(-1.0, side="short") for _ in range(60)] + [_t(2.0) for _ in range(10)]
    s = opt.suggestions({}, _results(trades, long_net_r=20.0, short_net_r=-60.0,
                                     long_trades=10, short_trades=60))
    pick = next(x for x in s if x["id"] == "restrict_side")
    assert pick["affected"]["count"] == 60          # full count reported
    assert len(pick["affected"]["sample"]) <= 12    # but the payload stays small
