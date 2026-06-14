"""ATR-based stop widening in RiskManager."""
from datetime import datetime, timedelta, timezone

from bot.risk import RiskConfig, RiskManager
from bot.types import AccountSnapshot, Signal, SignalType


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _signal(entry, sl):
    return Signal(timestamp=T0, symbol="X", type=SignalType.LONG,
                  entry=entry, stop_loss=sl, take_profit=entry + 2.0)


def test_atr_widens_stop_when_implied_atr_stop_is_wider():
    """If ATR-derived stop is wider than the signal's stop, qty must shrink."""
    cfg = RiskConfig(atr_stop_mult=2.0)  # opt-in
    rm = RiskManager(cfg)
    rm.on_bar(10_000, T0)

    # Baseline: no ATR feed yet -> sizing uses signal stop (entry-sl = 1)
    sig = _signal(entry=100.0, sl=99.0)
    acct = AccountSnapshot(cash=10_000, equity=10_000, positions=[])
    allow, qty_no_atr, _ = rm.evaluate(sig, acct, T0)
    assert allow

    # Now feed an ATR of 5.0 -> ATR-stop = 2*5 = 10, much wider than 1
    rm.update_atr(5.0)
    allow, qty_atr, _ = rm.evaluate(sig, acct, T0)
    assert allow
    assert qty_atr < qty_no_atr, "ATR sizing must be MORE conservative"
    # qty = risk_dollars / atr_stop = 100 / 10 = 10
    assert abs(qty_atr - 10.0) < 1e-9


def test_atr_does_not_loosen_a_wider_signal_stop():
    """If signal's stop is already wider than ATR-stop, signal stop wins."""
    cfg = RiskConfig(atr_stop_mult=2.0)
    rm = RiskManager(cfg)
    rm.on_bar(10_000, T0)
    rm.update_atr(0.1)  # very tight ATR

    sig = _signal(entry=100.0, sl=95.0)  # 5-pt stop
    acct = AccountSnapshot(cash=10_000, equity=10_000, positions=[])
    allow, qty, _ = rm.evaluate(sig, acct, T0)
    assert allow
    # qty = 100 / 5 = 20  (signal stop, not ATR's 0.2-pt stop)
    assert abs(qty - 20.0) < 1e-9


def test_atr_sizing_off_by_default():
    """Default config: atr_stop_mult = 0, ATR feed must have no effect.

    With atr_stop_mult=0 and signal stop = 1, raw qty = risk_dollars / 1 = 100,
    but the 25% notional cap then trims it to 10_000 * 0.25 / 100 = 25.
    What matters for this test is that the cap-trimmed qty is identical with
    or without an ATR feed.
    """
    rm = RiskManager(RiskConfig())
    rm.on_bar(10_000, T0)
    sig = _signal(entry=100, sl=99)
    acct = AccountSnapshot(cash=10_000, equity=10_000, positions=[])
    allow1, qty_no_atr, _ = rm.evaluate(sig, acct, T0)
    rm.update_atr(99999.0)  # absurd ATR — should be ignored when atr_stop_mult=0
    allow2, qty_with_atr, _ = rm.evaluate(sig, acct, T0)
    assert allow1 and allow2
    assert abs(qty_no_atr - qty_with_atr) < 1e-9
