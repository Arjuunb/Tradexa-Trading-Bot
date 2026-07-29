"""The Portfolio Engine.

Independent of the execution engine, by construction: it imports no broker, no
exchange client, no database and no web framework — only its own snapshot types
and the shared metric arithmetic. A test enforces that, because independence
claimed in a docstring is a convention, and a convention is what gets broken by
the first deadline.

The contract:

    state = engine.snapshot(portfolio)

    state.balance            settled cash across every venue
    state.equity             balance plus open P&L
    state.buying_power       what can still be deployed
    state.used_margin        committed, with free margin and margin level
    state.gross_exposure     open notional, gross and net, and as % of equity
    state.unrealized_pnl     open P&L, or None if any position is unmarked
    state.realized_pnl       booked P&L
    state.daily_return       today vs yesterday's close (UTC)
    state.monthly_return     this calendar month vs last month's close
    state.win_rate           fraction of closed trades in profit
    state.expectancy         average currency outcome per trade
    state.sharpe_ratio       annualised, from daily equity closes
    state.max_drawdown_pct   worst peak-to-trough decline

Every one of those thirteen is reported per venue as well as in aggregate, so
"the portfolio is down 4%" can always be resolved into which account did it.

Three properties are worth stating because they are deliberate.

**Multiple brokers and exchanges are the normal case, not a feature flag.** One
venue and nine take the same path. Nothing in the engine assumes a single
balance, because two exchanges genuinely do not share one.

**Unavailable is a value.** A missing mark, an unreachable venue, a currency
with no rate — each produces ``None`` and a note naming what is missing, never
a zero. A dashboard that cannot tell "flat" from "unknown" will report the
second as the first at exactly the wrong moment.

**The engine mutates nothing and holds no state.** Two calls on the same
portfolio return the same numbers, which is what makes a figure on a dashboard
reproducible after the fact.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from tradexa.portfolio import metrics
from tradexa.portfolio.snapshots import (
    ClosedTrade, Portfolio, VenueSnapshot, to_dict,
)

#: Below these sample sizes the corresponding figures are annotated rather than
#: withheld. Chosen as the smallest windows where the statistic stops being
#: dominated by a single observation: a month of daily marks, and enough trades
#: that one outlier cannot set the win rate.
MIN_SHARPE_DAYS = 20
MIN_TRADES = 10


@dataclass(frozen=True)
class VenueState:
    """One venue's contribution, converted into the portfolio's base currency."""

    venue: str
    kind: str
    currency: str
    balance: float
    equity: Optional[float]
    buying_power: Optional[float]
    used_margin: float
    free_margin: Optional[float]
    margin_level: Optional[float]
    gross_exposure: float
    net_exposure: float
    unrealized_pnl: Optional[float]
    realized_pnl: float
    position_count: int
    unmarked: tuple[str, ...] = ()
    reachable: bool = True
    #: Rate applied to convert into base currency. 1.0 when already in base.
    fx_rate: Optional[float] = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return to_dict(self.__dict__)


@dataclass(frozen=True)
class PortfolioState:
    """The whole book, at one instant."""

    at: datetime
    base_currency: str

    # ── capital ───────────────────────────────────────────────────────────
    balance: float = 0.0
    equity: Optional[float] = None
    buying_power: Optional[float] = None
    used_margin: float = 0.0
    free_margin: Optional[float] = None
    margin_level: Optional[float] = None

    # ── exposure ──────────────────────────────────────────────────────────
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    exposure_pct: Optional[float] = None
    exposure_by_symbol: dict[str, float] = field(default_factory=dict)
    exposure_by_venue: dict[str, float] = field(default_factory=dict)

    # ── P&L ───────────────────────────────────────────────────────────────
    unrealized_pnl: Optional[float] = None
    realized_pnl: float = 0.0

    # ── returns ───────────────────────────────────────────────────────────
    daily_return: Optional[float] = None
    monthly_return: Optional[float] = None

    # ── track record ──────────────────────────────────────────────────────
    win_rate: Optional[float] = None
    expectancy: Optional[float] = None
    profit_factor: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    trade_count: int = 0

    # ── provenance ────────────────────────────────────────────────────────
    per_venue: tuple[VenueState, ...] = ()
    #: Everything the caller should know about what is MISSING from the numbers
    #: above. Empty means the snapshot is whole.
    notes: tuple[str, ...] = ()
    sharpe_basis: str = ""
    computed_ms: float = 0.0

    @property
    def complete(self) -> bool:
        """Whether every figure above is derived from complete inputs."""
        return not self.notes

    @property
    def venue_count(self) -> int:
        return len(self.per_venue)

    def venue(self, name: str) -> Optional[VenueState]:
        for v in self.per_venue:
            if v.venue == name:
                return v
        return None

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe, with ``None`` preserved.

        ``available`` and ``notes`` travel WITH the numbers rather than in a
        separate call, so there is no version of this payload that carries the
        figures without the caveats attached to them.
        """
        data = to_dict({k: v for k, v in self.__dict__.items() if k != "per_venue"})
        data["per_venue"] = [v.as_dict() for v in self.per_venue]
        data["available"] = self.complete
        return data

    def explain(self) -> str:
        """One line for an operator."""
        eq = "unknown" if self.equity is None else f"{self.equity:,.2f}"
        parts = [f"{self.base_currency} {eq} equity across "
                 f"{self.venue_count} venue(s)",
                 f"exposure {self.gross_exposure:,.2f}"]
        if self.daily_return is not None:
            parts.append(f"today {self.daily_return*100:+.2f}%")
        if self.notes:
            parts.append(f"⚠ {len(self.notes)} caveat(s)")
        return " | ".join(parts)


