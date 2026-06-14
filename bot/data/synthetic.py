"""Stdlib-only synthetic OHLCV generator.

Used by tests, demos, and the bundled sample CSVs so the CLI runs out of
the box without any network or external data dependency. We generate a
geometric Brownian motion close-to-close, then derive open/high/low/volume
around it.

Determinism: ``seed`` makes every output bit-for-bit reproducible. The
generator uses Python's ``random.Random`` directly so it has no NumPy /
SciPy dependency.

Realism trade-offs
------------------
- Returns are i.i.d. log-normal — no fat tails, no autocorrelation,
  no overnight gaps. Good enough for engine smoke tests, not for serious
  backtests.
- We add a *trend* term so the series isn't a pure martingale, which lets
  trend filters actually do something useful.
- High/low are sampled as ``close * (1 +/- |N|)`` so they always bracket
  the close.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from bot.types import Bar


# Step seconds per common timeframe label.
_TF_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def generate_bars(
    n: int = 2000,
    timeframe: str = "1h",
    start_price: float = 100.0,
    drift_per_bar: float = 0.0002,
    vol_per_bar: float = 0.008,
    start_ts: Optional[datetime] = None,
    seed: int = 42,
) -> list[Bar]:
    """Generate ``n`` synthetic OHLCV bars.

    Parameters
    ----------
    n: number of bars to produce (must be > 0).
    timeframe: bar interval; one of '1m','5m','15m','30m','1h','4h','1d'.
    start_price: opening price of bar 0.
    drift_per_bar: log-return drift per bar; positive = uptrend.
    vol_per_bar: log-return stdev per bar.
    start_ts: UTC datetime of bar 0 (defaults to 2020-01-01 UTC).
    seed: PRNG seed for reproducibility.
    """
    if n <= 0:
        raise ValueError("n must be > 0")
    if timeframe not in _TF_SECONDS:
        raise ValueError(f"unsupported timeframe {timeframe!r}")
    if vol_per_bar <= 0:
        raise ValueError("vol_per_bar must be > 0")
    if start_price <= 0:
        raise ValueError("start_price must be > 0")

    rng = random.Random(seed)
    step = timedelta(seconds=_TF_SECONDS[timeframe])
    ts = start_ts or datetime(2020, 1, 1, tzinfo=timezone.utc)
    price = start_price
    bars: list[Bar] = []
    for _ in range(n):
        # log-return
        r = rng.gauss(drift_per_bar, vol_per_bar)
        new_close = price * math.exp(r)
        bar_open = price
        bar_close = new_close
        # high/low jitter so candles look realistic and rejection patterns
        # can actually form.
        wick = abs(rng.gauss(0, vol_per_bar)) * price
        bar_high = max(bar_open, bar_close) + wick
        bar_low = min(bar_open, bar_close) - wick
        if bar_low <= 0:
            bar_low = min(bar_open, bar_close) * 0.99
        # Volume: log-normal around 1000, weakly correlated with absolute return.
        vol = abs(rng.gauss(1000.0, 200.0)) + abs(r) * 50_000
        bars.append(Bar(
            timestamp=ts, open=bar_open, high=bar_high,
            low=bar_low, close=bar_close, volume=vol,
        ))
        price = new_close
        ts = ts + step
    return bars


def write_csv(bars: list[Bar], path: str) -> None:
    """Write ``bars`` to ``path`` as ``timestamp,open,high,low,close,volume``."""
    import csv
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([
                b.timestamp.isoformat(),
                f"{b.open:.6f}",
                f"{b.high:.6f}",
                f"{b.low:.6f}",
                f"{b.close:.6f}",
                f"{b.volume:.4f}",
            ])
