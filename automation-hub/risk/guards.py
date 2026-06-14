"""Composite risk guard — the live circuit breaker.

Evaluated after every bar by the live runner. If any breaker trips, the runner
halts the bot and fires an alert. Composes the individual guards:

- daily-loss limit        (risk.daily_limits)
- max-drawdown            (risk.drawdown_guard)
- consecutive-loss streak (risk.daily_limits)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from bot.metrics import max_drawdown

from database.models import RiskRules
from risk.daily_limits import consecutive_losses, daily_limit_hit, daily_loss_used
from risk.drawdown_guard import breached


@dataclass
class GuardTrip:
    breaker: str   # "daily_loss" | "drawdown" | "consecutive_losses"
    reason: str    # human-readable


def _equity_values(equity_curve: Sequence) -> list[float]:
    if not equity_curve:
        return []
    first = equity_curve[0]
    if isinstance(first, (tuple, list)):
        return [v for _, v in equity_curve]
    return list(equity_curve)


def evaluate(
    *,
    equity_curve: Sequence,
    trades: Sequence[dict],
    pnl_today: float,
    starting_equity: float,
    rules: RiskRules,
) -> Optional[GuardTrip]:
    """Return the first tripped breaker, or None if all clear."""
    # 1. Daily loss kill switch.
    if daily_limit_hit(pnl_today, starting_equity, rules.max_daily_loss_pct):
        used = daily_loss_used(pnl_today, starting_equity, rules.max_daily_loss_pct)
        return GuardTrip("daily_loss",
                         f"Daily loss limit hit ({used*100:.0f}% of budget)")

    # 2. Max drawdown.
    eq = _equity_values(equity_curve)
    if eq and breached(eq, rules.max_drawdown_pct):
        return GuardTrip("drawdown",
                         f"Max drawdown breached ({max_drawdown(eq)*100:.2f}%)")

    # 3. Consecutive losses.
    n = consecutive_losses(trades)
    if rules.max_consecutive_losses > 0 and n >= rules.max_consecutive_losses:
        return GuardTrip("consecutive_losses",
                         f"{n} consecutive losses (limit {rules.max_consecutive_losses})")

    return None
