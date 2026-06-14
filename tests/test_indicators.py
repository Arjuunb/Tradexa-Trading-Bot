"""EMA / RSI indicator tests."""
import pytest

from bot.data.indicators import ema, rsi


def test_ema_constant_series_is_constant():
    assert ema([5.0] * 10, 4)[-1] == pytest.approx(5.0)


def test_ema_tracks_and_lags_a_step():
    series = [0.0] * 5 + [10.0] * 50
    out = ema(series, 10)
    assert len(out) == len(series)
    assert out[5] < 10.0          # lags the jump
    assert out[-1] == pytest.approx(10.0, abs=0.1)  # converges


def test_ema_rejects_bad_period():
    with pytest.raises(ValueError):
        ema([1, 2, 3], 0)


def test_rsi_all_gains_is_100():
    assert rsi([float(i) for i in range(1, 30)], 14) == pytest.approx(100.0)


def test_rsi_all_losses_is_low():
    assert rsi([float(i) for i in range(30, 1, -1)], 14) < 1.0


def test_rsi_insufficient_history_is_neutral():
    assert rsi([1.0, 2.0, 3.0], 14) == 50.0


def test_rsi_bounded():
    import random
    r = random.Random(0)
    closes = [100.0]
    for _ in range(200):
        closes.append(closes[-1] * (1 + r.uniform(-0.02, 0.02)))
    v = rsi(closes, 14)
    assert 0.0 <= v <= 100.0