class PortfolioEngine:
    """Computes portfolio state from a snapshot. Holds nothing between calls."""

    def __init__(self, *, periods_per_year: float = metrics.DAYS_PER_YEAR) -> None:
        #: Annualisation basis for Sharpe. 365 suits continuously-traded
        #: markets; an equities book should construct the engine with 252.
        self.periods_per_year = periods_per_year

    # ---------------------------------------------------------------- public
    def snapshot(self, portfolio: Portfolio) -> PortfolioState:
        """The only entry point. Pure: same portfolio in, same state out."""
        started = time.perf_counter()
        notes: list[str] = []

        venues = self._venue_states(portfolio, notes)
        capital = self._aggregate_capital(portfolio, venues, notes)
        trades = tuple(portfolio.closed_trades)
        curve = tuple(portfolio.equity_curve)

        equity = capital["equity"]
        gross = capital["gross_exposure"]

        if not curve:
            notes.append("no equity curve supplied — returns, Sharpe and "
                         "drawdown cannot be computed")
        else:
            # A Sharpe from a handful of days is arithmetic, not evidence. The
            # figure is still reported — suppressing a real calculation would be
            # its own dishonesty — but it is reported WITH its sample size, so
            # nobody reads a fortnight of luck as a track record.
            days = len(metrics.daily_closes(curve))
            if days < MIN_SHARPE_DAYS:
                notes.append(f"Sharpe and drawdown are computed from {days} daily "
                             f"observation(s); under {MIN_SHARPE_DAYS} the figures "
                             "are indicative, not a track record")
        if trades and len(trades) < MIN_TRADES:
            notes.append(f"win rate and expectancy are from {len(trades)} closed "
                         f"trade(s) — under {MIN_TRADES} they are not yet stable")

        return PortfolioState(
            at=portfolio.at,
            base_currency=portfolio.base_currency,
            balance=capital["balance"],
            equity=equity,
            buying_power=capital["buying_power"],
            used_margin=capital["used_margin"],
            free_margin=capital["free_margin"],
            margin_level=(equity / capital["used_margin"]
                          if capital["used_margin"] and equity is not None else None),
            gross_exposure=gross,
            net_exposure=capital["net_exposure"],
            exposure_pct=(gross / equity if equity else None),
            exposure_by_symbol=capital["by_symbol"],
            exposure_by_venue=capital["by_venue"],
            unrealized_pnl=capital["unrealized_pnl"],
            realized_pnl=capital["realized_pnl"],
            daily_return=metrics.daily_return(curve, portfolio.at),
            monthly_return=metrics.monthly_return(curve, portfolio.at),
            win_rate=metrics.win_rate(trades),
            expectancy=metrics.expectancy(trades),
            profit_factor=metrics.profit_factor(trades),
            sharpe_ratio=metrics.sharpe_ratio(curve, self.periods_per_year),
            max_drawdown_pct=metrics.max_drawdown_pct(curve),
            trade_count=len(trades),
            per_venue=venues,
            notes=tuple(notes),
            sharpe_basis=(f"daily equity closes, annualised ×√{self.periods_per_year:g}, "
                          "no risk-free rate subtracted"),
            computed_ms=(time.perf_counter() - started) * 1000,
        )

    def venue_breakdown(self, portfolio: Portfolio,
                        venue: str) -> Optional[PortfolioState]:
        """The same thirteen figures for ONE venue.

        Not a separate implementation — it narrows the portfolio to that venue
        and runs the identical path, so a per-venue figure can never disagree
        with the aggregate it belongs to. Trades and the equity curve are
        filtered to the venue where they carry one; an unattributed curve is
        passed through with a note rather than silently reused as if it
        described this venue alone.
        """
        target = portfolio.venue(venue)
        if target is None:
            return None
        trades = tuple(t for t in portfolio.closed_trades if t.venue == venue)
        attributed = any(t.venue for t in portfolio.closed_trades)
        state = self.snapshot(Portfolio(
            venues=(target,),
            equity_curve=portfolio.equity_curve,
            closed_trades=trades if attributed else (),
            base_currency=portfolio.base_currency,
            fx_rates=portfolio.fx_rates,
            at=portfolio.at))
        extra: list[str] = []
        if portfolio.equity_curve:
            extra.append(f"equity curve is portfolio-wide, not specific to "
                         f"'{venue}' — returns, Sharpe and drawdown describe "
                         "the whole book")
        if portfolio.closed_trades and not attributed:
            extra.append("closed trades carry no venue attribution — win rate "
                         "and expectancy omitted rather than misattributed")
        return PortfolioState(**{**state.__dict__,
                                 "notes": state.notes + tuple(extra)})

    # --------------------------------------------------------------- private
    def _venue_states(self, portfolio: Portfolio,
                      notes: list[str]) -> tuple[VenueState, ...]:
        out: list[VenueState] = []
        for v in portfolio.venues:
            rate = portfolio.rate_for(v.currency)
            if not v.reachable:
                notes.append(f"venue '{v.venue}' is unreachable — excluded from "
                             f"every total{f' ({v.note})' if v.note else ''}")
            elif rate is None:
                notes.append(f"venue '{v.venue}' holds {v.currency} and no "
                             f"{v.currency}/{portfolio.base_currency} rate was "
                             "supplied — excluded from every total")
            elif v.unmarked:
                notes.append(f"venue '{v.venue}' has unmarked position(s): "
                             f"{', '.join(v.unmarked)} — equity and unrealised "
                             "P&L are unavailable, exposure is marked at cost")
            out.append(self._convert(v, rate))
        return tuple(out)

    @staticmethod
    def _convert(v: VenueSnapshot, rate: Optional[float]) -> VenueState:
        """One venue in base currency. ``rate`` of ``None`` leaves the figures in
        the venue's own currency and flags them — converting with a guessed rate
        would be the one failure mode worse than not converting."""
        r = rate if rate is not None else 1.0
        scale = lambda x: None if x is None else x * r  # noqa: E731
        return VenueState(
            venue=v.venue, kind=v.kind.value, currency=v.currency,
            balance=v.cash * r,
            equity=scale(v.equity),
            buying_power=scale(v.buying_power),
            used_margin=v.used_margin * r,
            free_margin=scale(v.free_margin),
            # A ratio, not an amount — converting it would be wrong.
            margin_level=v.margin_level,
            gross_exposure=v.gross_exposure * r,
            net_exposure=v.net_exposure * r,
            unrealized_pnl=scale(v.unrealized_pnl),
            realized_pnl=v.realized_pnl * r,
            position_count=len(v.positions),
            unmarked=v.unmarked, reachable=v.reachable, fx_rate=rate,
            note=v.note)

    @staticmethod
    def _exposure_by_symbol(portfolio: Portfolio,
                            usable: set[str]) -> dict[str, float]:
        """Open notional per symbol, summed ACROSS venues.

        One symbol held on two exchanges is one exposure, and seeing it as two
        half-sized ones is the specific mistake a multi-venue book invites. This
        is the reason the portfolio needs an engine rather than a sum: no single
        venue can compute it.
        """
        out: dict[str, float] = {}
        for v in portfolio.venues:
            if v.venue not in usable:
                continue
            rate = portfolio.rate_for(v.currency) or 1.0
            for p in v.positions:
                out[p.symbol] = out.get(p.symbol, 0.0) + p.notional * rate
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def _aggregate_capital(self, portfolio: Portfolio,
                           venues: tuple[VenueState, ...],
                           notes: list[str]) -> dict[str, Any]:
        """Sum what can be summed. A venue that cannot be converted or reached
        contributes to nothing, including the denominators."""
        usable = [v for v in venues if v.reachable and v.fx_rate is not None]
        by_venue = {v.venue: v.gross_exposure for v in usable}
        by_symbol = self._exposure_by_symbol(portfolio, {v.venue for v in usable})

        unrealized: Optional[float] = 0.0
        for v in usable:
            if v.unrealized_pnl is None:
                unrealized = None
                break
            unrealized += v.unrealized_pnl

        equity: Optional[float] = None if unrealized is None else (
            sum(v.balance for v in usable) + unrealized)
        buying_power: Optional[float] = None
        if all(v.buying_power is not None for v in usable):
            buying_power = sum(v.buying_power or 0.0 for v in usable)
        free_margin: Optional[float] = None
        if all(v.free_margin is not None for v in usable):
            free_margin = sum(v.free_margin or 0.0 for v in usable)

        return {
            "balance": sum(v.balance for v in usable),
            "equity": equity,
            "buying_power": buying_power,
            "used_margin": sum(v.used_margin for v in usable),
            "free_margin": free_margin,
            "gross_exposure": sum(v.gross_exposure for v in usable),
            "net_exposure": sum(v.net_exposure for v in usable),
            "unrealized_pnl": unrealized,
            "realized_pnl": sum(v.realized_pnl for v in usable),
            "by_symbol": by_symbol,
            "by_venue": by_venue,
        }


__all__ = ["PortfolioEngine", "PortfolioState", "VenueState"]
