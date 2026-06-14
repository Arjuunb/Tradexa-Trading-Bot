"""Max-drawdown guard. Halts a bot when peak-to-trough equity breaches a cap."""
from __future__ import annotations

from typing import Sequence

from bot.metrics import max_drawdown


def current_drawdown(equity: Sequence[float]) -> float:
    """Most-recent drawdown from the running peak (<= 0)."""
    if not equity:
        return 0.0
    peak = max(equity)
    # peak so far up to the last point:
    running_peak = equity[0]
    for v in equity:
        running_peak = max(running_peak, v)
    last = equity[-1]
    return (last - running_peak) / running_peak if running_peak > 0 else 0.0


def breached(equity: Sequence[float], max_dd_pct: float) -> bool:
    """True if worst drawdown over the curve exceeds the cap (e.g. 0.20)."""
    return max_drawdown(list(equity)) <= -abs(max_dd_pct)
