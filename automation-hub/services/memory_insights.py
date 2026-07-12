"""Nightly pattern recognition + data-driven coaching over the trade memory.

Every number here is computed from the REAL stored trades — no invented
percentages. Coaching statements are sample-gated: a claim like "you perform
27% better during the London session" is only emitted when the underlying
buckets are large enough to mean anything; below the bar we downgrade to an
"early signal" or stay silent. This mirrors the evolution-memory staging used
elsewhere (early-signal < 10, evidence ≥ 30).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

from services.performance import _risk_adjusted

EARLY_SIGNAL_MAX = 10      # below this a bucket is an early signal only
EVIDENCE_MIN = 30          # at/above this a bucket is strong evidence
_MIN_BUCKET = 5            # never report a breakdown row below this many trades


def _bucket_stats(rows: list[dict]) -> dict:
    """Win rate / expectancy / avg-RR / pnl for a set of memory rows."""
    n = len(rows)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "expectancy": 0.0,
                "avg_rr": 0.0, "pnl": 0.0}
    wins = sum(1 for r in rows if (r.get("pnl") or 0) > 0)
    pnl = sum((r.get("pnl") or 0) for r in rows)
    rrs = [r.get("actual_rr") for r in rows if r.get("actual_rr") is not None]
    return {
        "trades": n,
        "win_rate": round(100 * wins / n, 1),
        "expectancy": round(pnl / n, 3),
        "avg_rr": round(sum(rrs) / len(rrs), 3) if rrs else 0.0,
        "pnl": round(pnl, 2),
    }


def _group(rows: list[dict], key: str) -> list[dict]:
    buckets: dict = defaultdict(list)
    for r in rows:
        k = r.get(key)
        if k:
            buckets[k].append(r)
    out = [{key: k, **_bucket_stats(v)} for k, v in buckets.items()]
    out.sort(key=lambda d: d["expectancy"], reverse=True)
    return out


def build_review(rows: list[dict], starting_balance: float = 10000.0) -> dict:
    """Full pattern-recognition report over a set of closed-trade memories."""
    rows = [r for r in rows if r.get("result") in ("win", "loss", "breakeven")]
    n = len(rows)
    overall = _bucket_stats(rows)
    rrs = [r.get("actual_rr") for r in rows if r.get("actual_rr") is not None]
    risk_adj = _risk_adjusted(rrs)

    # equity / drawdown from the memory pnl sequence (chronological)
    chrono = sorted(rows, key=lambda r: r.get("closed_at") or "")
    equity = peak = starting_balance
    max_dd = 0.0
    for r in chrono:
        equity += (r.get("pnl") or 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    by_symbol = [b for b in _group(rows, "symbol") if b["trades"] >= 1]
    by_strategy = _group(rows, "strategy")
    by_session = [b for b in _group(rows, "session") if b["trades"] >= 1]
    by_weekday = _group(rows, "weekday")
    by_setup = _group(rows, "grade")

    durations = [r.get("duration_s") for r in rows if r.get("duration_s") is not None]
    avg_hold = round(sum(durations) / len(durations), 0) if durations else None

    best_setup = max(by_setup, key=lambda b: b["expectancy"], default=None)
    worst_setup = min(by_setup, key=lambda b: b["expectancy"], default=None)
    best_session = max((b for b in by_session if b["trades"] >= _MIN_BUCKET),
                       key=lambda b: b["expectancy"], default=None)
    worst_session = min((b for b in by_session if b["trades"] >= _MIN_BUCKET),
                        key=lambda b: b["expectancy"], default=None)

    return {
        "sample": n,
        "overall": overall,
        "risk_adjusted": risk_adj,
        "sharpe_ratio": risk_adj["sharpe_ratio"],
        "sortino_ratio": risk_adj["sortino_ratio"],
        "max_drawdown_abs": round(max_dd, 2),
        "avg_hold_seconds": avg_hold,
        "by_symbol": by_symbol,
        "by_strategy": by_strategy,
        "by_session": by_session,
        "by_weekday": by_weekday,
        "by_setup_grade": by_setup,
        "best_setup": best_setup,
        "worst_setup": worst_setup,
        "best_session": best_session,
        "worst_session": worst_session,
        "mistakes": _mistake_library(rows),
        "winning_patterns": [b for b in by_setup if b["expectancy"] > 0 and b["trades"] >= _MIN_BUCKET],
        "coaching": coaching_insights(rows),
        "evidence_note": (f"{n} closed trades. "
                          + ("Strong sample." if n >= EVIDENCE_MIN
                             else "Early sample — treat breakdowns as signals, not proof."
                             if n < EARLY_SIGNAL_MAX else "Building evidence.")),
    }


def _mistake_library(rows: list[dict]) -> list[dict]:
    """Aggregate the recorded mistakes into a frequency-ranked library."""
    counts: dict = defaultdict(lambda: {"count": 0, "loss": 0.0, "examples": []})
    for r in rows:
        m = ((r.get("sections", {}) or {}).get("trade_outcome", {}) or {}).get("mistakes")
        if not m or str(m).startswith("None"):
            continue
        c = counts[m]
        c["count"] += 1
        c["loss"] += min(0.0, r.get("pnl") or 0)
        if len(c["examples"]) < 3:
            c["examples"].append(r.get("trade_id"))
    lib = [{"mistake": k, "count": v["count"], "loss_attributed": round(v["loss"], 2),
            "examples": v["examples"], "repeated": v["count"] >= 2}
           for k, v in counts.items()]
    lib.sort(key=lambda d: d["count"], reverse=True)
    return lib


def coaching_insights(rows: list[dict]) -> list[dict]:
    """Data-driven coaching, sample-gated. Each statement carries the real
    numbers behind it and a confidence stage; nothing is emitted on thin data
    that could read as a fabricated edge."""
    out: list[dict] = []
    n = len(rows)
    if n < _MIN_BUCKET:
        return [{"statement": f"Only {n} closed trades so far — keep trading to unlock "
                              "session/weekday/setup coaching (needs at least "
                              f"{_MIN_BUCKET}).", "stage": "insufficient-data", "metric": None}]

    overall_exp = _bucket_stats(rows)["expectancy"]

    # Session edge vs overall
    for b in _group(rows, "session"):
        if b["trades"] < _MIN_BUCKET:
            continue
        delta = b["expectancy"] - overall_exp
        if abs(delta) < 1e-9 or overall_exp == 0:
            continue
        pct = round(100 * delta / abs(overall_exp)) if overall_exp else None
        if pct is not None and abs(pct) >= 15:
            better = delta > 0
            out.append({
                "statement": (f"You perform {abs(pct)}% {'better' if better else 'worse'} during the "
                              f"{b['session']} session ({b['expectancy']:+.3f}R vs {overall_exp:+.3f}R "
                              f"overall, {b['trades']} trades)."),
                "stage": _stage(b["trades"]),
                "metric": {"session": b["session"], **b},
            })

    # Weekday weakness
    for b in _group(rows, "weekday"):
        if b["trades"] < _MIN_BUCKET:
            continue
        if b["win_rate"] <= 35 and b["expectancy"] < 0:
            out.append({
                "statement": (f"{b['weekday']}s are a weak spot: {b['win_rate']}% win rate over "
                              f"{b['trades']} trades ({b['expectancy']:+.3f}R). Consider trading lighter "
                              f"or sitting out until the pattern reverses."),
                "stage": _stage(b["trades"]),
                "metric": {"weekday": b["weekday"], **b},
            })

    # Best setup grade
    grades = [b for b in _group(rows, "grade") if b["trades"] >= _MIN_BUCKET]
    top = max(grades, key=lambda b: b["expectancy"], default=None)
    if top and top["expectancy"] > 0:
        out.append({
            "statement": (f"Your '{top['grade']}'-grade setups are your edge: {top['win_rate']}% win, "
                          f"{top['expectancy']:+.3f}R over {top['trades']} trades. Prioritise them."),
            "stage": _stage(top["trades"]),
            "metric": {"grade": top["grade"], **top},
        })

    if not out:
        out.append({"statement": "No statistically meaningful edge or weakness yet — "
                                 "results are within normal variance across buckets.",
                    "stage": "no-signal", "metric": None})
    return out


def _stage(trades: int) -> str:
    if trades >= EVIDENCE_MIN:
        return "evidence"
    if trades >= EARLY_SIGNAL_MAX:
        return "building"
    return "early-signal"
