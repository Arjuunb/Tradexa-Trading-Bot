"""Risk-manager and backtester-integration tests for the P0 fixes."""
from datetime import datetime, timedelta, timezone

from bot.risk import RiskConfig, RiskManager
from bot.types import AccountSnapshot, Signal, SignalType


def _sig(t):
    return Signal(timestamp=t, symbol="X", type=SignalType.LONG,
                  entry=100, stop_loss=99, take_profit=102)


def test_cooldown_counts_bars_not_signals():
    """After a losing trade, the next 5 bars block trades regardless of how
    many or how few signals arrive. The 6th bar should allow a trade again.
    """
    rm = RiskManager(RiskConfig(cooldown_bars_after_loss=5))
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    acct = AccountSnapshot(cash=10_000, equity=10_000, positions=[])

    # Anchor day with first bar.
    rm.on_bar(10_000, t0)
    # Simulate a closed losing trade -> sets cooldown to 5.
    rm.on_trade_closed(-50.0, t0)
    assert rm.state.cooldown_left == 5

    # Five bars pass with NO signals. Cooldown must still decrement each bar.
    for i in range(1, 6):
        rm.on_bar(10_000, t0 + timedelta(hours=i))
    assert rm.state.cooldown_left == 0

    # On the 6th bar, a new signal must be allowed.
    rm.on_bar(10_000, t0 + timedelta(hours=6))
    allow, qty, reason = rm.evaluate(_sig(t0 + timedelta(hours=6)), acct,
                                     t0 + timedelta(hours=6))
    assert allow, f"Expected trade allowed after cooldown, got: {reason}"


def test_cooldown_blocks_during_window():
    rm = RiskManager(RiskConfig(cooldown_bars_after_loss=3))
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rm.on_bar(10_000, t0)
    rm.on_trade_closed(-25.0, t0)
    # Bar 1: cooldown still active.
    rm.on_bar(10_000, t0 + timedelta(hours=1))
    allow, _, reason = rm.evaluate(
        _sig(t0 + timedelta(hours=1)),
        AccountSnapshot(cash=10_000, equity=10_000, positions=[]),
        t0 + timedelta(hours=1),
    )
    assert not allow
    assert "Cooldown" in reason


def test_daily_loss_anchors_at_day_start_not_first_signal():
    """The kill switch must fire on equity below 97% of the DAY'S OPEN, not
    of the equity at the first signal of the day.
    """
    rm = RiskManager(RiskConfig(max_daily_loss_pct=0.03))
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    # Day starts at equity 10_000 — anchored on the first bar.
    rm.on_bar(10_000, t0)
    # Equity drifts up to 10_500 before any signal arrives.
    for i in range(1, 4):
        rm.on_bar(10_500, t0 + timedelta(hours=i))
    # Now equity drops to 9_700 — that is -3% from 10_000 (the true day open).
    acct = AccountSnapshot(cash=9_700, equity=9_700, positions=[])
    rm.on_bar(9_700, t0 + timedelta(hours=5))
    allow, _, reason = rm.evaluate(_sig(t0 + timedelta(hours=5)), acct,
                                   t0 + timedelta(hours=5))
    assert not allow
    assert "Daily loss" in reason


def test_daily_loss_resets_next_day():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=0.03))
    d1 = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    d2 = datetime(2025, 1, 2, 9, tzinfo=timezone.utc)
    rm.on_bar(10_000, d1)
    # Drop equity 4% — kill switch active.
    rm.on_bar(9_600, d1 + timedelta(hours=1))
    acct = AccountSnapshot(cash=9_600, equity=9_600, positions=[])
    allow, _, _ = rm.evaluate(_sig(d1 + timedelta(hours=1)), acct,
                              d1 + timedelta(hours=1))
    assert not allow
    # New day — anchor resets to current equity.
    rm.on_bar(9_600, d2)
    acct2 = AccountSnapshot(cash=9_600, equity=9_600, positions=[])
    allow2, _, reason = rm.evaluate(_sig(d2), acct2, d2)
    assert allow2, reason


def test_max_open_positions_blocks():
    rm = RiskManager(RiskConfig(max_open_positions=2))
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rm.on_bar(10_000, t)
    from bot.types import Position
    acct = AccountSnapshot(
        cash=5_000, equity=10_000,
        positions=[Position("A", 1, 100), Position("B", 1, 100)],
    )
    allow, _, reason = rm.evaluate(_sig(t), acct, t)
    assert not allow
    assert "Max open" in reason


def test_notional_cap():
    rm = RiskManager(RiskConfig(risk_per_trade_pct=0.5, max_position_pct=0.1))
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rm.on_bar(10_000, t)
    acct = AccountSnapshot(cash=10_000, equity=10_000, positions=[])
    sig = Signal(timestamp=t, symbol="X", type=SignalType.LONG,
                 entry=100, stop_loss=99, take_profit=102)
    allow, qty, _ = rm.evaluate(sig, acct, t)
    assert allow
    # Without cap, qty would be 10000*0.5/1 = 5000. Cap at 10% of equity = 1000$ -> qty = 10.
    assert qty == 10.0
