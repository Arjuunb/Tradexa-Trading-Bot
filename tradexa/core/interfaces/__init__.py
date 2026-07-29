"""Ports — the contracts business logic depends on.

Everything here is a ``typing.Protocol``, not an ABC. That is the load-bearing
choice: the live ``bot.brokers.base.Broker`` and ``bot.strategies.base.Strategy``
are already ABCs with real subclasses in production, and requiring them to also
inherit from something in ``tradexa`` would mean editing every implementation
to satisfy a refactor. Protocols are structural — an existing class satisfies
one by having the right methods, with no import and no edit. Working code keeps
working, and new code can still type against the port.

``@runtime_checkable`` is applied so ``isinstance`` works for wiring checks,
with the usual caveat that it verifies method *names* and not signatures.

Dependency rule: these interfaces are stated in terms of domain models only.
No ccxt client, no SQL connection, no HTTP response, no FastAPI type appears in
a signature — otherwise the "interface" would simply relocate the coupling.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Optional, Protocol, runtime_checkable

from tradexa.core.models import (
    AccountSnapshot,
    Bar,
    ExecutionReport,
    Order,
    PortfolioSnapshot,
    Position,
    RiskAssessment,
    Signal,
    StrategyResult,
    Trade,
)


# ── market data ─────────────────────────────────────────────────────────────
@runtime_checkable
class MarketDataProvider(Protocol):
    """Where bars come from — a live exchange, a cache, a synthetic generator.

    ``get_bars`` returns the bars AND the source that produced them. The source
    is not decoration: a live-mode engine served bundled sample data will never
    see a new candle, and without the provenance travelling beside the data
    that failure is invisible until someone asks why nothing has traded.
    """

    def get_bars(self, symbol: str, timeframe: str, limit: int) -> tuple[list[Bar], str]:
        """Return ``(bars, source)``, oldest first. ``source`` starts with
        ``"live"`` only when the data genuinely came from a live venue."""
        ...


@runtime_checkable
class StreamingMarketDataProvider(MarketDataProvider, Protocol):
    """A provider that can also push. Separate from ``MarketDataProvider``
    because most callers only need polling, and requiring every provider to
    implement a stream would force fakes to grow methods nobody calls."""

    def stream_bars(self, symbol: str, timeframe: str) -> Iterable[Bar]:
        ...


# ── execution ───────────────────────────────────────────────────────────────
@runtime_checkable
class Broker(Protocol):
    """Order placement and account state.

    Structurally compatible with the existing ``bot.brokers.base.Broker`` ABC,
    so live brokers satisfy this without modification.
    """

    @property
    def name(self) -> str: ...

    def submit_order(self, order: Order) -> str: ...

    def cancel_order(self, order_id: str) -> None: ...

    def get_account(self) -> AccountSnapshot: ...

    def get_position(self, symbol: str) -> Optional[Position]: ...


@runtime_checkable
class ExecutionEngine(Protocol):
    """Turns an APPROVED order into an execution report.

    Takes ``RiskAssessment`` alongside the order rather than trusting the
    caller: execution must be unable to place a trade risk never approved, and
    the only way to guarantee that structurally is to require the approval as
    an argument.
    """

    def execute(self, order: Order, assessment: RiskAssessment) -> ExecutionReport:
        ...


# ── strategy ────────────────────────────────────────────────────────────────
@runtime_checkable
class Strategy(Protocol):
    """Consumes bars, may emit a signal.

    Structurally compatible with ``bot.strategies.base.Strategy``.
    """

    name: str

    def on_bar(self, bar: Bar) -> Optional[Signal]: ...


@runtime_checkable
class EvaluatingStrategy(Protocol):
    """A strategy that explains itself.

    ``evaluate`` returns a ``StrategyResult`` — including the "no signal, and
    here is why" case that ``on_bar`` can only express as ``None``. Kept
    separate so existing strategies remain valid ``Strategy`` implementations
    without being forced to grow this method.
    """

    def evaluate(self, bar: Bar) -> StrategyResult: ...


@runtime_checkable
class StrategyFactory(Protocol):
    """Builds a strategy for a symbol. The engine holds one of these rather
    than a strategy instance, because a multi-symbol run needs one independent
    instance per symbol — shared indicator state across pairs is a silent
    correctness bug, not a performance detail."""

    def __call__(self, symbol: str, **params: Any) -> Strategy: ...


# ── risk ────────────────────────────────────────────────────────────────────
@runtime_checkable
class RiskManager(Protocol):
    """Approves, resizes or refuses proposed trades.

    Returns a ``RiskAssessment`` rather than a bool so the approved size
    travels with the approval. Sizing computed anywhere else can drift from the
    rule that authorised it.
    """

    def assess(self, signal: Signal, portfolio: PortfolioSnapshot) -> RiskAssessment:
        ...

    def is_halted(self) -> bool:
        """True when a circuit breaker has tripped. Checked before assessment
        so a halt cannot be argued past by a well-sized trade."""
        ...


# ── portfolio ───────────────────────────────────────────────────────────────
@runtime_checkable
class PortfolioManager(Protocol):
    """Owns account, positions and realised results."""

    def snapshot(self) -> PortfolioSnapshot: ...

    def apply_trade(self, trade: Trade) -> None: ...

    def open_positions(self) -> list[Position]: ...


# ── infrastructure ports ────────────────────────────────────────────────────
@runtime_checkable
class EventBus(Protocol):
    """Publish/subscribe within the process.

    ``publish`` never raises on a subscriber's behalf: one failing listener
    must not abort a fill being recorded. Implementations isolate handler
    errors and report them out of band.
    """

    def publish(self, event: Any) -> None: ...

    def subscribe(self, event_type: type, handler: Callable[[Any], None]) -> Callable[[], None]:
        """Register ``handler``; returns a callable that unsubscribes it."""
        ...


@runtime_checkable
class Logger(Protocol):
    """Structured logging. ``**context`` rather than pre-formatted strings, so
    a log line can be queried by field instead of grepped."""

    def info(self, event: str, /, **context: Any) -> None: ...
    def warning(self, event: str, /, **context: Any) -> None: ...
    def error(self, event: str, /, **context: Any) -> None: ...


@runtime_checkable
class Storage(Protocol):
    """Durable key/value persistence, stated without reference to SQL, files or
    any particular engine, so the domain cannot acquire a database dependency
    by using it."""

    def get(self, key: str) -> Optional[Any]: ...
    def put(self, key: str, value: Any) -> None: ...
    def delete(self, key: str) -> None: ...


@runtime_checkable
class Clock(Protocol):
    """Time as a dependency.

    A backtest replaying 2019 and a live loop must both ask the same question
    and get the era-appropriate answer. Code that calls ``datetime.now()``
    directly cannot be tested at a fixed instant, which is how time-dependent
    logic ends up with flaky tests.
    """

    def now(self) -> datetime: ...


__all__ = [
    "MarketDataProvider", "StreamingMarketDataProvider",
    "Broker", "ExecutionEngine",
    "Strategy", "EvaluatingStrategy", "StrategyFactory",
    "RiskManager", "PortfolioManager",
    "EventBus", "Logger", "Storage", "Clock",
]
