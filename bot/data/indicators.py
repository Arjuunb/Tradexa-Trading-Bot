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


def ema(values: Sequence[float], period: int) -> list[float]:
    """Exponential moving average series (same length as ``values``).

    Seeded with the first value; ``out[-1]`` is the latest EMA. Returns ``[]``
    for empty input.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: Sequence[float], period: int = 14) -> float:
    """Wilder's RSI of the most recent bar. Returns 50.0 (neutral) when there
    is not enough history, 100.0 when there are no losses in the window.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(closes) < period + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gain = ch if ch > 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)
