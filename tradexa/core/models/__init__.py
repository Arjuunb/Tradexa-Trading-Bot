"""Domain models.

``bot.types`` already defines the types the live engine, brokers, backtester
and strategies exchange: Bar, Signal, Order, Position, Fill, AccountSnapshot,
Side, OrderType, SignalType. Those are the canonical definitions and this
module **re-exports** them. It does not restate them.

That is a deliberate refusal. Declaring a second ``Order`` here would create
two types with the same name and no conversion between them, and every seam
that touched both would need a translation layer nobody would keep in step —
the classic outcome of a "clean models" package bolted onto a working system.
One definition, imported from wherever it already lives, beats a tidier
address for a duplicate.

What this module adds is what genuinely has no type today and is currently
passed as bare dictionaries:

    Candle            Bar plus the symbol and timeframe it belongs to
    Tick              a single trade/quote print
    Trade             a CLOSED round trip — entry, exit, and the R it made
    ExecutionReport   what came back from a submit attempt
    RiskAssessment    a risk verdict, with the rule that produced it
    StrategyResult    a strategy evaluation, including "no signal" and why
    PortfolioSnapshot account plus positions plus derived exposure

All are frozen dataclasses. Domain values that arrive from an exchange or a
fill are facts about a moment; making them immutable means a downstream module
cannot quietly rewrite history, and it makes them safe to publish on the event
bus where several subscribers hold the same object.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# ``bot`` lives at the repository root, which is on the path for the engine and
# the test suite but not necessarily for a caller importing ``tradexa`` alone.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(_ROOT))

from bot.types import (  # noqa: E402  (re-export: one definition, one source)
    AccountSnapshot,
    Bar,
    Fill,
    Order,
    OrderType,
    Position,
    Side,
    Signal,
    SignalType,
)


# ── market data ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Candle:
    """A Bar that knows which market and timeframe it came from.

    ``Bar`` is deliberately anonymous — the backtester holds one series at a
    time and the symbol is ambient. Anything multi-asset (the scanner, the
    sweep, a portfolio-level feed) has to carry the pair around beside the bar,
    which is how a 4h candle ends up resampled as if it were 1h. Binding them
    together makes that mismatch unrepresentable.
    """

    symbol: str
    timeframe: str
    bar: Bar

    @property
    def timestamp(self) -> datetime:
        return self.bar.timestamp

    @property
    def close(self) -> float:
        return self.bar.close


@dataclass(frozen=True)
class Tick:
    """A single print. Not used by the bar-driven engine today; defined because
    the websocket feed emits these and currently types them as dicts."""

    symbol: str
    timestamp: datetime
    price: float
    size: float = 0.0
    side: Optional[Side] = None


# ── closed round trips ──────────────────────────────────────────────────────
class TradeOutcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    BREAK_EVEN = "break_even"


@dataclass(frozen=True)
class Trade:
    """A CLOSED position — entry through exit.

    Distinct from ``Position`` (open, mutable, marked to market) and from
    ``Fill`` (one execution). Analytics, the journal, the evidence review and
    the monitoring agent all reason about completed round trips and each
    currently rebuilds that shape from dicts with slightly different keys.

    ``r_multiple`` is the unit that matters: profit measured in units of the
    risk actually taken. Currency P&L is not comparable across position sizes;
    R is.
    """

    symbol: str
    side: Side
    qty: float
    entry_price: float
    exit_price: float
    opened_at: datetime
    closed_at: datetime
    pnl: float
    r_multiple: Optional[float] = None
    fees: float = 0.0
    strategy_id: Optional[str] = None
    reason: str = ""

    @property
    def outcome(self) -> TradeOutcome:
        if self.pnl > 0:
            return TradeOutcome.WIN
        if self.pnl < 0:
            return TradeOutcome.LOSS
        return TradeOutcome.BREAK_EVEN

    @property
    def duration_s(self) -> float:
        return (self.closed_at - self.opened_at).total_seconds()


# ── execution ───────────────────────────────────────────────────────────────
class ExecutionStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True)
class ExecutionReport:
    """The outcome of a submit attempt.

    Every broker currently reports success differently — some return an id,
    some a dict, some raise. A single report type lets the execution engine
    treat "rejected by the venue" and "the HTTP call blew up" as the same shape
    of answer, which is what makes retry policy expressible at all.
    """

    status: ExecutionStatus
    order: Order
    broker_order_id: Optional[str] = None
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    fees: float = 0.0
    submitted_at: Optional[datetime] = None
    message: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (ExecutionStatus.ACCEPTED, ExecutionStatus.FILLED,
                               ExecutionStatus.PARTIAL)


# ── risk ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RiskAssessment:
    """A risk verdict on a proposed trade.

    Carries the approved size, because "allowed" and "allowed at what size" are
    the same decision — returning a bare bool is what forces sizing to be
    recomputed somewhere else and drift from the rule that approved it.

    ``rule`` names the specific guard on a rejection, so the UI and the logs can
    say *which* limit stopped a trade instead of "blocked by risk".
    """

    approved: bool
    approved_qty: float = 0.0
    risk_amount: float = 0.0
    rule: Optional[str] = None
    reason: str = ""
    warnings: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls, qty: float, *, risk_amount: float = 0.0,
              warnings: tuple[str, ...] = (), **context: Any) -> "RiskAssessment":
        return cls(approved=True, approved_qty=qty, risk_amount=risk_amount,
                   warnings=warnings, context=context)

    @classmethod
    def reject(cls, rule: str, reason: str, **context: Any) -> "RiskAssessment":
        return cls(approved=False, rule=rule, reason=reason, context=context)


# ── strategy ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StrategyResult:
    """One strategy evaluation of one bar.

    Models "no signal" as a first-class answer WITH a reason, rather than
    ``None``. A strategy that declines to trade is doing its job, and the
    reason is the most useful thing the decision log can record — "why isn't it
    trading?" is otherwise unanswerable after the fact.
    """

    strategy_id: str
    symbol: str
    timestamp: datetime
    signal: Optional[Signal] = None
    reason: str = ""
    indicators: dict[str, float] = field(default_factory=dict)

    @property
    def has_signal(self) -> bool:
        return self.signal is not None


# ── portfolio ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PortfolioSnapshot:
    """Account plus positions plus what they imply, at one instant.

    Exposure is derived here rather than stored, so it cannot disagree with the
    positions it is computed from.
    """

    timestamp: datetime
    account: AccountSnapshot
    positions: tuple[Position, ...] = ()
    realized_pnl: float = 0.0
    fees_paid: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions)

    @property
    def open_positions(self) -> int:
        return sum(1 for p in self.positions if p.qty)

    @property
    def gross_exposure(self) -> float:
        """Absolute notional at risk, longs and shorts alike — the number that
        matters for a margin call, unlike a net figure that a hedged book
        flatters to zero."""
        return sum(abs(p.qty) * p.avg_price for p in self.positions)

    def exposure_pct(self) -> Optional[float]:
        """Gross exposure as a fraction of equity, or None when equity is zero
        — a blown account has no meaningful ratio, and dividing anyway would
        report ``inf`` as if it were a measurement."""
        if not self.account.equity:
            return None
        return self.gross_exposure / self.account.equity


__all__ = [
    # re-exported canonical types (defined in bot.types)
    "Bar", "Signal", "Order", "Position", "Fill", "AccountSnapshot",
    "Side", "OrderType", "SignalType",
    # added here
    "Candle", "Tick",
    "Trade", "TradeOutcome",
    "ExecutionReport", "ExecutionStatus",
    "RiskAssessment",
    "StrategyResult",
    "PortfolioSnapshot",
]
