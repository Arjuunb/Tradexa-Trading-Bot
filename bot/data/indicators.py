"""Lightweight stdlib indicators used by risk sizing and trailing stops.

Kept tiny and dependency-free on purpose.
"""
from __future__ import annotations

from typing import Sequence

from bot.types import Bar


def true_range(prev_close: float, bar: Bar) -> float:
    """Wilder's True Range for a single bar."""
    return max(
        bar.high - bar.low,
        abs(bar.high - prev_close),
        abs(bar.low - prev_close),
    )


def atr(bars: Sequence[Bar], period: int = 14) -> float:
    """Simple-moving-average ATR over the last `period` bars.

    Returns 0.0 if we don't have enough history yet.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(bars) < period + 1:
        return 0.0
    trs: list[float] = []
    window = bars[-(period + 1):]
    for i in range(1, len(window)):
        trs.append(true_range(window[i - 1].close, window[i]))
    return sum(trs) / len(trs)
