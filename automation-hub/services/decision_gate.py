"""Decision gate — the single accept/reject point in front of every trade.

Builds the unified decision object from REAL inputs (the DecisionBrain signal
plus the TradeBrain quality verdict) and applies the same acceptance rule the
engine has always enforced: no hard blocks AND quality score >= min_score.
Nothing is fabricated: every score, rule and reason comes from computed values.

The decision object (the contract the dashboard reads):
    symbol, timeframe, strategy, side, regime (market regime), htf_bias,
    setup_quality_score (TradeBrain 0-100), volume_score, rr_score,
    confidence (strategy's own 0-1), passed_rules, failed_rules,
    decision ("accepted"|"rejected"), reason, components (full breakdown).
"""
from __future__ import annotations

from typing import Optional

from services.rule_status import RuleStatus


def _rules(verdict) -> list[dict]:
    """The setup-quality rules with their individual verdicts.

    ``passed_rules``/``failed_rules`` below are kept for the seven existing
    consumers, but they flatten a distinction the verdict already draws and
    this function preserves: ``verdict.failed`` are rules the setup satisfied
    only marginally — the reason string built below literally calls them
    "weak" — while ``verdict.blocks`` are hard blocks that stopped the trade.

    Merging them was not merely lossy on screen. This object is persisted to
    the decision store, so the distinction was destroyed on write and no later
    query could recover it: a decision rejected by a hard block and one merely
    graded weak looked identical in the archive forever after.
    """
    rules: list[dict] = []
    for name in (verdict.passed or []):
        rules.append({"rule": name, "status": RuleStatus.PASSED})
    for name in (verdict.failed or []):
        rules.append({"rule": name, "status": RuleStatus.WEAK})
    for name in (verdict.blocks or []):
        rules.append({"rule": name, "status": RuleStatus.FAILED})
    return rules


def build_decision(*, symbol: str, timeframe: str, strategy: str, side: str,
                   confidence: Optional[float], verdict, min_score: int,
                   regime_hint: str = "") -> dict:
    """Map a signal + BrainVerdict into the unified decision object.

    ``verdict`` is strategies.brain.BrainVerdict (or None when the quality gate
    is disabled/stood down — then the decision is accepted by definition, with
    the reason stating exactly that; no scores are invented).
    """
    if verdict is None:
        return {
            "symbol": symbol, "timeframe": timeframe, "strategy": strategy,
            "side": side, "regime": regime_hint or None, "htf_bias": None,
            "setup_quality_score": None, "volume_score": None, "rr_score": None,
            "confidence": confidence,
            "passed_rules": [], "failed_rules": [], "rules": [],
            "decision": "accepted",
            "reason": "Quality gate not evaluated (disabled or insufficient history) "
                      "— signal passed through to the risk pipeline.",
            "components": {},
        }

    comp = dict(verdict.components or {})
    accepted = bool(verdict.allowed) and verdict.score >= min_score

    if not verdict.allowed:
        reason = "Hard block: " + "; ".join(verdict.blocks or ["blocked"])
    elif verdict.score < min_score:
        reason = (f"Quality score {verdict.score} below minimum {min_score} "
                  f"(failed: {', '.join(verdict.failed) or 'none'})")
    else:
        reason = (f"Score {verdict.score}/{100} ({verdict.grade}) — "
                  f"{len(verdict.passed)} rules passed"
                  + (f", {len(verdict.failed)} weak" if verdict.failed else ""))

    return {
        "symbol": symbol, "timeframe": timeframe, "strategy": strategy,
        "side": side,
        "regime": verdict.regime or regime_hint or None,
        "htf_bias": verdict.htf_bias,
        "setup_quality_score": float(verdict.score),
        "volume_score": comp.get("volume"),
        "rr_score": comp.get("rr_quality"),
        "confidence": confidence,
        "passed_rules": list(verdict.passed or []),
        # Kept as-is for the existing consumers. `rules` below is the
        # non-lossy form and is what new readers should use.
        "failed_rules": list(verdict.failed or []) + list(verdict.blocks or []),
        "rules": _rules(verdict),
        "decision": "accepted" if accepted else "rejected",
        "reason": reason,
        "components": comp,
    }
