"""Smoke tests — make sure imports work, candles are detected, and a backtest
runs end-to-end on synthetic data without crashing.
"""
from datetime import datetime, timezone, timedelta

import pytest

from bot.backtester import Backtester
from bot.strategies import SupportResistanceRejection
from bot.types import Bar


def make_bar(t, o, h, l, c, v=100.0):
    return Bar(t, o, h, l, c, v)


def test_bullish_pin_detected():
    s = SupportResistanceRejection("X")
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    # body is small (100->101), but lower wick is huge (down to 90)
    s.bars = [make_bar(t, 100, 101.5, 90, 101)]
    assert s._bullish_pin(s.bars[0])


def test_bearish_engulfing_detected():
    s = SupportResistanceRejection("X")
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    s.bars = [
        make_bar(t, 100, 102, 99, 101),         # prev bullish
        make_bar(t + timedelta(hours=1), 102, 103, 98, 99),  # engulfing bearish
    ]
    assert s._bearish_engulf()


def test_backtest_runs_on_synthetic():
    from examples.run_backtest import synthetic_bars
    bars = synthetic_bars(500)
    strat = SupportResistanceRejection("BTC/USDT", pivot=3, min_touches=2)
    bt = Backtester(strat, bars, starting_cash=10_000)
    result = bt.run()
    assert result.starting_equity == 10_000
    assert isinstance(result.metrics, dict)
    assert "total_return" in result.metrics
