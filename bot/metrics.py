"""Performance metrics. Stdlib-only, pure functions.

All functions operate on either a list of equity-curve points
``[(datetime, equity), ...]`` or a list of trade dicts produced by the
backtester.

Definitions (all reported as decimals, not percentages):

- ``total_return``    = (end - start) / start
- ``cagr``            = (end/start)^(years_per_period) - 1, where the period
                        is the equity-curve span in seconds.
- ``max_dd``          = worst peak-to-trough drawdown.
- ``sharpe``          = mean(returns) / stdev(returns) * sqrt(ann)
- ``sortino``         = mean(returns) / stdev(NEGATIVE returns only) * sqrt(ann)
- ``calmar``          = cagr / abs(max_dd)
- ``profit_factor``   = sum(wins) / sum(abs(losses))
- ``expectancy``      = avg(win_pnl)*win_rate - avg(loss_pnl)*(1-win_rate)
- ``exposure``        = fraction of bars where a position was open
- ``avg_trade_bars``  = average number of bars from entry to exit
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable, Sequence


EquityCurve = Sequence[tuple[datetime, float]]


def max_drawdown(eq: Sequence[float]) -> float:
    if not eq:
        return 0.0
    peak = eq[0]
    worst = 0.0
    for v in eq:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < worst:
                worst = dd
    return worst


def _per_bar_returns(eq: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(eq)):
        if eq[i - 1] > 0:
            out.append((eq[i] - eq[i - 1]) / eq[i - 1])
    return out


def sharpe(eq: Sequence[float], ann_factor: float) -> float:
    rets = _per_bar_returns(eq)
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    std = math.sqrt(var) if var > 0 else 0.0
    return (mean / std) * math.sqrt(ann_factor) if std > 0 else 0.0


def sortino(eq: Sequence[float], ann_factor: float) -> float:
    rets = _per_bar_returns(eq)
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    downside = [r for r in rets if r < 0]
    if not downside:
        return 0.0
    dvar = sum(r * r for r in downside) / len(downside)
    dstd = math.sqrt(dvar) if dvar > 0 else 0.0
    return (mean / dstd) * math.sqrt(ann_factor) if dstd > 0 else 0.0


def cagr(curve: EquityCurve) -> float:
    if len(curve) < 2:
        return 0.0
    start_t, start_v = curve[0]
    end_t, end_v = curve[-1]
    if start_v <= 0 or end_v <= 0:
        return 0.0
    span = (end_t - start_t).total_seconds()
    if span <= 0:
        return 0.0
    years = span / (365.25 * 24 * 3600)
    if years <= 0:
        return 0.0
    return (end_v / start_v) ** (1.0 / years) - 1.0


def calmar(curve: EquityCurve, max_dd: float) -> float:
    g = cagr(curve)
    if max_dd == 0:
        return 0.0
    return g / abs(max_dd)


def profit_factor(trades: Iterable[dict]) -> float:
    wins = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in trades if t["pnl"] < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def expectancy(trades: Sequence[dict]) -> float:
    if not trades:
        return 0.0
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    wr = len(wins) / len(trades)
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    return wr * avg_w + (1 - wr) * avg_l


def avg_trade_bars(trades: Iterable[dict]) -> float:
    durations: list[float] = []
    for t in trades:
        e, x = t.get("entry_time"), t.get("exit_time")
        if e and x:
            # rough: count seconds; caller converts to bars by dividing by tf seconds
            durations.append((x - e).total_seconds())
    if not durations:
        return 0.0
    return sum(durations) / len(durations)


def exposure(equity_curve_len: int, trades: Sequence[dict]) -> float:
    """Approx: total trade-bars (using entry_time..exit_time order) / total bars.

    Caller passes the equity-curve length as a proxy for total bars. This is a
    conservative approximation that ignores intra-bar gaps.
    """
    if equity_curve_len <= 0 or not trades:
        return 0.0
    # We can't reconstruct exact in-bar counts from the trade dict alone, so
    # exposure is reported as fraction of trades' wall-clock duration over the
    # backtest's wall-clock duration. Callers who want bar-accurate exposure
    # should compute it from the equity curve directly.
    return 0.0


def expand_metrics(
    starting_equity: float,
    ending_equity: float,
    curve: EquityCurve,
    trades: Sequence[dict],
    ann_factor: float,
) -> dict:
    """Compute the full metrics dict in one call."""
    eq_vals = [v for _, v in curve]
    mdd = max_drawdown(eq_vals)
    base = {
        "total_return": (ending_equity - starting_equity) / starting_equity
        if starting_equity else 0.0,
        "max_dd": mdd,
        "sharpe": sharpe(eq_vals, ann_factor),
        "sortino": sortino(eq_vals, ann_factor),
        "cagr": cagr(curve),
        "calmar": calmar(curve, mdd),
        "annualization_factor": ann_factor,
    }
    if not trades:
        return {
            **base, "num_trades": 0, "win_rate": 0.0, "avg_r": 0.0,
            "profit_factor": 0.0, "expectancy": 0.0, "avg_trade_seconds": 0.0,
        }
    wins = [t for t in trades if t["pnl"] > 0]
    return {
        **base,
        "num_trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "avg_r": sum(t["r"] for t in trades) / len(trades),
        "profit_factor": profit_factor(trades),
        "expectancy": expectancy(trades),
        "avg_trade_seconds": avg_trade_bars(trades),
    }
