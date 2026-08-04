"""The gap between a backtest fill and a live one.

The platform already models slippage, commission and spread as *costs*
(``services/fill_model.RealisticFill``, and ``bot.tradecore.costs``). What it
has never modelled is the part of execution that is not a cost at all:

    latency      the price moved between deciding and arriving
    queue        a resting limit order is behind other people's orders
    liquidity    a bar's volume is finite, and so is your fill

Each of these makes a backtest optimistic in a way no cost adjustment can fix,
because they change *whether* you traded, not merely at what price. A strategy
whose edge comes from being first in the queue tests beautifully and cannot be
traded.

Everything here is a pure function of an injected clock and a supplied volume.
No randomness by default: a backtest that returns a different answer each run
cannot be used to decide anything, and the places where variance IS wanted
(Monte Carlo) take a seed explicitly.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Any, Optional


class Liquidity(str, Enum):
    MAKER = "maker"
    TAKER = "taker"


@dataclass(frozen=True)
class SpreadModel:
    """The quoted spread, and which side of it you pay.

    A taker crosses it; a maker earns it. Applying half a spread to every fill —
    the usual shortcut — charges a resting limit order for liquidity it
    provided, and understates a market order that crossed the whole thing.
    """

    #: Spread as a fraction of price. 4 bps is a liquid crypto major.
    fraction: float = 0.0004
    #: Widening applied during high volatility, as a multiple.
    stress_multiplier: float = 1.0

    def half(self, price: float) -> float:
        return price * self.fraction * self.stress_multiplier / 2.0

    def fill_price(self, price: float, *, is_buy: bool,
                   liquidity: Liquidity = Liquidity.TAKER) -> float:
        """Where the fill actually lands relative to the mid."""
        half = self.half(price)
        if liquidity is Liquidity.MAKER:
            # A resting order fills at its own price and collects the spread —
            # the sign is inverted, not zeroed. Zeroing it loses the maker's
            # actual edge, which for a market-making strategy is the entire P&L.
            return price - half if is_buy else price + half
        return price + half if is_buy else price - half

    def widen(self, multiplier: float) -> "SpreadModel":
        return SpreadModel(self.fraction, max(1.0, multiplier))


@dataclass
class LatencyModel:
    """The delay between deciding and arriving, in wall-clock terms.

    Modelled as time, not as a price penalty. The two differ whenever the market
    moves during the delay: a fixed price penalty charges the same amount in a
    dead market and a fast one, and the whole point of latency is that it costs
    nothing in the first and everything in the second.
    """

    #: Signal to order arriving at the venue.
    decision_ms: float = 50.0
    #: Venue receiving to acknowledging.
    venue_ms: float = 30.0
    #: Extra delay under stress, as a multiple. Applied when the caller says so.
    stress_multiplier: float = 1.0
    #: Random component. 0 keeps a backtest reproducible, which is the default
    #: because a result that changes per run cannot be used to decide anything.
    jitter_ms: float = 0.0
    seed: int = 7

    def __post_init__(self) -> None:
        self._rnd = random.Random(self.seed)

    @property
    def total_ms(self) -> float:
        base = (self.decision_ms + self.venue_ms) * max(1.0, self.stress_multiplier)
        if self.jitter_ms <= 0:
            return base
        return max(0.0, base + self._rnd.uniform(-self.jitter_ms, self.jitter_ms))

    @property
    def delay(self) -> timedelta:
        return timedelta(milliseconds=self.total_ms)

    def price_after_delay(self, ticks, *, from_index: int) -> tuple[float, int]:
        """The price a delayed order actually meets.

        Walks the tick path forward by the latency and returns the price there,
        with the index it landed on. This is the difference between modelling
        latency and pricing it: in a market that gapped during those 80ms, the
        fill is at the gapped price, and no basis-point penalty would have said
        so.
        """
        if not ticks:
            raise ValueError("no ticks to walk")
        start = ticks[min(from_index, len(ticks) - 1)]
        deadline = start.timestamp + self.delay
        index = from_index
        while index + 1 < len(ticks) and ticks[index + 1].timestamp <= deadline:
            index += 1
        return ticks[index].price, index


@dataclass
class QueuedOrder:
    """A resting limit order and its place in the book."""

    order_id: str
    price: float
    qty: float
    is_buy: bool
    #: Size resting AHEAD of this order at the same price when it was placed.
    queue_ahead: float = 0.0
    filled: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.qty - self.filled)

    @property
    def at_front(self) -> bool:
        return self.queue_ahead <= 0


class OrderQueue:
    """Resting limit orders, filled only after the queue ahead of them.

    The mechanism a bar backtest cannot express. "Price touched my limit" is not
    a fill: it is a fill for whoever was there first, and for you only if enough
    volume traded through to clear the queue in front of you.

    Modelled with the standard pessimistic assumption: volume at a price level
    consumes the queue in order, and your order begins at the BACK of whatever
    was already there. Assuming front-of-queue is what makes a mean-reversion
    backtest look free.
    """

    def __init__(self, *, participation: float = 0.25) -> None:
        #: Fraction of traded volume that can be attributed to your price level.
        #: 25% is deliberately conservative — assuming all of a bar's volume
        #: passed through your exact limit is how a thin market becomes a
        #: perfect one.
        self.participation = participation
        self._orders: dict[str, QueuedOrder] = {}
        self.fills: list[dict[str, Any]] = []

    def place(self, order: QueuedOrder) -> QueuedOrder:
        self._orders[order.order_id] = order
        return order

    def cancel(self, order_id: str) -> Optional[QueuedOrder]:
        return self._orders.pop(order_id, None)

    @property
    def resting(self) -> tuple[QueuedOrder, ...]:
        return tuple(o for o in self._orders.values() if o.remaining > 0)

    def on_trade(self, price: float, volume: float) -> list[dict[str, Any]]:
        """Apply traded volume at ``price``. Returns fills produced.

        A buy limit fills when price trades AT or BELOW it; a sell limit at or
        above. Price trading strictly through the level clears the queue
        entirely — that is what a sweep does, and it is the one case where a
        resting order is certain to fill.
        """
        produced: list[dict[str, Any]] = []
        available = max(0.0, volume) * self.participation
        for order in list(self._orders.values()):
            if order.remaining <= 0:
                continue
            touched = price <= order.price if order.is_buy else price >= order.price
            if not touched:
                continue
            through = price < order.price if order.is_buy else price > order.price
            if through:
                # Swept: everything at the level traded, including this order.
                fill_qty = order.remaining
                order.queue_ahead = 0.0
            else:
                # Touched at the level: the queue consumes volume first.
                if order.queue_ahead > 0:
                    consumed = min(order.queue_ahead, available)
                    order.queue_ahead -= consumed
                    available -= consumed
                    if order.queue_ahead > 0:
                        continue          # still behind others
                fill_qty = min(order.remaining, available)
                available -= fill_qty
            if fill_qty <= 0:
                continue
            order.filled += fill_qty
            fill = {"order_id": order.order_id, "qty": fill_qty,
                    "price": order.price, "liquidity": Liquidity.MAKER.value,
                    "partial": order.remaining > 0}
            produced.append(fill)
            self.fills.append(fill)
        return produced


@dataclass
class LiquidityCap:
    """How much of a bar's volume one order may take.

    Turns partial fills from a coin flip into a consequence of size. A 10-BTC
    order into a bar that traded 12 BTC does not fill at one price, and a
    backtester that fills it anyway has discovered a strategy that only works
    at sizes the market cannot absorb.
    """

    #: Maximum share of the period's volume this order may consume.
    max_participation: float = 0.10
    #: Price impact charged per unit of participation, in basis points.
    impact_bps_per_unit: float = 20.0

    def fillable(self, requested: float, period_volume: float) -> float:
        if period_volume <= 0:
            # No volume means no fill. Filling into a bar that traded nothing is
            # the purest form of backtest fiction.
            return 0.0
        return min(requested, period_volume * self.max_participation)

    def impact(self, filled: float, period_volume: float) -> float:
        """Price impact as a fraction, from how much of the market you took."""
        if period_volume <= 0 or filled <= 0:
            return 0.0
        share = filled / period_volume
        return (share * self.impact_bps_per_unit) / 10_000.0

    def apply(self, *, requested: float, period_volume: float, price: float,
              is_buy: bool) -> dict[str, Any]:
        """One order against one period's liquidity."""
        filled = self.fillable(requested, period_volume)
        impact = self.impact(filled, period_volume)
        effective = price * (1 + impact) if is_buy else price * (1 - impact)
        return {"requested": requested, "filled": filled,
                "unfilled": max(0.0, requested - filled),
                "price": effective, "impact_pct": impact,
                "partial": filled + 1e-12 < requested,
                "participation": (filled / period_volume) if period_volume else 0.0}


