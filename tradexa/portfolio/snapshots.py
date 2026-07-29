"""What the Portfolio Engine reads.

The engine is a **pure function of these inputs**. It opens no connection, holds
no session and imports no execution engine. A caller assembles a ``Portfolio``
from wherever the truth lives — a paper engine, a broker's REST account
endpoint, an exchange's balances call — and hands it over.

That separation is the requirement, not a stylistic preference. Portfolio
mathematics that lives inside an execution engine can only ever describe that
one engine's account: a second broker means a second copy of the arithmetic,
and two copies of a Sharpe ratio drift. Here the venues are data, so one
account and nine are the same code path.

Two honesty rules run through every type in this file, and both exist because
the alternative is a number that looks fine and is wrong:

**A missing mark price is not a zero.** ``PositionSnapshot.unrealized_pnl``
returns ``None`` when the position has no mark, and every aggregate above it
propagates that as unavailable. Treating an unmarked position as flat reports a
losing book as break-even.

**Currencies are not silently summed.** A USD broker and a EUR broker do not
add up without a rate. Given one, the engine converts; without one, it says so
rather than producing a number that is the sum of two different things.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class VenueKind(str, Enum):
    """What sort of account this is.

    Kept as data rather than as separate classes: a broker and an exchange
    differ in how their state is FETCHED, which is the adapter's problem, not in
    how equity is computed, which is this package's.
    """

    BROKER = "broker"
    EXCHANGE = "exchange"
    PAPER = "paper"


@dataclass(frozen=True)
class PositionSnapshot:
    """One open position, as the portfolio needs to see it."""

    symbol: str
    direction: Direction
    qty: float
    entry: float
    #: Current price. ``None`` means genuinely unknown — see the module note.
    mark: Optional[float] = None
    stop: Optional[float] = None
    venue: str = ""
    #: Units of the underlying per contract. 1.0 for spot and crypto.
    contract_multiplier: float = 1.0

    @property
    def notional(self) -> float:
        """Exposure at the CURRENT price where one is known, at entry otherwise.

        Marking to entry is a fallback that is stated, not hidden: an aggregate
        built on it carries ``marks_missing``, so a reader can tell whether the
        exposure figure moves with the market or is frozen at cost.
        """
        price = self.mark if self.mark is not None else self.entry
        return abs(self.qty) * price * self.contract_multiplier

    @property
    def signed_notional(self) -> float:
        """Positive long, negative short. Nets across a hedged book."""
        sign = 1.0 if self.direction is Direction.LONG else -1.0
        return sign * self.notional

    @property
    def cost_basis(self) -> float:
        return abs(self.qty) * self.entry * self.contract_multiplier

    @property
    def unrealized_pnl(self) -> Optional[float]:
        """``None`` without a mark. Never 0.0 — that is a claim, not a gap."""
        if self.mark is None:
            return None
        move = self.mark - self.entry
        if self.direction is Direction.SHORT:
            move = -move
        return move * abs(self.qty) * self.contract_multiplier

    @property
    def risk_amount(self) -> Optional[float]:
        """Currency at stake to the stop. ``None`` when unstopped — which is
        unbounded risk, not none, and must not be summed as zero."""
        if self.stop is None:
            return None
        return abs(self.entry - self.stop) * abs(self.qty) * self.contract_multiplier


@dataclass(frozen=True)
class VenueSnapshot:
    """One broker or exchange account, at an instant.

    Every venue reports its own cash, its own positions and its own margin. The
    engine aggregates them; it never assumes they share a balance, because two
    exchanges genuinely do not.
    """

    venue: str
    kind: VenueKind = VenueKind.BROKER
    #: Cash attributable to this account. Not equity — that is cash plus open
    #: P&L. On a spot venue the cost of an open position has already left this
    #: figure; on a margin venue it appears in ``used_margin`` instead. Either
    #: way ``equity == cash + unrealised``, which is what the aggregates rely on.
    cash: float = 0.0
    positions: Sequence[PositionSnapshot] = ()
    #: Margin currently committed. 0 on a cash or spot account.
    used_margin: float = 0.0
    #: Maximum leverage this venue permits. 1.0 = cash account.
    max_leverage: float = 1.0
    #: Lifetime realised P&L booked at this venue.
    realized_pnl: float = 0.0
    currency: str = "USD"
    #: Whether the snapshot came back cleanly. A venue that failed to respond is
    #: EXCLUDED from aggregates rather than counted as an empty account — an
    #: unreachable exchange holding three positions is not a flat one.
    reachable: bool = True
    note: str = ""

    @property
    def gross_exposure(self) -> float:
        return sum(p.notional for p in self.positions)

    @property
    def net_exposure(self) -> float:
        return sum(p.signed_notional for p in self.positions)

    @property
    def unrealized_pnl(self) -> Optional[float]:
        """``None`` if ANY position is unmarked — a partial sum presented as a
        total is the most misleading answer available."""
        if any(p.mark is None for p in self.positions):
            return None
        return sum(p.unrealized_pnl or 0.0 for p in self.positions)

    @property
    def unmarked(self) -> tuple[str, ...]:
        return tuple(p.symbol for p in self.positions if p.mark is None)

    @property
    def equity(self) -> Optional[float]:
        u = self.unrealized_pnl
        return None if u is None else self.cash + u

    @property
    def free_margin(self) -> Optional[float]:
        eq = self.equity
        return None if eq is None else max(0.0, eq - self.used_margin)

    @property
    def buying_power(self) -> Optional[float]:
        """What can still be deployed here: free margin times the venue's own
        leverage. Computed per venue and only then summed — a 1× cash broker and
        a 10× futures venue do not share a multiplier."""
        free = self.free_margin
        return None if free is None else free * max(1.0, self.max_leverage)

    @property
    def margin_level(self) -> Optional[float]:
        """Equity over used margin. ``None`` on an unlevered account, where the
        ratio is not "infinitely safe" — it is undefined."""
        if not self.used_margin:
            return None
        eq = self.equity
        return None if eq is None else eq / self.used_margin


@dataclass(frozen=True)
class EquityPoint:
    """One observation of total portfolio equity."""

    at: datetime
    equity: float


@dataclass(frozen=True)
class ClosedTrade:
    """A finished trade. The unit the win rate and expectancy are measured in."""

    symbol: str
    pnl: float
    closed_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    venue: str = ""
    #: R-multiple where the strategy recorded one.
    rr: Optional[float] = None

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


@dataclass(frozen=True)
class Portfolio:
    """Everything the engine is given. Assembled by the caller, read by the engine."""

    venues: Sequence[VenueSnapshot] = ()
    #: Equity over time — the input to Sharpe, drawdown and the return windows.
    #: Supplied rather than derived: the engine sees one instant, and a curve
    #: reconstructed from closed trades alone would miss every open-position
    #: swing between them.
    equity_curve: Sequence[EquityPoint] = ()
    closed_trades: Sequence[ClosedTrade] = ()
    base_currency: str = "USD"
    #: currency -> units of base per unit. ``{"EUR": 1.09}`` reads as 1 EUR =
    #: 1.09 USD. The base currency is implicitly 1.0 and need not be listed.
    fx_rates: Mapping[str, float] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def reachable_venues(self) -> tuple[VenueSnapshot, ...]:
        return tuple(v for v in self.venues if v.reachable)

    @property
    def unreachable_venues(self) -> tuple[str, ...]:
        return tuple(v.venue for v in self.venues if not v.reachable)

    def rate_for(self, currency: str) -> Optional[float]:
        """Conversion into the base currency, or ``None`` if unknown."""
        if currency == self.base_currency:
            return 1.0
        rate = self.fx_rates.get(currency)
        return float(rate) if rate else None

    @property
    def unconvertible(self) -> tuple[str, ...]:
        """Currencies present in the book with no rate to the base."""
        return tuple(sorted({v.currency for v in self.reachable_venues
                             if self.rate_for(v.currency) is None}))

    def venue(self, name: str) -> Optional[VenueSnapshot]:
        for v in self.venues:
            if v.venue == name:
                return v
        return None


def to_dict(value: Any) -> Any:
    """JSON-safe rendering that keeps ``None`` as ``None``.

    Written rather than reached for from a serialisation library because the
    one thing it must not do is coerce an unavailable figure to 0 on its way to
    a dashboard — which is exactly where the honesty rules above would be
    quietly undone.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: to_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dict(v) for v in value]
    return value


__all__ = ["Direction", "VenueKind", "PositionSnapshot", "VenueSnapshot",
           "EquityPoint", "ClosedTrade", "Portfolio", "to_dict"]
