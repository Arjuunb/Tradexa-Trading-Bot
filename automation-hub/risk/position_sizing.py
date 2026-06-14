"""Position sizing — wraps the engine's risk-based sizing.

Risk a fixed % of equity per trade based on stop distance, reusing the tested
``bot.risk.RiskManager`` logic via a thin functional entry point.
"""
from __future__ import annotations

from bot.risk import RiskConfig

from database.models import RiskRules


def size_position(equity: float, entry: float, stop: float,
                  rules: RiskRules) -> float:
    """Return position quantity, capped by per-trade risk and max notional."""
    cfg = RiskConfig(
        risk_per_trade_pct=rules.risk_per_trade_pct,
        max_daily_loss_pct=rules.max_daily_loss_pct,
        max_open_positions=rules.max_open_positions,
    )
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0 or equity <= 0:
        return 0.0
    qty = (equity * cfg.risk_per_trade_pct) / risk_per_unit
    max_notional = equity * cfg.max_position_pct
    if entry > 0 and qty * entry > max_notional:
        qty = max_notional / entry
    return max(qty, 0.0)
