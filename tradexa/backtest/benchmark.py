"""Comparing a strategy against doing nothing.

The question a backtest cannot answer alone: a 60% return in a year the asset
rose 200% is not a good result, and a −5% year while it fell 40% is an excellent
one. Every figure here exists because absolute performance is uninterpretable
without the market it was earned in.

**Buy-and-hold is the benchmark that matters here**, not a bond index. The
alternative to running this strategy on BTC is holding BTC — that is the
decision the numbers should inform.

Reuses ``bot.metrics`` for the shared statistics, so a strategy's Sharpe in a
comparison is the same Sharpe the backtest report printed. Two definitions on
one page is how a comparison becomes an argument about methodology.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from bot.metrics import max_drawdown as _max_drawdown
from bot.metrics import sharpe as _sharpe

#: Annualisation basis. 365 for continuously-traded markets, matching the
#: portfolio engine — the two must agree or the same account reports two Sharpes.
DAYS_PER_YEAR = 365.0


def returns_of(series: Sequence[float]) -> list[float]:
    """Period-over-period fractional returns."""
    return [(series[i] - series[i - 1]) / series[i - 1]
            for i in range(1, len(series)) if series[i - 1] > 0]


def buy_and_hold(prices: Sequence[float], starting_equity: float) -> list[float]:
    """The equity curve of holding the asset from the first bar.

    Includes no costs, and that is deliberate: one entry and no exit is close
    enough to free that modelling it would add noise, and it makes the benchmark
    the *hardest* honest version of itself — a strategy that only beats a
    cost-laden benchmark has not beaten holding.
    """
    if not prices or prices[0] <= 0:
        return []
    units = starting_equity / prices[0]
    return [units * p for p in prices]


def beta(strategy: Sequence[float], market: Sequence[float]) -> Optional[float]:
    """Sensitivity to the benchmark. ``None`` when the market never moved."""
    n = min(len(strategy), len(market))
    if n < 2:
        return None
    s, m = strategy[:n], market[:n]
    mean_m = sum(m) / n
    variance = sum((x - mean_m) ** 2 for x in m) / n
    if variance <= 0:
        return None
    mean_s = sum(s) / n
    covariance = sum((s[i] - mean_s) * (m[i] - mean_m) for i in range(n)) / n
    return covariance / variance


def alpha(strategy: Sequence[float], market: Sequence[float],
          *, periods_per_year: float = DAYS_PER_YEAR) -> Optional[float]:
    """Annualised excess return after adjusting for market exposure.

    Beta-adjusted, not a raw difference: a strategy that is simply 2× levered
    long shows a large raw outperformance in a bull market and no alpha at all,
    and the distinction is the entire question.
    """
    b = beta(strategy, market)
    if b is None:
        return None
    n = min(len(strategy), len(market))
    mean_s = sum(strategy[:n]) / n
    mean_m = sum(market[:n]) / n
    return (mean_s - b * mean_m) * periods_per_year


def tracking_error(strategy: Sequence[float], market: Sequence[float],
                   *, periods_per_year: float = DAYS_PER_YEAR) -> Optional[float]:
    n = min(len(strategy), len(market))
    if n < 2:
        return None
    diffs = [strategy[i] - market[i] for i in range(n)]
    mean = sum(diffs) / n
    variance = sum((d - mean) ** 2 for d in diffs) / n
    return math.sqrt(variance) * math.sqrt(periods_per_year)


def information_ratio(strategy: Sequence[float], market: Sequence[float],
                      *, periods_per_year: float = DAYS_PER_YEAR) -> Optional[float]:
    """Excess return per unit of tracking error. ``None`` if it never deviated."""
    te = tracking_error(strategy, market, periods_per_year=periods_per_year)
    if not te:
        return None
    n = min(len(strategy), len(market))
    excess = (sum(strategy[:n]) / n - sum(market[:n]) / n) * periods_per_year
    return excess / te


def capture(strategy: Sequence[float], market: Sequence[float],
            *, upside: bool) -> Optional[float]:
    """Share of the benchmark's up (or down) moves the strategy participated in.

    The pair that tells you what kind of strategy this is. 80% upside with 30%
    downside is a different instrument from 120%/110%, even at the same total
    return, and the total return alone cannot distinguish them.
    """
    n = min(len(strategy), len(market))
    pairs = [(strategy[i], market[i]) for i in range(n)
             if (market[i] > 0 if upside else market[i] < 0)]
    if not pairs:
        return None
    market_sum = sum(m for _s, m in pairs)
    if market_sum == 0:
        return None
    return sum(s for s, _m in pairs) / market_sum


@dataclass(frozen=True)
class Comparison:
    """A strategy against its benchmark, with everything needed to judge it."""

    label: str
    benchmark_label: str
    strategy_return: float
    benchmark_return: float
    strategy_max_dd: float
    benchmark_max_dd: float
    strategy_sharpe: Optional[float] = None
    benchmark_sharpe: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    tracking_error: Optional[float] = None
    information_ratio: Optional[float] = None
    upside_capture: Optional[float] = None
    downside_capture: Optional[float] = None
    periods: int = 0
    notes: tuple[str, ...] = ()

    @property
    def excess_return(self) -> float:
        return self.strategy_return - self.benchmark_return

    @property
    def beat_benchmark(self) -> bool:
        return self.excess_return > 0

    @property
    def beat_on_risk(self) -> Optional[bool]:
        """Better return AND no worse drawdown.

        The question that matters more than the return alone: outperforming by
        taking twice the drawdown is not outperformance, it is leverage, and
        leverage is available to the benchmark too.
        """
        if self.strategy_max_dd is None or self.benchmark_max_dd is None:
            return None
        return self.beat_benchmark and self.strategy_max_dd <= self.benchmark_max_dd

    def explain(self) -> str:
        verdict = "beat" if self.beat_benchmark else "trailed"
        line = (f"{self.label} {verdict} {self.benchmark_label} by "
                f"{self.excess_return * 100:+.2f}% "
                f"({self.strategy_return * 100:+.2f}% vs "
                f"{self.benchmark_return * 100:+.2f}%)")
        if self.beat_on_risk is False and self.beat_benchmark:
            line += (f" — but with a deeper drawdown "
                     f"({self.strategy_max_dd * 100:.1f}% vs "
                     f"{self.benchmark_max_dd * 100:.1f}%)")
        return line

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "benchmark": self.benchmark_label,
                "strategy_return": self.strategy_return,
                "benchmark_return": self.benchmark_return,
                "excess_return": self.excess_return,
                "beat_benchmark": self.beat_benchmark,
                "beat_on_risk": self.beat_on_risk,
                "strategy_max_drawdown": self.strategy_max_dd,
                "benchmark_max_drawdown": self.benchmark_max_dd,
                "strategy_sharpe": self.strategy_sharpe,
                "benchmark_sharpe": self.benchmark_sharpe,
                "alpha": self.alpha, "beta": self.beta,
                "tracking_error": self.tracking_error,
                "information_ratio": self.information_ratio,
                "upside_capture": self.upside_capture,
                "downside_capture": self.downside_capture,
                "periods": self.periods, "notes": list(self.notes)}


def compare(equity: Sequence[float], prices: Sequence[float], *,
            label: str = "strategy", benchmark_label: str = "buy & hold",
            periods_per_year: float = DAYS_PER_YEAR) -> Comparison:
    """Compare a strategy's equity curve against buying and holding.

    Both curves start at the same capital, so the comparison is like for like:
    a benchmark normalised differently would make the excess return an artefact
    of the normalisation.
    """
    notes: list[str] = []
    if len(equity) < 2 or len(prices) < 2:
        return Comparison(label, benchmark_label, 0.0, 0.0, 0.0, 0.0,
                          notes=("not enough data to compare",))
    if len(equity) != len(prices):
        notes.append(f"curves differ in length ({len(equity)} vs {len(prices)}) "
                     "— compared over the shorter one")
    n = min(len(equity), len(prices))
    equity, prices = list(equity[:n]), list(prices[:n])
    bench = buy_and_hold(prices, equity[0])

    s_returns, b_returns = returns_of(equity), returns_of(bench)
    ann = math.sqrt(periods_per_year)
    if n < 30:
        notes.append(f"only {n} periods — alpha, beta and capture ratios are "
                     "indicative rather than evidence")

    return Comparison(
        label=label, benchmark_label=benchmark_label,
        strategy_return=(equity[-1] - equity[0]) / equity[0],
        benchmark_return=(bench[-1] - bench[0]) / bench[0],
        strategy_max_dd=abs(_max_drawdown(equity)),
        benchmark_max_dd=abs(_max_drawdown(bench)),
        strategy_sharpe=_sharpe(equity, ann) if len(equity) > 2 else None,
        benchmark_sharpe=_sharpe(bench, ann) if len(bench) > 2 else None,
        alpha=alpha(s_returns, b_returns, periods_per_year=periods_per_year),
        beta=beta(s_returns, b_returns),
        tracking_error=tracking_error(s_returns, b_returns,
                                      periods_per_year=periods_per_year),
        information_ratio=information_ratio(s_returns, b_returns,
                                            periods_per_year=periods_per_year),
        upside_capture=capture(s_returns, b_returns, upside=True),
        downside_capture=capture(s_returns, b_returns, upside=False),
        periods=n, notes=tuple(notes))


__all__ = ["DAYS_PER_YEAR", "returns_of", "buy_and_hold", "beta", "alpha",
           "tracking_error", "information_ratio", "capture", "Comparison",
           "compare"]
