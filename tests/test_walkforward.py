"""Walk-forward validation: window slicing and out-of-sample correctness."""
from datetime import datetime, timedelta, timezone

from bot.strategies.support_resistance import SupportResistanceRejection
from bot.types import Bar
from bot.walkforward import walk_forward


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _make_bars(n):
    # synthetic random-walk
    import random
    random.seed(42)
    p = 100.0
    out = []
    for i in range(n):
        p *= 1 + random.uniform(-0.005, 0.005)
        hi = p * 1.003
        lo = p * 0.997
        out.append(Bar(T0 + timedelta(hours=i), p, hi, lo, p, 100.0))
    return out


def test_walkforward_produces_windows():
    bars = _make_bars(500)
    report = walk_forward(
        bars=bars,
        build_strategy=lambda train: SupportResistanceRejection("X", min_touches=1),
        train_bars=200, test_bars=100, step=100,
        starting_cash=10_000, fee_bps=0, slippage_bps=0,
    )
    # (500 - 200) // 100 = 3 windows
    assert len(report.windows) == 3
    for w in report.windows:
        assert w.train_end - w.train_start == 200
        assert w.test_end - w.test_start == 100
        assert "total_return" in w.result.metrics


def test_walkforward_robustness_check_runs():
    bars = _make_bars(400)
    report = walk_forward(
        bars=bars,
        build_strategy=lambda train: SupportResistanceRejection("X", min_touches=1),
        train_bars=200, test_bars=100,
        starting_cash=10_000, fee_bps=0, slippage_bps=0,
    )
    # Don't assert true/false (depends on synthetic data), just that it runs.
    is_ok = report.is_robust(min_sharpe=-999, max_dd=-1.0)
    assert isinstance(is_ok, bool)
