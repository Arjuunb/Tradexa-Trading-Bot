"""OHLC resampling — turn candles of one size into candles of a larger size.

The bundled sample data is 1-hour candles. Every caller that asked ``get_bars``
for 4h or 1d got those 1h candles back unchanged, because the sample branch
ignored the timeframe argument entirely. Nothing downstream could detect it, so
a "4h strategy" was silently a 1h strategy, and the multi-timeframe sweep was
comparing a series against itself.

This module is the fix. Aggregating N consecutive candles into one is exact —
open of the first, high of the highest, low of the lowest, close of the last,
volume summed — so a 4h candle built from four real 1h candles IS the real 4h
candle, not an approximation.

Four rules keep it honest:

  * **Downsample only.** 1h -> 4h is aggregation. 1h -> 15m would require
    inventing price action inside an hour nobody recorded, so it is refused
    rather than interpolated.
  * **Whole multiples only.** 1h -> 4h (x4) and 4h -> 1d (x6) work; a target
    that is not an integer multiple of the source would produce candles
    straddling boundaries and is refused.
  * **Aligned to real boundaries.** A 4h candle starts at 00:00, 04:00, 08:00
    UTC — the same buckets every exchange uses — not at whatever offset the data
    happens to begin. Unaligned candles would not match any chart a trader can
    check the result against.
  * **No partial trailing candle.** A bucket missing some of its source candles
    is a candle that has not finished forming. Emitting it would let a strategy
    trade on a bar the market has not closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from bot.types import Bar

# Seconds per timeframe label. Mirrors bot.data.synthetic so the two agree on
# what "4h" means.
TF_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
    "1w": 604800,
}


def tf_seconds(timeframe: str) -> Optional[int]:
    return TF_SECONDS.get((timeframe or "").strip().lower())


def infer_timeframe(bars: Sequence[Bar]) -> Optional[str]:
    """The candle size a bar series actually has, from the gaps between bars.

    Uses the MEDIAN gap, not the mean: real market data has holes (exchange
    downtime, listing gaps) and a single large gap would drag a mean far enough
    to misidentify the series. Returns None when the series is too short to have
    a spacing, or when the spacing matches no known timeframe."""
    if len(bars) < 3:
        return None
    gaps = []
    for a, b in zip(bars, bars[1:]):
        try:
            g = (b.timestamp - a.timestamp).total_seconds()
        except (AttributeError, TypeError):
            return None
        if g > 0:
            gaps.append(g)
    if len(gaps) < 2:
        return None
    gaps.sort()
    median = gaps[len(gaps) // 2]
    for label, secs in TF_SECONDS.items():
        if abs(median - secs) <= max(1.0, secs * 0.02):
            return label
    return None


def _bucket_start(ts: datetime, secs: int) -> datetime:
    """The start of the aligned bucket containing ``ts``.

    Anchored to the Unix epoch in UTC, which is what every exchange's daily and
    4-hourly candles are anchored to."""
    aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    epoch = int(aware.timestamp())
    start = epoch - (epoch % secs)
    out = datetime.fromtimestamp(start, tz=timezone.utc)
    return out if ts.tzinfo else out.replace(tzinfo=None)


def can_resample(source_tf: Optional[str], target_tf: Optional[str]) -> bool:
    """True only when ``target`` is a whole multiple of ``source``. Equal
    timeframes are trivially fine (nothing to do)."""
    s, t = tf_seconds(source_tf or ""), tf_seconds(target_tf or "")
    if not s or not t:
        return False
    return t >= s and t % s == 0


def resample(bars: Sequence[Bar], target_tf: str,
             source_tf: Optional[str] = None) -> list[Bar]:
    """Aggregate ``bars`` into ``target_tf`` candles.

    Returns [] when the conversion is not a legitimate aggregation — the caller
    must then report that the timeframe is unavailable rather than pass off the
    source candles as the target."""
    if not bars:
        return []
    src = source_tf or infer_timeframe(bars)
    if not can_resample(src, target_tf):
        return []
    s, t = tf_seconds(src), tf_seconds(target_tf)
    if s == t:
        return list(bars)

    per_bucket = t // s
    out: list[Bar] = []
    cur: list[Bar] = []
    cur_start: Optional[datetime] = None

    def _flush() -> None:
        # Only complete buckets: a bucket short of its source candles is a
        # candle still forming, and trading on it would be trading on a bar the
        # market has not closed.
        if cur_start is not None and len(cur) == per_bucket:
            out.append(Bar(
                timestamp=cur_start,
                open=cur[0].open,
                high=max(b.high for b in cur),
                low=min(b.low for b in cur),
                close=cur[-1].close,
                volume=sum((b.volume or 0.0) for b in cur),
            ))

    for b in bars:
        start = _bucket_start(b.timestamp, t)
        if cur_start is None or start != cur_start:
            _flush()
            cur, cur_start = [b], start
        else:
            cur.append(b)
    _flush()
    return out


def to_timeframe(bars: Sequence[Bar], target_tf: str) -> tuple[list[Bar], str]:
    """``(bars, note)`` — resample if needed, and say plainly what happened.

    The note is the point: a caller that cannot deliver the requested candle
    size gets a sentence explaining why, instead of silently returning the wrong
    candles."""
    if not bars:
        return [], "no bars"
    src = infer_timeframe(bars)
    if src is None:
        return list(bars), "source timeframe could not be determined; bars returned as-is"
    if src == target_tf:
        return list(bars), f"already {target_tf}"
    if not can_resample(src, target_tf):
        s, t = tf_seconds(src), tf_seconds(target_tf)
        if s and t and t < s:
            return [], (f"cannot build {target_tf} candles from {src} data — that would "
                        "mean inventing price action inside a candle nobody recorded")
        return [], (f"cannot build {target_tf} candles from {src} data — "
                    f"{target_tf} is not a whole multiple of {src}")
    out = resample(bars, target_tf, source_tf=src)
    if not out:
        return [], f"not enough {src} data to form a single complete {target_tf} candle"
    return out, f"resampled {len(bars)} {src} candles into {len(out)} {target_tf} candles"
