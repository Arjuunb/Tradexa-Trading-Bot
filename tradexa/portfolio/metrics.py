"""Portfolio mathematics. Pure functions over the snapshot types.

Nothing here reads a clock, a database or a broker. Every function takes what
it needs and returns a number or ``None`` — never a plausible zero standing in
for an answer it does not have.

**The arithmetic that already existed is reused, not restated.** Drawdown,
Sharpe and expectancy come from ``bot.metrics``, which the backtester and the
live pipeline already use. A second implementation would agree on the day it
was written and drift on the first bug fix, and a portfolio page disagreeing
with the backtest report about the same account's Sharpe is worse than either
number being absent.

What is genuinely new here is everything the existing helpers do not cover:
calendar-window returns, resampling an irregular equity curve to daily closes,
and the multi-venue aggregation the whole engine exists for.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Optional, Sequence

from bot.metrics import expectancy as _expectancy
from bot.metrics import max_drawdown as _max_drawdown
from bot.metrics import sharpe as _sharpe

from tradexa.portfolio.snapshots import ClosedTrade, EquityPoint

#: Trading periods per year for annualising a daily Sharpe. 365 rather than 252
#: because this platform's primary markets are crypto, which do not close at the
#: weekend. Overridable per call — an equities-only book should pass 252, and
#: the difference is ~18% on the reported figure, which is not a rounding
#: detail.
DAYS_PER_YEAR = 365.0


# ── equity curve handling ───────────────────────────────────────────────────

def _sorted(curve: Sequence[EquityPoint]) -> list[EquityPoint]:
    """Chronological order, imposed rather than assumed.

    Callers assemble curves from ledgers and broker histories, and an
    out-of-order point silently inverts a return: peak-to-trough drawdown read
    off a shuffled curve is meaningless in a way that produces no error.
    """
    return sorted(curve, key=lambda p: p.at)


def daily_closes(curve: Sequence[EquityPoint]) -> list[tuple[date, float]]:
    """The LAST equity observation of each UTC day.

    Returns are computed day over day, so an unresampled curve would make Sharpe
    a function of how often the caller happened to sample — an account polled
    every minute would report a different ratio from the same account polled
    hourly, with no change in performance.
    """
    by_day: dict[date, tuple[datetime, float]] = {}
    for p in _sorted(curve):
        day = p.at.astimezone(timezone.utc).date()
        prev = by_day.get(day)
        if prev is None or p.at >= prev[0]:
            by_day[day] = (p.at, p.equity)
    return [(d, by_day[d][1]) for d in sorted(by_day)]


def _equity_at_or_before(curve: Sequence[EquityPoint],
                         moment: datetime) -> Optional[float]:
    """The last observation no later than ``moment``, or ``None``.

    ``None`` rather than the earliest available point: an account opened on
    Tuesday has no Monday equity, and substituting Tuesday's would report a
    day's return of exactly zero for a day that never happened.
    """
    prior = [p for p in _sorted(curve) if p.at <= moment]
    return prior[-1].equity if prior else None


def window_return(curve: Sequence[EquityPoint],
                  since: datetime) -> Optional[float]:
    """Fractional return from the last observation before ``since`` to the latest.

    The baseline is the point BEFORE the window opens — the closing equity of
    the previous period — because a return measured from the first point inside
    the window silently discards everything that happened overnight.
    """
    ordered = _sorted(curve)
    if not ordered:
        return None
    base = _equity_at_or_before(ordered, since)
    if base is None or base <= 0:
        return None
    return (ordered[-1].equity - base) / base


def daily_return(curve: Sequence[EquityPoint],
                 now: Optional[datetime] = None) -> Optional[float]:
    """Today's return, measured from yesterday's closing equity (UTC)."""
    now = now or datetime.now(timezone.utc)
    midnight = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0,
                                                    microsecond=0)
    return window_return(curve, midnight)


def monthly_return(curve: Sequence[EquityPoint],
                   now: Optional[datetime] = None) -> Optional[float]:
    """This calendar month's return, from last month's closing equity.

    Calendar month, not a trailing 30 days. They differ, and a figure labelled
    "monthly return" next to a month name has to be the one the label claims.
    """
    now = now or datetime.now(timezone.utc)
    first = now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0,
                                                 second=0, microsecond=0)
    return window_return(curve, first)


def max_drawdown_pct(curve: Sequence[EquityPoint]) -> Optional[float]:
    """Worst peak-to-trough decline, as a POSITIVE fraction.

    ``bot.metrics.max_drawdown`` returns it negative (a drawdown is a fall).
    Flipped once, here, rather than at each of the display sites that would
    otherwise each decide a sign.
    """
    if len(curve) < 2:
        return None
    return abs(_max_drawdown([p.equity for p in _sorted(curve)]))


def sharpe_ratio(curve: Sequence[EquityPoint],
                 periods_per_year: float = DAYS_PER_YEAR) -> Optional[float]:
    """Annualised Sharpe from daily equity closes, or ``None``.

    ``None`` — not 0.0 — below two daily observations. Zero is a real Sharpe
    meaning "no risk-adjusted edge"; a new account has not earned that verdict.

    Excess return over a risk-free rate is not subtracted, matching the rest of
    the platform's Sharpe figures. That makes it comparable with the backtest
    report, and it is the basis the engine states in its output.
    """
    closes = daily_closes(curve)
    if len(closes) < 2:
        return None
    return _sharpe([e for _, e in closes], math.sqrt(periods_per_year))


# ── trade-derived statistics ────────────────────────────────────────────────

def win_rate(trades: Sequence[ClosedTrade]) -> Optional[float]:
    """Fraction of closed trades that made money. ``None`` with no trades.

    Break-even trades count as losses, matching ``bot.metrics.expectancy``,
    which splits on ``pnl > 0``. Two definitions of "win" across one page is how
    a win rate and an expectancy stop reconciling.
    """
    if not trades:
        return None
    return sum(1 for t in trades if t.is_win) / len(trades)


def expectancy(trades: Sequence[ClosedTrade]) -> Optional[float]:
    """Average currency outcome per trade, via the shared implementation."""
    if not trades:
        return None
    return _expectancy([{"pnl": t.pnl} for t in trades])


def realized_pnl(trades: Sequence[ClosedTrade]) -> float:
    return sum(t.pnl for t in trades)


def profit_factor(trades: Sequence[ClosedTrade]) -> Optional[float]:
    """Gross wins over gross losses. ``None`` when nothing has lost yet — the
    ratio is undefined there, and reporting infinity as a score flatters a
    three-trade record into looking flawless."""
    if not trades:
        return None
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    if losses <= 0:
        return None
    return sum(t.pnl for t in trades if t.pnl > 0) / losses


__all__ = ["DAYS_PER_YEAR", "daily_closes", "window_return", "daily_return",
           "monthly_return", "max_drawdown_pct", "sharpe_ratio", "win_rate",
           "expectancy", "realized_pnl", "profit_factor"]
