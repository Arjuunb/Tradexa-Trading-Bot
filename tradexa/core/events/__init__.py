"""The event vocabulary.

Definitions only — no bus, no dispatch, no subscribers. Phase 2 adds the
implementation; this phase fixes the *language*, because an event bus whose
payloads are dicts is a second untyped API, and the shape of what modules say
to each other matters more than the machinery that carries it.

Every event is frozen and carries ``occurred_at``. Ordering is reconstructed
from the events themselves rather than from the order a subscriber happened to
receive them, which is the only way a replayed sequence can be compared against
a live one.

Naming is past-tense throughout — ``OrderFilled``, not ``FillOrder``. An event
is a statement that something happened; a command is a request that something
should. Mixing the two is how a bus becomes a call graph with extra steps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from tradexa.core.models import (
    Bar,
    ExecutionReport,
    Order,
    PortfolioSnapshot,
    Position,
    RiskAssessment,
    Signal,
    Trade,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Event:
    """Root event. ``occurred_at`` is UTC and set at construction.

    Subclasses declare their own fields; this base exists so the bus can type
    a subscription as ``Event`` and so every event is guaranteed to carry a
    timestamp without each one remembering to.
    """

    occurred_at: datetime = field(default_factory=_now)

    @property
    def name(self) -> str:
        return type(self).__name__


# ── lifecycle ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class BotStarted(Event):
    mode: str = "paper"
    symbols: tuple[str, ...] = ()
    timeframe: str = ""
    strategy: str = ""


@dataclass(frozen=True)
class BotStopped(Event):
    reason: str = ""


# ── market data ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MarketDataReceived(Event):
    """A CLOSED bar arrived.

    Only closed bars are published. An in-progress candle changes under the
    subscriber's feet, and acting on one is how a backtest and a live run
    diverge on identical data.
    """

    symbol: str = ""
    timeframe: str = ""
    bar: Optional[Bar] = None
    source: str = ""


# ── strategy ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SignalGenerated(Event):
    signal: Optional[Signal] = None
    strategy_id: str = ""


@dataclass(frozen=True)
class SignalRejected(Event):
    """A strategy looked and declined. Published because "why isn't it
    trading?" is the most-asked question of any bot, and it is unanswerable
    after the fact unless the non-events were recorded too."""

    symbol: str = ""
    strategy_id: str = ""
    reason: str = ""


# ── risk ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RiskValidated(Event):
    signal: Optional[Signal] = None
    assessment: Optional[RiskAssessment] = None


@dataclass(frozen=True)
class RiskBreached(Event):
    """A limit was hit — daily loss, exposure, drawdown."""

    rule: str = ""
    detail: str = ""
    halted: bool = False


# ── execution ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class OrderSubmitted(Event):
    order: Optional[Order] = None
    broker: str = ""


@dataclass(frozen=True)
class OrderFilled(Event):
    report: Optional[ExecutionReport] = None


@dataclass(frozen=True)
class OrderRejectedEvent(Event):
    """Named with the suffix to avoid colliding with the ``OrderRejected``
    exception. They describe the same fact in different registers: one is
    raised at a call site, the other is broadcast to anyone listening."""

    order: Optional[Order] = None
    reason: str = ""


# ── positions & portfolio ───────────────────────────────────────────────────
@dataclass(frozen=True)
class PositionOpened(Event):
    position: Optional[Position] = None
    strategy_id: str = ""


@dataclass(frozen=True)
class PositionClosed(Event):
    trade: Optional[Trade] = None


@dataclass(frozen=True)
class PortfolioUpdated(Event):
    snapshot: Optional[PortfolioSnapshot] = None


#: Every event type, for registry checks and documentation. Kept explicit
#: rather than derived by subclass introspection so an event only becomes part
#: of the public vocabulary when someone deliberately adds it.
ALL_EVENTS: tuple[type[Event], ...] = (
    BotStarted, BotStopped,
    MarketDataReceived,
    SignalGenerated, SignalRejected,
    RiskValidated, RiskBreached,
    OrderSubmitted, OrderFilled, OrderRejectedEvent,
    PositionOpened, PositionClosed, PortfolioUpdated,
)

__all__ = [
    "Event",
    "BotStarted", "BotStopped",
    "MarketDataReceived",
    "SignalGenerated", "SignalRejected",
    "RiskValidated", "RiskBreached",
    "OrderSubmitted", "OrderFilled", "OrderRejectedEvent",
    "PositionOpened", "PositionClosed", "PortfolioUpdated",
    "ALL_EVENTS",
]
