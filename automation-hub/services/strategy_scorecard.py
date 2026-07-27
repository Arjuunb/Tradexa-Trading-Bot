"""Strategy scorecard — ratings and deep analytics computed from a real backtest.

Every score below is a documented, deterministic formula over numbers the
backtest actually produced. Nothing is modelled, smoothed or guessed: where the
sample cannot support a score (too few months, too few trades) the value is
``None`` and the UI shows "not enough data" rather than a confident-looking
number built on three trades.

Scores are 0-100 and all point the same way: HIGHER IS BETTER, including the
risk score (100 = well controlled).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import pstdev
from typing import Any, Optional

_MIN_TRADES_FOR_SCORE = 10
_MIN_MONTHS = 3
_DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _dt(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _rs(trades: list[dict]) -> list[float]:
    return [float(t.get("r") or 0.0) for t in trades]


def _bucket(rows: list[dict]) -> dict:
    rs = _rs(rows)
    wins = sum(1 for r in rs if r > 0)
    return {"trades": len(rows), "net_r": round(sum(rs), 2),
            "avg_r": round(sum(rs) / len(rs), 3) if rs else 0.0,
            "win_rate": round(100 * wins / len(rs), 1) if rs else 0.0}


# ----------------------------------------------------------------- analytics

def gross_split(trades: list[dict]) -> dict:
    """Gross profit / gross loss in R — the two halves behind profit factor."""
    rs = _rs(trades)
    gp = round(sum(r for r in rs if r > 0), 2)
    gl = round(sum(r for r in rs if r < 0), 2)
    return {"gross_profit_r": gp, "gross_loss_r": gl,
            "net_r": round(gp + gl, 2)}


def sortino(trades: list[dict]) -> Optional[float]:
    """Sortino = mean(R) / downside deviation. None when there is no downside
    (undefined, not "infinite") or the sample is too small to mean anything."""
    rs = _rs(trades)
    if len(rs) < _MIN_TRADES_FOR_SCORE:
        return None
    downside = [r for r in rs if r < 0]
    if not downside:
        return None
    dd = pstdev(downside) if len(downside) > 1 else abs(downside[0])
    if not dd:
        return None
    return round((sum(rs) / len(rs)) / dd, 3)


def day_of_week_breakdown(trades: list[dict]) -> list[dict]:
    groups: dict[int, list[dict]] = defaultdict(list)
    for t in trades:
        d = _dt(t.get("entry_time"))
        if d is not None:
            groups[d.weekday()].append(t)
    return sorted(({"day": _DOW[k], **_bucket(v)} for k, v in groups.items()),
                  key=lambda x: x["net_r"], reverse=True)


def monthly_breakdown(trades: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        d = _dt(t.get("entry_time"))
        if d is not None:
            groups[f"{d.year}-{d.month:02d}"].append(t)
    return [{"month": k, **_bucket(groups[k])} for k in sorted(groups)]


def recovery_profile(results: dict) -> Optional[dict]:
    """How the equity curve behaved around its worst drawdown: how deep, and how
    many trades it took to make a new high afterwards (None if never recovered)."""
    curve = [p.get("equity") for p in (results.get("equity_curve") or [])
             if isinstance(p.get("equity"), (int, float))]
    if len(curve) < 3:
        return None
    peak, worst, worst_i = curve[0], 0.0, 0
    for i, e in enumerate(curve):
        peak = max(peak, e)
        dd = peak - e
        if dd > worst:
            worst, worst_i = dd, i
    if worst <= 0:
        return {"max_drawdown_abs": 0.0, "trough_index": 0,
                "trades_to_recover": 0, "recovered": True}
    prior_peak = max(curve[:worst_i + 1])
    after = curve[worst_i:]
    rec = next((j for j, e in enumerate(after) if e >= prior_peak), None)
    return {"max_drawdown_abs": round(worst, 2), "trough_index": worst_i,
            "trades_to_recover": rec, "recovered": rec is not None}


# -------------------------------------------------------------------- scores

def _profitability_score(pf: Optional[float], exp: Optional[float]) -> Optional[float]:
    """Profit factor 1.0 -> 0, 2.5 -> 100 (linear), nudged by expectancy sign."""
    if not isinstance(pf, (int, float)):
        return None
    base = _clamp((pf - 1.0) / 1.5 * 100.0)
    if isinstance(exp, (int, float)) and exp <= 0:
        base = min(base, 40.0)          # a negative average trade caps it
    return round(base, 1)


def _risk_score(results: dict) -> Optional[float]:
    """Higher = better controlled. Blends return-vs-drawdown with the worst
    losing streak. Both come straight from the backtest."""
    net, dd = results.get("net_r"), results.get("max_drawdown_r")
    streak = results.get("max_consecutive_losses")
    if not isinstance(net, (int, float)) or not isinstance(dd, (int, float)):
        return None
    ratio = abs(net / dd) if dd else (2.0 if net > 0 else 0.0)
    ratio_score = _clamp(ratio / 3.0 * 100.0)          # 3:1 return:DD -> 100
    streak_score = 100.0
    if isinstance(streak, (int, float)) and streak > 0:
        streak_score = _clamp(100.0 - (streak - 3) * 12.0)  # 3 in a row is fine
    return round(0.65 * ratio_score + 0.35 * streak_score, 1)


def _consistency_score(months: list[dict]) -> Optional[float]:
    """Share of profitable months. None below _MIN_MONTHS — three good months is
    not evidence of consistency."""
    if len(months) < _MIN_MONTHS:
        return None
    good = sum(1 for m in months if m["net_r"] > 0)
    return round(100.0 * good / len(months), 1)


def _stability_score(results: dict) -> Optional[float]:
    """How smoothly equity grew: the fraction of the curve spent at or near its
    running peak. A curve that spends most of its life underwater scores low."""
    curve = [p.get("equity") for p in (results.get("equity_curve") or [])
             if isinstance(p.get("equity"), (int, float))]
    if len(curve) < 5:
        return None
    peak, near = curve[0], 0
    for e in curve:
        peak = max(peak, e)
        if peak <= 0:
            continue
        if (peak - e) / peak <= 0.05:      # within 5% of the high-water mark
            near += 1
    return round(100.0 * near / len(curve), 1)


def _confidence_score(results: dict) -> float:
    """How much the numbers above deserve trust: sample size + time span.
    This is explicitly a measure of EVIDENCE, not of profitability."""
    n = int(results.get("total_trades") or 0)
    days = int(results.get("span_days") or 0)
    n_score = _clamp(n / 100.0 * 100.0)          # 100 trades -> full marks
    d_score = _clamp(days / 365.0 * 100.0)       # a year -> full marks
    return round(0.6 * n_score + 0.4 * d_score, 1)


def _rating(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    for cut, letter in ((85, "A"), (70, "B"), (55, "C"), (40, "D"), (25, "E")):
        if score >= cut:
            return letter
    return "F"


def scorecard(spec: dict, results: Optional[dict]) -> dict:
    """The full scorecard. ``available: False`` when there is no backtest —
    a rating is never produced from the spec alone."""
    if not results or not results.get("trades"):
        return {"available": False,
                "note": "No completed backtest trades. Run a backtest first — every "
                        "score here is computed from real results."}

    trades = list(results.get("trades") or [])
    n = len(trades)
    months = monthly_breakdown(trades)

    prof = _profitability_score(results.get("profit_factor"), results.get("expectancy_r"))
    risk = _risk_score(results)
    cons = _consistency_score(months)
    stab = _stability_score(results)
    conf = _confidence_score(results)

    parts = [(prof, 0.40), (risk, 0.30), (cons, 0.15), (stab, 0.15)]
    have = [(v, w) for v, w in parts if v is not None]
    overall = (round(sum(v * w for v, w in have) / sum(w for _, w in have), 1)
               if have and n >= _MIN_TRADES_FOR_SCORE else None)

    summary = _summary(overall, conf, n, results)

    return {
        "available": True,
        "rating": _rating(overall),
        "strategy_score": overall,
        "scores": {"profitability": prof, "risk": risk, "consistency": cons,
                   "stability": stab, "confidence": conf},
        "score_basis": {
            "profitability": "profit factor scaled 1.0->0, 2.5->100; capped at 40 if expectancy <= 0",
            "risk": "65% |net R / max drawdown R| (3:1 -> 100) + 35% worst losing streak",
            "consistency": f"share of profitable months (needs >= {_MIN_MONTHS} months)",
            "stability": "share of the equity curve within 5% of its running peak",
            "confidence": "60% sample size (100 trades = full) + 40% span (365 days = full)",
            "overall": "weighted: profitability 40%, risk 30%, consistency 15%, stability 15%",
        },
        "summary": summary,
        "performance": {
            **gross_split(trades),
            "win_rate": results.get("win_rate"), "profit_factor": results.get("profit_factor"),
            "sharpe": results.get("sharpe"), "sortino": sortino(trades),
            "max_drawdown_r": results.get("max_drawdown_r"),
            "max_drawdown_pct": results.get("max_drawdown_pct"),
            "avg_rr": results.get("avg_rr"), "expectancy_r": results.get("expectancy_r"),
            "avg_hold_bars": results.get("avg_hold_bars"),
            "total_trades": n, "span_days": results.get("span_days"),
            "end_balance": results.get("end_balance"), "net_pct": results.get("net_pct"),
        },
        "monthly": months,
        "day_of_week": day_of_week_breakdown(trades),
        "recovery": recovery_profile(results),
        "equity_curve": results.get("equity_curve") or [],
    }


def _summary(overall: Optional[float], conf: float, n: int, results: dict) -> str:
    if overall is None:
        return (f"Only {n} trades — too few to rate. Widen the backtest window or "
                "loosen the entry rules to build a meaningful sample.")
    pf = results.get("profit_factor")
    verdict = ("shows a solid edge" if overall >= 70 else
               "shows a modest edge" if overall >= 55 else
               "is around break-even" if overall >= 40 else
               "does not show an edge")
    trust = ("well-evidenced" if conf >= 70 else
             "provisional" if conf >= 40 else "weakly evidenced")
    return (f"Over {n} trades this strategy {verdict} "
            f"(profit factor {pf}). The result is {trust} "
            f"— confidence {conf}/100 from sample size and time span.")
