"""Synthetic data generator — determinism + invariants."""
import pytest

from bot.data.synthetic import generate_bars, write_csv


def test_generate_bars_is_deterministic_with_seed():
    a = generate_bars(50, "1h", seed=7)
    b = generate_bars(50, "1h", seed=7)
    assert [x.close for x in a] == [x.close for x in b]


def test_bars_satisfy_ohlc_invariant():
    bars = generate_bars(200, "1h", seed=11)
    for b in bars:
        assert b.high >= max(b.open, b.close)
        assert b.low <= min(b.open, b.close)
        assert b.low > 0
        assert b.volume >= 0


def test_generate_bars_param_validation():
    with pytest.raises(ValueError):
        generate_bars(0, "1h")
    with pytest.raises(ValueError):
        generate_bars(10, "bogus_tf")
    with pytest.raises(ValueError):
        generate_bars(10, "1h", vol_per_bar=0)


def test_write_csv_roundtrip(tmp_path):
    from bot.data.csv_loader import load_csv_bars
    bars = generate_bars(50, "1h", seed=3)
    p = tmp_path / "x.csv"
    write_csv(bars, str(p))
    loaded = load_csv_bars(str(p))
    assert len(loaded) == 50
    assert abs(loaded[0].close - bars[0].close) < 1e-4
