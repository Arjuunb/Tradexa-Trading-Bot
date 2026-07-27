"""OHLC resampling.

Contract: aggregating N candles into one is EXACT, it refuses anything that
would require inventing price action, and the candles it produces line up with
the buckets a real exchange uses.
"""
from datetime import datetime, timedelta, timezone

from bot.data.resample import (
    can_resample, infer_timeframe, resample, tf_seconds, to_timeframe,
)
from bot.types import Bar


def _hourly(n, start="2020-01-01T00:00:00+00:00", base=100.0):
    t0 = datetime.fromisoformat(start)
    return [Bar(timestamp=t0 + timedelta(hours=i),
                open=base + i, high=base + i + 2, low=base + i - 1,
                close=base + i + 1, volume=10.0 + i)
            for i in range(n)]


# ------------------------------------------------------------------ inference

def test_hourly_data_is_recognised_as_hourly():
    assert infer_timeframe(_hourly(50)) == "1h"


def test_a_single_gap_does_not_fool_the_detector():
    """Real feeds have holes. A mean would be dragged by one long outage; the
    median is not."""
    bars = _hourly(40)
    shifted = [Bar(timestamp=b.timestamp + timedelta(days=5), open=b.open,
                   high=b.high, low=b.low, close=b.close, volume=b.volume)
               for b in bars[20:]]
    assert infer_timeframe(bars[:20] + shifted) == "1h"


def test_too_few_bars_to_have_a_spacing():
    assert infer_timeframe(_hourly(2)) is None
    assert infer_timeframe([]) is None


def test_an_unknown_spacing_is_none_not_a_guess():
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    odd = [Bar(timestamp=t0 + timedelta(seconds=137 * i), open=1, high=1,
               low=1, close=1, volume=1) for i in range(10)]
    assert infer_timeframe(odd) is None


# -------------------------------------------------------------- what is legal

def test_whole_multiples_only():
    assert can_resample("1h", "4h") is True
    assert can_resample("1h", "1d") is True
    assert can_resample("4h", "1d") is True          # x6
    assert can_resample("1h", "1h") is True
    assert can_resample("4h", "6h") is False, "6h is not a whole multiple of 4h"
    assert can_resample("1h", "15m") is False, "that would be upsampling"
    assert can_resample("1h", "nonsense") is False
    assert can_resample(None, "4h") is False


# ------------------------------------------------------------- the arithmetic

def test_four_hourly_candles_become_one_exact_four_hour_candle():
    bars = _hourly(4)
    out = resample(bars, "4h")
    assert len(out) == 1
    c = out[0]
    assert c.open == bars[0].open, "open is the FIRST candle's open"
    assert c.close == bars[-1].close, "close is the LAST candle's close"
    assert c.high == max(b.high for b in bars)
    assert c.low == min(b.low for b in bars)
    assert c.volume == sum(b.volume for b in bars)


def test_candles_align_to_exchange_boundaries():
    """A 4h candle starts at 00:00 / 04:00 / 08:00 UTC. Anything else would not
    match a chart the trader can check the result against."""
    out = resample(_hourly(48), "4h")
    assert all(c.timestamp.hour % 4 == 0 for c in out)
    assert all(c.timestamp.minute == 0 for c in out)


def test_data_starting_mid_bucket_still_aligns():
    """Starting at 02:00 must not produce candles at 02:00/06:00/10:00 — the
    first partial bucket is dropped and the rest land on real boundaries."""
    out = resample(_hourly(24, start="2020-01-01T02:00:00+00:00"), "4h")
    assert out and all(c.timestamp.hour % 4 == 0 for c in out)
    assert out[0].timestamp.hour == 4, "the incomplete 00:00 bucket is dropped"


def test_an_incomplete_trailing_candle_is_dropped():
    """Six hourly candles make ONE complete 4h candle, not two — the last two
    hours are a bar the market has not closed."""
    out = resample(_hourly(6), "4h")
    assert len(out) == 1


def test_a_day_of_hourly_data_is_one_daily_candle():
    out = resample(_hourly(24), "1d")
    assert len(out) == 1
    assert out[0].timestamp.hour == 0


def test_resampling_to_the_same_timeframe_is_a_no_op():
    bars = _hourly(10)
    assert [b.close for b in resample(bars, "1h")] == [b.close for b in bars]


def test_upsampling_returns_nothing_rather_than_inventing_candles():
    assert resample(_hourly(24), "15m") == []


def test_no_bars_in_no_bars_out():
    assert resample([], "4h") == []


def test_the_full_series_is_conserved():
    """96 hourly candles -> exactly 24 four-hour candles, with the first open
    and last close preserved end to end."""
    bars = _hourly(96)
    out = resample(bars, "4h")
    assert len(out) == 24
    assert out[0].open == bars[0].open
    assert out[-1].close == bars[-1].close
    assert out[0].timestamp == bars[0].timestamp


def test_naive_timestamps_are_handled_without_crashing():
    t0 = datetime(2020, 1, 1)
    bars = [Bar(timestamp=t0 + timedelta(hours=i), open=1.0, high=2.0,
                low=0.5, close=1.5, volume=1.0) for i in range(8)]
    out = resample(bars, "4h")
    assert len(out) == 2
    assert out[0].timestamp.tzinfo is None, "naive in, naive out"


# ------------------------------------------------------------------ the note

def test_a_successful_conversion_says_what_it_did():
    out, note = to_timeframe(_hourly(48), "4h")
    assert len(out) == 12
    assert "resampled 48 1h candles into 12 4h candles" == note


def test_an_impossible_conversion_explains_itself_and_returns_nothing():
    out, note = to_timeframe(_hourly(48), "15m")
    assert out == []
    assert "inventing price action" in note


def test_a_non_multiple_conversion_explains_itself():
    out, note = to_timeframe(_hourly(48), "1w")
    # 1w IS a multiple of 1h (168), so use a genuine non-multiple instead
    assert out or note
    bars4h = resample(_hourly(96), "4h")
    out, note = to_timeframe(bars4h, "6h")
    assert out == [] and "not a whole multiple" in note


def test_too_little_data_for_one_candle_says_so():
    out, note = to_timeframe(_hourly(3, start="2020-01-01T01:00:00+00:00"), "1d")
    assert out == []
    assert "not enough" in note


def test_matching_timeframe_is_reported_as_such():
    out, note = to_timeframe(_hourly(10), "1h")
    assert len(out) == 10 and note == "already 1h"


def test_unknown_source_returns_bars_untouched_and_says_so():
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    odd = [Bar(timestamp=t0 + timedelta(seconds=137 * i), open=1, high=1,
               low=1, close=1, volume=1) for i in range(10)]
    out, note = to_timeframe(odd, "4h")
    assert len(out) == 10 and "could not be determined" in note


def test_tf_seconds_is_case_and_space_tolerant():
    assert tf_seconds(" 4H ") == 14400
    assert tf_seconds("bogus") is None
