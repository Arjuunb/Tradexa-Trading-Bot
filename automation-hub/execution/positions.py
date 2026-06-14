"""Position helpers over the engine's ``Position`` type."""
from __future__ import annotations

from bot.types import Position  # re-export

__all__ = ["Position", "unrealized_pnl", "notional"]


def unrealized_pnl(pos: Position, last_price: float) -> float:
    return (last_price - pos.avg_price) * pos.qty


def notional(pos: Position, last_price: float) -> float:
    return abs(pos.qty) * last_price
