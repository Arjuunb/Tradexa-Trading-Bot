"""Daily-loss and consecutive-loss protection.

The engine's RiskManager already enforces the daily-loss kill switch and the
post-loss cooldown during runs; these helpers expose the same checks to the
live supervisor and the Risk Center UI.
"""
from __future__ import annotations

from typing import Sequence


def daily_loss_used(pnl_today: float, equity: float, max_daily_loss_pct: float) -> float:
    """Fraction (0..1+) of the daily-loss budget consumed."""
    limit = max_daily_loss_pct * equity
    if limit <= 0:
        return 0.0
    return max(0.0, -pnl_today) / limit


def daily_limit_hit(pnl_today: float, equity: float, max_daily_loss_pct: float) -> bool:
    return daily_loss_used(pnl_today, equity, max_daily_loss_pct) >= 1.0


def consecutive_losses(trades: Sequence[dict]) -> int:
    streak = 0
    for t in reversed(list(trades)):
        if t.get("pnl", 0) < 0:
            streak += 1
        else:
            break
    return streak


def consecutive_loss_limit_hit(trades: Sequence[dict], max_streak: int) -> bool:
    return consecutive_losses(trades) >= max_streak
