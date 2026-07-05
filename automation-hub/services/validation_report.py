"""Daily paper-validation report (Phase 9).

A once-a-day digest of the paper-validation run, assembled entirely from REAL
stored data (closed trades, the skip log, risk/health events, Safety Center).
It never fabricates numbers and never unlocks live trading — every report ends
by restating that live remains locked.

'Improving vs weakening' is derived from the strategy-health recent-vs-previous
window comparison, which is itself computed from real closed trades.
"""
from __future__ import annotations


def _trend(recent: dict, previous: dict) -> dict:
    """Compare the recent trade window to the previous one on the metrics that
    matter. Returns a direction + the per-metric deltas (all real)."""
    keys = ("win_rate", "profit_factor", "expectancy")
    deltas = {}
    score = 0
    for k in keys:
        r = float(recent.get(k, 0) or 0)
        p = float(previous.get(k, 0) or 0)
        deltas[k] = round(r - p, 3)
        if deltas[k] > 0:
            score += 1
        elif deltas[k] < 0:
            score -= 1
    if not previous or previous.get("n", 0) == 0:
        direction = "not-enough-history"
    elif score > 0:
        direction = "improving"
    elif score < 0:
        direction = "weakening"
    else:
        direction = "stable"
    return {"direction": direction, "deltas": deltas}


def build_daily_report(
    *,
    validation: dict,          # from build_paper_validation
    recent: dict,              # strategy_health recent window
    previous: dict,            # strategy_health previous window
    risk_events: list[dict],   # recent risk-category skips / halts (real)
    health_errors: list[dict], # from /health/bot errors
    day_index: int | None = None,
) -> dict:
    m = validation.get("metrics", {})
    trend = _trend(recent, previous)
    lr = validation.get("live_review", {})
    return {
        "day_index": day_index,
        "closed_trades": {
            "count": validation.get("sample_size", 0),
            "min_review": validation.get("min_review"),
            "min_evidence": validation.get("min_evidence"),
            "win_rate": m.get("win_rate"),
            "profit_factor": m.get("profit_factor"),
            "expectancy": m.get("expectancy"),
            "avg_rr": m.get("avg_rr"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "sharpe_ratio": m.get("sharpe_ratio"),
            "sortino_ratio": m.get("sortino_ratio"),
        },
        "best_worst": {
            "best_symbol": validation.get("best_symbol"),
            "worst_symbol": validation.get("worst_symbol"),
            "best_strategy": validation.get("best_strategy"),
            "worst_strategy": validation.get("worst_strategy"),
        },
        "skipped": {
            "total": validation.get("skipped_total", 0),
            "by_category": validation.get("skipped_by_category", []),
        },
        "risk_events": risk_events,
        "health_errors": health_errors,
        "trend": trend,                       # improving / weakening / stable
        "live_review": {
            "eligible": lr.get("eligible", False),
            "stage": lr.get("stage"),
            "reasons": lr.get("reasons", []),
        },
        "safety": validation.get("safety", {}),
        # invariant restated on every report — live is never unlocked by this
        "live_trading": "LOCKED",
        "note": ("Paper mode only. This report never unlocks live trading; a human "
                 "review is required before any live pre-flight."),
    }
