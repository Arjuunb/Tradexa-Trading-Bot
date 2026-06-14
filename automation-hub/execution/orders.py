"""Order helpers — re-exports the engine's order types plus small builders.

Keeps a single import surface for the execution layer; the underlying
``bot.types`` dataclasses are reused unchanged.
"""
from __future__ import annotations

from bot.types import Order, OrderType, Side  # re-export

__all__ = ["Order", "OrderType", "Side", "market_order", "limit_order"]


def market_order(symbol: str, side: Side, qty: float,
                 stop_loss: float | None = None,
                 take_profit: float | None = None) -> Order:
    return Order(symbol=symbol, side=side, qty=qty, order_type=OrderType.MARKET,
                 stop_loss=stop_loss, take_profit=take_profit)


def limit_order(symbol: str, side: Side, qty: float, limit_price: float) -> Order:
    return Order(symbol=symbol, side=side, qty=qty, order_type=OrderType.LIMIT,
                 limit_price=limit_price)
