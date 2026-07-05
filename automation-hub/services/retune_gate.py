"""Strategy retune gate (Phase 10).

Enforces "do not retune the strategy from a small sample". A retune search may
only run once the LIVE paper record has enough closed trades to justify acting
on it; promotion of any shadow candidate needs the stronger evidence threshold.
A ``critical_bug`` override exists for fixing a broken infrastructure path — it
is the ONLY way to bypass the sample gate, and it is logged.

This never touches live trading. It only decides whether a *paper* retune search
is allowed to run, and whether a shadow may be *promoted* (still manual).
"""
from __future__ import annotations

# Match the paper-validation staging so the whole system speaks one language.
MIN_REVIEW = 30      # below this: no retune (except a critical bug)
MIN_EVIDENCE = 50    # at/above this: retune search + promotion may be considered


def evaluate_retune_gate(
    *,
    closed_paper_trades: int,
    critical_bug: bool = False,
    min_review: int = MIN_REVIEW,
    min_evidence: int = MIN_EVIDENCE,
) -> dict:
    """Decide whether a retune search may run and whether promotion is allowed.

    Returns ``allowed`` (may the search run), ``promotion_allowed`` (may a shadow
    candidate be promoted), a ``stage`` and a human ``reason``.
    """
    n = int(closed_paper_trades or 0)

    if critical_bug:
        return {
            "allowed": True, "promotion_allowed": False,
            "stage": "critical-bug-override",
            "sample_size": n, "min_review": min_review, "min_evidence": min_evidence,
            "reason": ("Critical-bug override: a retune is permitted to fix a broken "
                       "path. Promotion still requires evidence and human review."),
        }

    if n < min_review:
        return {
            "allowed": False, "promotion_allowed": False,
            "stage": "insufficient-sample",
            "sample_size": n, "min_review": min_review, "min_evidence": min_evidence,
            "reason": (f"Only {n} closed paper trades (need ≥ {min_review}). Continue "
                       "paper validation — no retune from a small sample."),
        }

    if n < min_evidence:
        return {
            "allowed": False, "promotion_allowed": False,
            "stage": "early-review",
            "sample_size": n, "min_review": min_review, "min_evidence": min_evidence,
            "reason": (f"{n} closed trades — early review only. Keep validating toward "
                       f"{min_evidence}+ before a retune; observe, do not change rules."),
        }

    return {
        "allowed": True, "promotion_allowed": True,
        "stage": "evidence",
        "sample_size": n, "min_review": min_review, "min_evidence": min_evidence,
        "reason": (f"{n} closed trades — evidence level. A retune search may run and "
                   "produce a shadow; promotion still needs the shadow to beat live "
                   "on its own sample AND a human decision."),
    }
