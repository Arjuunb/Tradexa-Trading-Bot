"""What the Risk Engine is given, and what it gives back.

The engine is a **pure function of its inputs**. It reads no database, calls no
exchange and imports no strategy. Everything a rule needs arrives in a
``RiskContext`` that the caller assembles.

That is the whole design. A risk engine that fetches its own state cannot be
tested at the edge cases that matter — a 19% drawdown, a margin call, an
account one tick from its daily limit — because reproducing those requires
manufacturing the state in a database first. Passing state in means every one
of those is a two-line test.

It also means the engine cannot be bypassed by accident: it has nothing to
consult except what it was handed, so a caller that skips it is visibly
skipping a step rather than quietly getting a different answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class TradeProposal:
    """A trade someone wants to make. Not yet approved, not yet sized.

    Deliberately has no ``qty``: size is the engine's output, not its input.
    Accepting a proposed size would invite a caller to compute one and have the
    engine merely wave it through — which is how sizing drifts from the rule
    that authorised it.
    """

    symbol: str
    direction: Direction
    entry: float
    stop: float
    target: Optional[float] = None
    confidence: float = 1.0
    strategy_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def stop_distance(self) -> float:
        """Absolute entry-to-stop distance — the denominator of every position
        size. Zero means the trade is unsizeable, not that it is free."""
        return abs(self.entry - self.stop)

    @property
    def risk_reward(self) -> Optional[float]:
        if self.target is None or not self.stop_distance:
            return None
        return abs(self.target - self.entry) / self.stop_distance

    @property
    def stop_is_valid(self) -> bool:
        """A stop on the wrong side of entry is not a stop — it is a target
        that would be hit immediately, and sizing from it produces a position
        the account cannot support."""
        if self.entry <= 0 or self.stop <= 0 or not self.stop_distance:
            return False
        return (self.stop < self.entry if self.direction is Direction.LONG
                else self.stop > self.entry)


@dataclass(frozen=True)
class OpenPosition:
    """An existing position, as risk needs to see it.

    Deliberately narrower than the trading ``Position`` model: risk cares about
    notional, direction and the risk still at stake, not about entry timestamps
    or broker ids. A narrow input is one fewer thing a test has to fabricate.
    """

    symbol: str
    direction: Direction
    qty: float
    entry: float
    stop: Optional[float] = None
    cluster: str = ""

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.entry

    @property
    def risk_amount(self) -> float:
        """Currency still at stake if the stop is hit. Zero when there is no
        stop — which is not "no risk", and callers that treat it as such are
        the reason ``max_account_risk`` reports unstopped positions separately."""
        if self.stop is None:
            return 0.0
        return abs(self.entry - self.stop) * abs(self.qty)


@dataclass(frozen=True)
class AccountState:
    """The account, at the instant of the decision."""

    equity: float
    #: Equity at the start of the day/period, for drawdown windows.
    starting_equity: float = 0.0
    #: The high-water mark, for peak-to-trough drawdown. Falls back to equity.
    peak_equity: float = 0.0
    cash: float = 0.0
    #: Margin currently committed. 0 on a cash account.
    used_margin: float = 0.0
    realized_pnl_today: float = 0.0
    realized_pnl_week: float = 0.0
    trades_today: int = 0

    def __post_init__(self) -> None:
        # Frozen, so defaults that depend on other fields are set via
        # object.__setattr__. Peak below equity would report a negative
        # drawdown, which reads as a gain and would disable the guard.
        if not self.peak_equity:
            object.__setattr__(self, "peak_equity", max(self.equity, 0.0))
        if not self.starting_equity:
            object.__setattr__(self, "starting_equity", self.equity)

    @property
    def drawdown_pct(self) -> float:
        """Peak-to-trough, as a fraction. Zero when at or above the peak."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    @property
    def free_margin(self) -> float:
        return max(0.0, self.equity - self.used_margin)


@dataclass(frozen=True)
class MarketConditions:
    """What the market is doing, as risk needs to see it."""

    #: ATR as a fraction of price. The regime measure sizing scales against.
    atr_pct: float = 0.0
    #: Minutes until the next scheduled high-impact event; None = none known.
    #: ``None`` and ``0`` mean different things and must not be conflated: no
    #: known event versus an event happening right now.
    minutes_to_news: Optional[float] = None
    spread_pct: float = 0.0
    #: Correlation cluster of the proposed symbol.
    cluster: str = ""


@dataclass(frozen=True)
class RiskContext:
    """Everything the engine needs. Assembled by the caller, read by the rules."""

    proposal: TradeProposal
    account: AccountState
    positions: Sequence[OpenPosition] = ()
    market: MarketConditions = field(default_factory=MarketConditions)
    #: Injected rather than read from the clock, so session and news rules are
    #: testable at a fixed instant and a backtest replaying 2019 gets the
    #: era-appropriate answer.
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: Set by an operator or a circuit breaker. Checked first, before anything
    #: else can argue its way past.
    kill_switch_engaged: bool = False
    kill_switch_reason: str = ""

    @property
    def gross_exposure(self) -> float:
        """Longs and shorts alike. A hedged book nets to zero and is still
        fully exposed; netting here would report a margin-callable position as
        flat."""
        return sum(p.notional for p in self.positions)

    @property
    def open_risk(self) -> float:
        return sum(p.risk_amount for p in self.positions)

    def positions_in_cluster(self, cluster: str,
                             direction: Optional[Direction] = None) -> list[OpenPosition]:
        return [p for p in self.positions
                if p.cluster == cluster
                and (direction is None or p.direction is direction)]

    def position_for(self, symbol: str) -> Optional[OpenPosition]:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None


__all__ = ["Direction", "TradeProposal", "OpenPosition", "AccountState",
           "MarketConditions", "RiskContext"]
