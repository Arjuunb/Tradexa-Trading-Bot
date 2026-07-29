"""The event vocabulary and its envelope.

Definitions only — the bus, dispatcher, registry and replay live in
``tradexa.infrastructure.events``. Keeping them apart is the dependency rule
working: the domain states what can happen, infrastructure decides how it
travels.

Every event carries an envelope so it can be traced, correlated and replayed:

    timestamp       when it happened (``occurred_at``; ``timestamp`` is an alias)
    event_id        unique per event, for deduplication and log joins
    source          which module published it
    correlation_id  ties one causal chain together
    metadata        free-form, for things the type does not model
    payload         the event's own typed fields, as a dict

``correlation_id`` is the field that earns its keep. One bar arriving leads to
a signal, a risk check, an order and a fill — five events across four modules.
Without a shared id, reconstructing that chain from a log means matching on
symbol and timestamp and hoping two symbols did not fire in the same second.
With one, the chain is a filter.

``payload`` is a derived property rather than a stored dict. Storing it would
mean the same data in two places on one frozen object, and the copy would drift
the first time someone constructed an event by hand.

Naming is past-tense throughout — ``OrderFilled``, not ``FillOrder``. An event
states that something happened; a command requests that something should.
Mixing the two turns a bus into a call graph with extra steps.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

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


def new_id() -> str:
    """A short unique id. ``uuid4().hex`` rather than a counter so ids stay
    unique across processes and restarts — a replayed journal from yesterday
    must not collide with events being published today."""
    return uuid.uuid4().hex


#: Envelope field names. Everything else on an event is its payload.
ENVELOPE_FIELDS = frozenset(
    {"occurred_at", "event_id", "source", "correlation_id", "metadata"})


@dataclass(frozen=True)
class Event:
    """Root event, carrying the envelope every event shares.

    All fields default, so a subclass may add its own without ordering
    problems, and existing construction sites keep working unchanged.
    """

    occurred_at: datetime = field(default_factory=_now)
    event_id: str = field(default_factory=new_id)
    #: The module that published this. Set by ``EventPublisher`` so callers do
    #: not repeat it, and so it cannot drift from where the code actually lives.
    source: str = ""
    #: Shared across every event in one causal chain. Empty means "not
    #: correlated" rather than "no chain" — an honest gap, not a fake id.
    correlation_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return type(self).__name__

    @property
    def timestamp(self) -> datetime:
        """Alias for ``occurred_at``. Both names exist because the envelope
        specifies ``timestamp`` while the original field was ``occurred_at``,
        and renaming would break published code for no behavioural gain."""
        return self.occurred_at

    @property
    def payload(self) -> dict[str, Any]:
        """The event's own fields — everything that is not envelope.

        Derived, never stored: one frozen object holding the same data twice is
        one bad constructor away from a payload that disagrees with the fields
        it claims to describe.
        """
        return {f.name: getattr(self, f.name) for f in fields(self)
                if f.name not in ENVELOPE_FIELDS}

    def envelope(self) -> dict[str, Any]:
        """The envelope alone, for logs and the replay journal."""
        return {
            "event": self.name,
            "event_id": self.event_id,
            "timestamp": self.occurred_at.isoformat(),
            "source": self.source,
            "correlation_id": self.correlation_id,
            "metadata": dict(self.metadata),
        }


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
    """Market data arrived from a feed.

    ``data_source`` is the provenance of the DATA — "live (ccxt)", "bundled
    sample" — distinct from the envelope's ``source``, which is the module that
    published the event. They were one field before the envelope existed; the
    distinction matters because a live-mode engine served bundled data will
    never see a new candle, and that failure is invisible unless the data's
    provenance travels beside it.
    """

    symbol: str = ""
    timeframe: str = ""
    bar: Optional[Bar] = None
    data_source: str = ""


@dataclass(frozen=True)
class CandleClosed(Event):
    """A candle CLOSED and is final.

    Separate from ``MarketDataReceived`` because only a closed candle may be
    acted on. An in-progress bar changes under the subscriber's feet, and
    trading one is how a backtest and a live run diverge on identical data.
    A feed that emits ticks publishes many MarketDataReceived per CandleClosed.
    """

    symbol: str = ""
    timeframe: str = ""
    bar: Optional[Bar] = None
    data_source: str = ""


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
class RiskCheckStarted(Event):
    """Risk evaluation began.

    Paired with RiskApproved/RiskRejected so a check that never completes is
    visible. A silent risk engine and one that approved everything look
    identical if only the outcomes are published.
    """

    signal: Optional[Signal] = None
    symbol: str = ""


@dataclass(frozen=True)
class RiskApproved(Event):
    signal: Optional[Signal] = None
    assessment: Optional[RiskAssessment] = None


@dataclass(frozen=True)
class RiskRejected(Event):
    """A trade refused by a risk rule. Not a fault — the guard working."""

    signal: Optional[Signal] = None
    assessment: Optional[RiskAssessment] = None
    rule: str = ""
    reason: str = ""


@dataclass(frozen=True)
class RiskValidated(Event):
    """Retained for backwards compatibility with the phase-2 vocabulary.
    New code should publish RiskApproved or RiskRejected, which say which."""

    signal: Optional[Signal] = None
    assessment: Optional[RiskAssessment] = None


@dataclass(frozen=True)
class RiskBreached(Event):
    """A limit was hit — daily loss, exposure, drawdown. Distinct from
    RiskRejected: that refuses one trade, this reports the account-level state
    that may halt all of them."""

    rule: str = ""
    detail: str = ""
    halted: bool = False


# ── execution ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class OrderCreated(Event):
    """An order exists but has not left the building.

    Separate from OrderSubmitted so an order built and then dropped — by a
    crash, a guard, a bug — is distinguishable from one the venue never
    answered. Without both, the two failures look the same in a log.
    """

    order: Optional[Order] = None


@dataclass(frozen=True)
class OrderSubmitted(Event):
    order: Optional[Order] = None
    broker: str = ""


@dataclass(frozen=True)
class OrderAccepted(Event):
    """The venue acknowledged it. Working, not yet filled."""

    order: Optional[Order] = None
    broker_order_id: str = ""


@dataclass(frozen=True)
class OrderRejected(Event):
    """The venue refused it.

    Shares a name with the exception in ``tradexa.core.exceptions`` — the same
    fact in two registers, one raised at a call site and one broadcast to
    anyone listening. They live in different modules and are imported by
    different code; ``OrderRejectedEvent`` remains as an alias for callers that
    import both.
    """

    order: Optional[Order] = None
    reason: str = ""
    broker: str = ""


#: Backwards-compatible alias from the phase-2 vocabulary.
OrderRejectedEvent = OrderRejected


@dataclass(frozen=True)
class OrderFilled(Event):
    report: Optional[ExecutionReport] = None


# ── positions ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PositionOpened(Event):
    position: Optional[Position] = None
    strategy_id: str = ""


@dataclass(frozen=True)
class PositionUpdated(Event):
    """Size, stop or target changed on an open position — a scale-out, a
    trailing stop, a manual on-chart adjust."""

    position: Optional[Position] = None
    reason: str = ""


@dataclass(frozen=True)
class PositionClosed(Event):
    trade: Optional[Trade] = None


# ── portfolio & outcomes ────────────────────────────────────────────────────
@dataclass(frozen=True)
class PortfolioUpdated(Event):
    snapshot: Optional[PortfolioSnapshot] = None


@dataclass(frozen=True)
class TradeCompleted(Event):
    """A round trip finished and its result is known.

    Distinct from PositionClosed: closing is the mechanical event, completion
    is the accounting one. They are usually simultaneous and are not the same
    when a position closes in parts — several closes, one completed trade.
    """

    trade: Optional[Trade] = None
    r_multiple: Optional[float] = None


# ── faults ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ErrorOccurred(Event):
    """Something failed.

    Carries the exception TYPE name and message rather than the exception
    object: an event may be journalled, replayed and serialised, and a live
    exception holds tracebacks and frames that keep whole object graphs alive.
    """

    error: str = ""
    message: str = ""
    module: str = ""
    retryable: bool = False
    context: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_exception(cls, exc: BaseException, *, module: str = "",
                       **envelope: Any) -> "ErrorOccurred":
        as_dict = getattr(exc, "as_dict", None)
        ctx: dict[str, Any] = {}
        if callable(as_dict):
            try:
                ctx = dict(as_dict())
            except Exception:  # noqa: BLE001 — never fail while reporting a failure
                ctx = {}
        return cls(error=type(exc).__name__, message=str(exc), module=module,
                   retryable=bool(getattr(exc, "retryable", False)),
                   context=ctx, **envelope)


#: The complete vocabulary. Explicit rather than derived by subclass
#: introspection, so an event joins the public vocabulary only when someone
#: deliberately adds it — and ``EventRegistry`` has one place to read.
ALL_EVENTS: tuple[type[Event], ...] = (
    BotStarted, BotStopped,
    MarketDataReceived, CandleClosed,
    SignalGenerated, SignalRejected,
    RiskCheckStarted, RiskApproved, RiskRejected, RiskValidated, RiskBreached,
    OrderCreated, OrderSubmitted, OrderAccepted, OrderRejected, OrderFilled,
    PositionOpened, PositionUpdated, PositionClosed,
    PortfolioUpdated, TradeCompleted,
    ErrorOccurred,
)

__all__ = [
    "Event", "ENVELOPE_FIELDS", "new_id",
    "BotStarted", "BotStopped",
    "MarketDataReceived", "CandleClosed",
    "SignalGenerated", "SignalRejected",
    "RiskCheckStarted", "RiskApproved", "RiskRejected",
    "RiskValidated", "RiskBreached",
    "OrderCreated", "OrderSubmitted", "OrderAccepted", "OrderRejected",
    "OrderRejectedEvent", "OrderFilled",
    "PositionOpened", "PositionUpdated", "PositionClosed",
    "PortfolioUpdated", "TradeCompleted",
    "ErrorOccurred",
    "ALL_EVENTS",
]
