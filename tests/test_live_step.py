"""The incremental engine (step/finalize) must equal the batch run().

This is the guarantee that a strategy behaves identically backtested and live:
the live runner feeds bars through the same Backtester.step the batch loop uses.
"""
import pytest

from bot.backtester import Backtester
from bot.data.synthetic import generate_bars
from bot.strategies import SupportResistanceRejection


def _batch(bars):
    return Backtester(SupportResistanceRejection("X"), list(bars)).run()


def _incremental(bars):
    eng = Backtester(SupportResistanceRejection("X"), [])
    for bar in bars:
        eng.bars.append(bar)
        eng.step(bar)
    return eng.finalize()


def test_step_then_finalize_matches_run():
    bars = generate_bars(900, "1h", seed=7)
    a = _batch(bars)
    b = _incremental(bars)
    assert b.ending_equity == pytest.approx(a.ending_equity)
    assert len(b.trades) == len(a.trades)
    assert b.metrics["num_trades"] == a.metrics["num_trades"]
    assert b.metrics["sharpe"] == pytest.approx(a.metrics["sharpe"])
    assert b.metrics["max_dd"] == pytest.approx(a.metrics["max_dd"])


def test_current_metrics_available_midrun():
    bars = generate_bars(120, "1h", seed=2)
    eng = Backtester(SupportResistanceRejection("X"), [])
    for bar in bars[:60]:
        eng.bars.append(bar)
        eng.step(bar)
    m = eng.current_metrics()           # no finalize
    assert "sharpe" in m and "num_trades" in m
    assert len(eng.equity_curve) == 60