@dataclass
class ExecutionModel:
    """Spread, latency, queue and liquidity, composed.

    One object so a backtest configures execution realism in a single place, and
    so a report can state exactly what was assumed. A result whose assumptions
    are spread across six keyword arguments cannot be reproduced by someone
    reading it.
    """

    spread: SpreadModel = field(default_factory=SpreadModel)
    latency: LatencyModel = field(default_factory=LatencyModel)
    liquidity: LiquidityCap = field(default_factory=LiquidityCap)
    commission_bps: float = 4.0
    maker_rebate_bps: float = 0.0

    def commission(self, notional: float, *,
                   liquidity: Liquidity = Liquidity.TAKER) -> float:
        rate = (-self.maker_rebate_bps if liquidity is Liquidity.MAKER
                else self.commission_bps)
        return abs(notional) * rate / 10_000.0

    def describe(self) -> dict[str, Any]:
        """The assumptions, as data, for the report to print verbatim."""
        return {
            "spread_bps": round(self.spread.fraction * 10_000, 4),
            "spread_stress_multiplier": self.spread.stress_multiplier,
            "latency_ms": round(self.latency.decision_ms + self.latency.venue_ms, 3),
            "latency_jitter_ms": self.latency.jitter_ms,
            "commission_bps": self.commission_bps,
            "maker_rebate_bps": self.maker_rebate_bps,
            "max_participation": self.liquidity.max_participation,
            "impact_bps_per_unit": self.liquidity.impact_bps_per_unit,
        }


