"""get_bars must honour the timeframe it is asked for.

The bundled sample CSVs are 1h candles. Before this, the sample branch returned
them unchanged for ANY requested timeframe, so a "4h strategy" silently ran on
1h candles and the multi-timeframe sweep compared a series against itself.
"""
import pytest

import data.market_data as md
from data.market_data import get_bars


@pytest.fixture(autouse=True)
def _force_bundled_sample(request, monkeypatch):
    """Pin the sample tests to the bundled-sample branch.

    get_bars prefers the local synced store, and other tests in the suite write
    to it. Without this these tests would skip or silently measure a different
    source depending on test order.

    Tests marked ``uses_store`` are exercising the store path itself, so they
    must NOT have it stubbed out from under them."""
    if request.node.get_closest_marker("uses_store"):
        return
    monkeypatch.setattr(md, "_from_local_store", lambda *a, **k: None)


def _spacing_s(bars):
    return (bars[1].timestamp - bars[0].timestamp).total_seconds()


@pytest.mark.parametrize("tf,secs", [("1h", 3600), ("4h", 14400), ("1d", 86400)])
def test_requested_timeframe_is_the_delivered_timeframe(tf, secs):
    bars, src = get_bars("BTCUSDT", n=2000, timeframe=tf)
    assert bars, f"{tf} returned nothing"
    assert _spacing_s(bars) == secs, f"{tf} bars are spaced {_spacing_s(bars)}s apart"


def test_the_sweeps_integrity_check_now_passes_for_every_timeframe():
    """This is the check that caught the bug. It must now be satisfied, not
    merely tolerated."""
    from services.strategy_sweep import timeframe_matches
    for tf in ("1h", "4h", "1d"):
        bars, _ = get_bars("BTCUSDT", n=2000, timeframe=tf)
        assert timeframe_matches(bars, tf), tf


def _sample(tf, n=5000):
    bars, src = get_bars("BTCUSDT", n=n, timeframe=tf)
    assert src == "bundled sample", src
    return bars


def test_higher_timeframes_yield_proportionally_fewer_candles():
    h, f = _sample("1h"), _sample("4h")
    assert abs(len(f) - len(h) / 4) <= 1, "4h should be a quarter of the 1h count"


def test_aggregated_candles_are_aligned_to_exchange_buckets():
    assert all(b.timestamp.hour % 4 == 0 for b in _sample("4h", n=200))


def test_a_timeframe_finer_than_the_sample_falls_through_rather_than_faking_it():
    """1h data cannot produce 15m candles. The sample branch must decline and let
    the next source answer, with a source string that says what it really is."""
    bars, src = get_bars("BTCUSDT", n=500, timeframe="15m")
    assert src != "bundled sample"
    if bars:
        assert _spacing_s(bars) == 900, "whatever answered must still honour 15m"


def test_the_daily_series_is_real_history_not_a_relabelled_hourly_one():
    d, h = _sample("1d"), _sample("1h")
    assert len(d) < len(h) / 20
    # a daily candle's range must span the hourly candles inside it exactly
    assert max(b.high for b in d) == max(b.high for b in h)
    assert min(b.low for b in d) == min(b.low for b in h)


# ------------------------------------------------- real synced data wins

def _seed_store(tmp_path, monkeypatch, *, tf="1h", n=1200, name="market.db"):
    """A local store holding real-shaped candles at one timeframe."""
    from datetime import datetime, timedelta, timezone
    from data.historical import HistoricalStore
    import config

    db = str(tmp_path / name)
    store = HistoricalStore(db)
    t0 = datetime(2021, 1, 1, tzinfo=timezone.utc)
    step = {"1h": timedelta(hours=1)}[tf]
    store.upsert(symbol="BTCUSDT", timeframe=tf, rows=[
        (int((t0 + step * i).timestamp() * 1000),
         100.0 + i, 102.0 + i, 99.0 + i, 101.0 + i, 5.0)
        for i in range(n)])

    class _Settings:
        market_db = db
    monkeypatch.setattr(config, "settings", _Settings, raising=False)
    return db


@pytest.mark.uses_store
def test_a_coarser_timeframe_is_aggregated_from_real_synced_candles(tmp_path, monkeypatch):
    """One /data/sync at 1h must also answer 4h. Otherwise asking for 4h after
    syncing 1h silently swaps REAL data for the demo sample."""
    _seed_store(tmp_path, monkeypatch)
    import data.market_data as md
    got = md._from_local_store("BTCUSDT", 200, "4h", None)
    assert got, "1h real candles should have answered the 4h request"
    assert (got[1].timestamp - got[0].timestamp).total_seconds() == 14400
    assert got[0].timestamp.hour % 4 == 0


@pytest.mark.uses_store
def test_the_exact_timeframe_is_still_preferred_when_it_exists(tmp_path, monkeypatch):
    _seed_store(tmp_path, monkeypatch)
    import data.market_data as md
    got = md._from_local_store("BTCUSDT", 200, "1h", None)
    assert (got[1].timestamp - got[0].timestamp).total_seconds() == 3600


@pytest.mark.uses_store
def test_the_store_is_not_asked_to_upsample(tmp_path, monkeypatch):
    """15m cannot be built from 1h. The store must decline rather than return
    hourly candles wearing a 15m label."""
    _seed_store(tmp_path, monkeypatch, n=600, name="m.db")
    import data.market_data as md
    assert md._from_local_store("BTCUSDT", 200, "15m", None) is None


@pytest.mark.uses_store
def test_too_little_synced_history_declines_rather_than_aggregating_noise(tmp_path, monkeypatch):
    _seed_store(tmp_path, monkeypatch, n=40, name="tiny.db")
    import data.market_data as md
    assert md._from_local_store("BTCUSDT", 200, "4h", None) is None
