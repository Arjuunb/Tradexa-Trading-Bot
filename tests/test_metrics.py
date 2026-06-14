"""Pure-function tests for bot.metrics."""
from datetime import datetime, timedelta, timezone

from bot.metrics import (
    cagr, calmar, expand_metrics, expectancy, max_drawdown,
    profit_factor, sharpe, sortino,
)


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def test_max_drawdown_known_curve():
    # 100 -> 110 -> 80 -> 90: peak 110, trough 80 -> -27.27%
    assert abs(max_drawdown([100, 110, 80, 90]) - (-0.27272727)) < 1e-6


def test_sharpe_positive_for_monotonic_growth():
    eq = [100 * (1.001 ** i) for i in range(100)]
    s = sharpe(eq, ann_factor=8760)
    assert s > 0


def test_sortino_treats_only_downside():
    eq = [100, 101, 99, 102, 100]
    so = sortino(eq, ann_factor=8760)
    sh = sharpe(eq, ann_factor=8760)
    # Sortino normally >= Sharpe when upside vol dominates.
    assert so >= sh - 1e-9


def test_cagr_one_year_doubled():
    curve = [(T0, 100.0), (T0 + timedelta(days=365), 200.0)]
    g = cagr(curve)
    assert abs(g - 1.0) < 0.01  # ~100% CAGR


def test_calmar_basic():
    curve = [(T0, 100.0), (T0 + timedelta(days=365), 110.0)]
    c = calmar(curve, max_dd=-0.05)
    assert c > 0


def test_profit_factor():
    trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": -30}, {"pnl": -20}]
    assert abs(profit_factor(trades) - 3.0) < 1e-9


def test_profit_factor_all_wins():
    assert profit_factor([{"pnl": 10}, {"pnl": 5}]) == float("inf")


def test_expectancy_known():
    trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": -50}, {"pnl": 100}]
    # avg_w=100, avg_l=-50, wr=0.5 -> 0.5*100 + 0.5*-50 = 25
    assert abs(expectancy(trades) - 25.0) < 1e-9


def test_expand_metrics_returns_all_keys():
    curve = [(T0 + timedelta(hours=i), 100.0 + i) for i in range(10)]
    trades = [{"pnl": 10, "r": 1.0, "entry_time": T0,
               "exit_time": T0 + timedelta(hours=2)}]
    m = expand_metrics(100, 109, curve, trades, ann_factor=8760)
    for k in ("total_return", "max_dd", "sharpe", "sortino", "cagr", "calmar",
              "profit_factor", "expectancy", "num_trades", "win_rate", "avg_r"):
        assert k in m, f"missing metric: {k}"
