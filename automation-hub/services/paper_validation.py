"""Paper-trading validation readiness (Phase 8).

Turns REAL stored paper trades + skip log + Safety Center state into a single
"is this ready for a human live-trading review?" verdict. It never unlocks live
trading — live stays hard-locked. Eligibility is deliberately multi-factor so a
single good-looking metric can never carry it:

  eligible = enough sample size  AND  a proven edge  AND  safety guards active

30 closed trades is the minimum for review; 50+ is the stronger "evidence"
threshold (matching the decision journal's staging).
"""
from __future__ import annotations

MIN_REVIEW = 30      # minimum closed paper trades before a live review may start
MIN_EVIDENCE = 50    # stronger-evidence threshold


def build_paper_validation(
    *,
    perf: dict,
    avg_rr: float,
    per_symbol: list[dict],            # [{name, net_pnl}]
    per_strategy: list[dict],          # [{name, net_r}]
    skipped_total: int,
    skipped_by_category: list[dict],   # [{category, count}]
    readiness: dict,                   # from services.safety_gate.build_live_readiness
    min_review: int = MIN_REVIEW,
    min_evidence: int = MIN_EVIDENCE,
) -> dict:
    n = int(perf.get("trades", 0) or 0)
    pf = float(perf.get("profit_factor", 0) or 0)
    exp = float(perf.get("expectancy", 0) or 0)

    sample_ok = n >= min_review
    edge_ok = n > 0 and pf >= 1.0 and exp > 0
    # only the guards a paper->live review depends on (a real live broker
    # connection is checked separately at go-live, not during paper validation)
    reqs = {r["key"]: r["passed"] for r in readiness.get("requirements", [])}
    safety_keys = ("max_daily_loss", "max_drawdown", "decision_logging",
                   "emergency_stop_tested")
    safety_ok = all(reqs.get(k, False) for k in safety_keys)

    eligible = sample_ok and edge_ok and safety_ok
    if not sample_ok:
        stage = "insufficient-sample"
    elif eligible and n >= min_evidence:
        stage = "ready-for-review (evidence)"
    elif eligible:
        stage = "ready-for-review (early)"
    else:
        stage = "not-eligible"

    reasons = []
    if not sample_ok:
        reasons.append(f"Need ≥ {min_review} closed paper trades (have {n}).")
    if not edge_ok:
        reasons.append("Edge not proven yet (need profit factor ≥ 1.0 and positive expectancy).")
    if not safety_ok:
        missing = [k for k in safety_keys if not reqs.get(k, False)]
        reasons.append("Safety guards incomplete: " + ", ".join(missing) + ".")
    if eligible:
        reasons.append("Sample size, edge and safety guards all met — a human live review may begin.")

    def _pick(rows, key):
        rows = [r for r in rows if r.get(key) is not None]
        if not rows:
            return None, None
        return (max(rows, key=lambda r: r[key]), min(rows, key=lambda r: r[key]))

    best_sym, worst_sym = _pick(per_symbol, "net_pnl")
    best_strat, worst_strat = _pick(per_strategy, "net_r")

    return {
        "sample_size": n,
        "min_review": min_review,
        "min_evidence": min_evidence,
        "metrics": {
            "win_rate": perf.get("win_rate", 0.0),
            "profit_factor": pf,
            "expectancy": exp,
            "max_drawdown_pct": perf.get("max_drawdown_pct", 0.0),
            "avg_rr": round(avg_rr, 2),
            "sharpe_ratio": perf.get("sharpe_ratio", 0.0),
            "sortino_ratio": perf.get("sortino_ratio", 0.0),
        },
        "best_symbol": best_sym, "worst_symbol": worst_sym,
        "best_strategy": best_strat, "worst_strategy": worst_strat,
        "skipped_total": skipped_total,
        "skipped_by_category": skipped_by_category,
        "safety": {
            "live_allowed": readiness.get("live_allowed", False),
            "hard_locked": readiness.get("hard_locked", True),
            "passed": readiness.get("passed", 0),
            "total": readiness.get("total", 0),
        },
        "live_review": {
            "eligible": eligible,
            "stage": stage,
            "reasons": reasons,
            "note": ("Live trading stays LOCKED regardless of this verdict. "
                     "This is human-review eligibility only — it never auto-enables "
                     "real-money trading."),
        },
    }
