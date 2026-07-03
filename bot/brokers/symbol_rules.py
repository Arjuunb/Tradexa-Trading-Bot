"""Exchange symbol rules — lot size, tick size, minimum notional.

Exchanges reject orders that violate their symbol filters (Binance:
LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL). This is the #1 reason a bot's first
live order fails: a computed size like 0.03712941 BTC must be floored to the
symbol's step size and the resulting notional must still clear the minimum.

``SymbolRules`` is pure and injectable (tests need no network); ``from_ccxt``
parses the rules out of a ccxt market structure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def _floor_to(value: float, step: float) -> float:
    """Floor ``value`` to a multiple of ``step`` (never rounds up — rounding a
    quantity up could exceed balance; rounding a price up could cross a limit)."""
    if step <= 0:
        return value
    # use integer math on the exponent to dodge float dust (0.1+0.2 style)
    ticks = math.floor(round(value / step, 9))
    return round(ticks * step, 12)


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    step_size: float = 0.0      # quantity increment (0 = unconstrained)
    tick_size: float = 0.0      # price increment
    min_qty: float = 0.0
    min_notional: float = 0.0   # min qty * price in quote currency

    # ------------------------------------------------------------- rounding
    def round_qty(self, qty: float) -> float:
        q = _floor_to(qty, self.step_size)
        return q if q >= self.min_qty else 0.0

    def round_price(self, price: Optional[float]) -> Optional[float]:
        if price is None:
            return None
        return _floor_to(price, self.tick_size)

    # ------------------------------------------------------------ validation
    def clamp(self, qty: float, price: float) -> tuple[float, str]:
        """Return (tradable_qty, reason). qty == 0 means the order cannot be
        placed as-is; reason says which filter failed."""
        q = self.round_qty(qty)
        if q <= 0:
            return 0.0, (f"qty {qty} below min lot {max(self.min_qty, self.step_size)}"
                         f" for {self.symbol}")
        if self.min_notional > 0 and price > 0 and q * price < self.min_notional:
            return 0.0, (f"notional {q * price:.2f} below exchange minimum "
                         f"{self.min_notional:.2f} for {self.symbol}")
        return q, ""


def from_ccxt(market: dict) -> SymbolRules:
    """Parse a ccxt ``market`` dict (exchange.market(symbol)) into SymbolRules.

    ccxt normalizes filters into ``limits`` (amount/price/cost mins) and
    ``precision`` (decimal places or step sizes, depending on the exchange's
    precisionMode). Handles both integer-precision and step-size styles.
    """
    limits = market.get("limits") or {}
    precision = market.get("precision") or {}

    def _step(p) -> float:
        if p is None:
            return 0.0
        p = float(p)
        # precisionMode TICK_SIZE gives the step directly (0.001); DECIMAL_PLACES
        # gives an integer count of places (3 -> 0.001)
        return 10.0 ** -int(p) if float(p).is_integer() and p >= 1 else p

    return SymbolRules(
        symbol=market.get("symbol", ""),
        step_size=_step(precision.get("amount")),
        tick_size=_step(precision.get("price")),
        min_qty=float(((limits.get("amount") or {}).get("min")) or 0.0),
        min_notional=float(((limits.get("cost") or {}).get("min")) or 0.0),
    )
