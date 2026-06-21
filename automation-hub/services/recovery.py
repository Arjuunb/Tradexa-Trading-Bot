"""Strategy Health scorecard (#10) + Drawdown Recovery engine (#18).

Builds on services.strategy_health (which already grades win rate / profit
factor / drawdown / expectancy and flags deterioration) by adding the two
missing scores — Stability and Confidence — and an auto unhealthy flag, plus a
drawdown-recovery policy that scales risk down as drawdown deepens.

Pure functions over a trade list / equity figures — fully unit-testable.
"""
from __future__ import annotations

from typing import Sequence

from services.strategy_health import StrategyHealthMonitor


def _clamp(x, lo=0, hi=100):
    return int(max(lo, min(hi, round(x))))


def _rs(trades: Sequence[dict]) -> list:
    """Per-trade R multiples (falls back to pnl sign when r is absent)."""
    out = []
    for t in trades:
        r = t.get("r")
        if r is None:
            r = t.get("rr")
        out.append(float(r) if r is not None else (1.0 if t.get("pnl", 0) > 0 else -1.0))
    return out


def stability_score(trades: Sequence[dict]) -> int:
    """0-100 — how consistent the equity path is (small, shallow drawdowns vs
    net, low return dispersion). Rewards smooth curves, punishes lumpiness."""
    rs = _rs(trades)
    n = len(rs)
    if n < 4:
        return 0
    net = sum(rs)
    # max drawdown of the cumulative R curve
    cum = peak = dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    dd_term = 1.0 - dd / (abs(net) + dd + 1e-9)          # 1 = no drawdown
    mean = net / n
    var = sum((r - mean) ** 2 for r in rs) / n
    sd = var ** 0.5
    disp_term = 1.0 / (1.0 + (sd / (abs(mean) + 1e-9)))  # tight dispersion -> ~1
    return _clamp(100 * (0.6 * dd_term + 0.4 * disp_term))


def confidence_score(trades: Sequence[dict]) -> int:
    """0-100 — how much to trust the edge: sample size × profit factor."""
    rs = _rs(trades)
    n = len(rs)
    if n == 0:
        return 0
    gp = sum(r for r in rs if r > 0)
    gl = -sum(r for r in rs if r < 0)
    pf = (gp / gl) if gl > 0 else (3.0 if gp > 0 else 0.0)
    sample = min(1.0, n / 40.0)
    edge = min(1.0, pf / 2.0)
    return _clamp(100 * (0.45 * sample + 0.55 * edge))


def health_scorecard(trades: Sequence[dict]) -> dict:
    """Full health card: the monitor's stats + Stability + Confidence + an auto
    unhealthy flag (#10)."""
    health = StrategyHealthMonitor().evaluate(list(trades)).to_dict()
    recent = health["recent"]
    stab = stability_score(trades)
    conf = confidence_score(trades)
    unhealthy = health["status"] == "Unhealthy" or (conf < 25 and len(trades) >= 8)
    return {
        "status": health["status"], "unhealthy": unhealthy,
        "win_rate": round(recent["win_rate"] * 100, 1),
        "profit_factor": recent["profit_factor"],
        "expectancy": recent["expectancy"],
        "max_drawdown": recent["max_drawdown"],
        "stability_score": stab, "confidence_score": conf,
        "trades": recent["n"], "warnings": health["warnings"],
    }


# ──────────────────────────── drawdown recovery (#18) ────────────────────────
def drawdown_recovery(peak_equity: float, equity: float, *,
                      soft: float = 0.05, hard: float = 0.10, critical: float = 0.18) -> dict:
    """As drawdown deepens, scale risk down and recommend protective actions.

    Returns the recovery ``mode``, a ``risk_multiplier`` to apply to position
    sizing, a ``max_trades_factor`` and concrete ``actions``."""
    peak = max(float(peak_equity), float(equity), 1e-9)
    dd = max(0.0, (peak - float(equity)) / peak)
    if dd < soft:
        mode, mult, tf, actions = "normal", 1.0, 1.0, []
    elif dd < hard:
        mode, mult, tf = "caution", 0.66, 0.75
        actions = ["Reduce risk per trade to ~66%.",
                   "Skip the weakest strategy / symbol until the curve recovers."]
    elif dd < critical:
        mode, mult, tf = "recovery", 0.4, 0.5
        actions = ["Cut risk per trade to ~40%.",
                   "Halve max trades per day.",
                   "Pause underperforming strategies (confidence < 35).",
                   "Take only A+ setups (quality score ≥ 75)."]
    else:
        mode, mult, tf = "lockdown", 0.0, 0.0
        actions = ["Stop opening new positions.",
                   "Manual review required before resuming — the drawdown is beyond the safe band."]
    return {
        "drawdown_pct": round(dd * 100, 2), "mode": mode,
        "risk_multiplier": mult, "max_trades_factor": tf,
        "recovery_active": mode != "normal", "actions": actions,
        "thresholds": {"soft": soft * 100, "hard": hard * 100, "critical": critical * 100},
    }