#: Presets. Named for what they represent rather than "conservative"/"optimistic",
#: because the honest question is "which market is this?" not "how cautious am I
#: feeling?".
LIQUID_CRYPTO = ExecutionModel(
    spread=SpreadModel(fraction=0.0004),
    latency=LatencyModel(decision_ms=50, venue_ms=30),
    liquidity=LiquidityCap(max_participation=0.10, impact_bps_per_unit=20),
    commission_bps=4.0)

THIN_ALTCOIN = ExecutionModel(
    spread=SpreadModel(fraction=0.0030),
    latency=LatencyModel(decision_ms=80, venue_ms=60),
    liquidity=LiquidityCap(max_participation=0.03, impact_bps_per_unit=120),
    commission_bps=7.5)

US_EQUITIES = ExecutionModel(
    spread=SpreadModel(fraction=0.0002),
    latency=LatencyModel(decision_ms=20, venue_ms=15),
    liquidity=LiquidityCap(max_participation=0.05, impact_bps_per_unit=10),
    commission_bps=1.0, maker_rebate_bps=0.2)

#: Zero friction. For proving a change is behaviour-preserving, never for
#: judging a strategy: a backtest with no costs is a description of a market
#: that does not exist.
FRICTIONLESS = ExecutionModel(
    spread=SpreadModel(fraction=0.0),
    latency=LatencyModel(decision_ms=0, venue_ms=0),
    liquidity=LiquidityCap(max_participation=1.0, impact_bps_per_unit=0.0),
    commission_bps=0.0)


__all__ = ["Liquidity", "SpreadModel", "LatencyModel", "QueuedOrder", "OrderQueue",
           "LiquidityCap", "ExecutionModel", "LIQUID_CRYPTO", "THIN_ALTCOIN",
           "US_EQUITIES", "FRICTIONLESS"]
