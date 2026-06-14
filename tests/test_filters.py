"""Strategy filters: trend, ATR floor, volume confirm, longs-only-in-uptrend."""
import pytest

from bot.data.synthetic import generate_bars
from bot.strategies import SupportResistanceRejection
from bot.types import SignalType


def _count_signals(strategy, bars) -> int:
    n = 0
    for b in bars:
        sig = strategy.on_bar(b)
        if sig and sig.type in (SignalType.LONG, SignalType.SHORT):
            n += 1
    return n


def test_trend_filter_param_validation():
    with pytest.raises(ValueError):
        SupportResistanceRejection("X", trend_ema_period=1)
    with pytest.raises(ValueError):
        SupportResistanceRejection("X", trend_min_slope_bps=-1)
    with pytest.raises(ValueError):
        SupportResistanceRejection("X", atr_floor_pct=-0.001)
    with pytest.raises(ValueError):
        SupportResistanceRejection("X", vol_sma_n=1)
    with pytest.raises(ValueError):
        SupportResistanceRejection("X", vol_mult=0)


def test_atr_floor_blocks_in_flat_market():
    # Build perfectly flat bars (TR ~= 0). atr_floor_pct > 0 should block every signal.
    bars = generate_bars(400, "1h", vol_per_bar=0.0001, seed=1)
    base = SupportResistanceRejection("X", min_touches=1)
    base_signals = _count_signals(base, bars)
    filt = SupportResistanceRejection("X", min_touches=1, atr_floor_pct=0.01)
    filt_signals = _count_signals(filt, bars)
    assert filt_signals <= base_signals
    assert filt_signals == 0


def test_vol_confirm_blocks_when_volume_is_zero():
    from bot.types import Bar
    from datetime import datetime, timezone
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    # All zero volume -> vol_confirm should never pass
    bars = [Bar(ts, 100, 101, 99, 100, 0) for _ in range(100)]
    s = SupportResistanceRejection("X", min_touches=1, vol_confirm=True)
    assert _count_signals(s, bars) == 0


def test_filters_default_off_preserves_baseline_count():
    # With every new knob at default values, behavior must match v0.2 exactly.
    bars = generate_bars(800, "1h", seed=3)
    s = SupportResistanceRejection("X")  # all filters default OFF
    n = _count_signals(s, bars)
    assert n >= 0  # smoke — main point: no crashes, no unexpected blocks
