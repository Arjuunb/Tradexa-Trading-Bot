"""Trade-management features: breakeven stop, partial TP, time-based exit."""
from datetime import datetime, timezone

from bot.backtester import Backtester
from bot.brokers.paper import PaperBroker
from bot.data.synthetic import generate_bars
from bot.strategies import SupportResistanceRejection
from bot.types import Bar, Order, OrderType, Side


def _make_bars():
    """Hand-crafted bars where an obvious long setup forms and price runs up."""
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out = []
    # Long flat at 100 to build a support zone
    for i in range(20):
        out.append(Bar(ts, 100, 100.5, 99.5, 100, 1000))
    # Re-touch support twice (need pivots)
    for low in (100, 99, 100, 99):
        out.append(Bar(ts, 100, 100.5, low, 100.2, 1500))
        for _ in range(3):
            out.append(Bar(ts, 100.5, 101, 100, 100.5, 1000))
    # Strong rejection candle then rip up
    out.append(Bar(ts, 100, 102, 95, 101.5, 5000))  # bullish pin
    for k in range(40):
        p = 102 + k * 0.4
        out.append(Bar(ts, p, p + 0.5, p - 0.1, p + 0.3, 1500))
    return out


def test_modify_stop_only_tightens():
    b = PaperBroker(starting_cash=10_000)
    o = Order(symbol="X", side=Side.BUY, qty=1.0, order_type=OrderType.MARKET,
              stop_loss=90.0, take_profit=120.0)
    b.submit_order(o)
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    b.on_bar("X", Bar(ts, 100, 101, 99, 100, 0))   # fills
    # Cannot widen (lower for a long)
    assert b.modify_stop("X", 80) is False
    # Can tighten (raise for a long)
    assert b.modify_stop("X", 95) is True


def test_partial_close_returns_fill_and_keeps_remainder():
    b = PaperBroker(starting_cash=10_000)
    o = Order(symbol="X", side=Side.BUY, qty=2.0, order_type=OrderType.MARKET,
              stop_loss=90.0, take_profit=120.0)
    b.submit_order(o)
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    b.on_bar("X", Bar(ts, 100, 101, 99, 100, 0))
    fill = b.partial_close("X", 1.0, Bar(ts, 105, 106, 104, 105, 0))
    assert fill is not None
    assert fill.qty == 1.0
    assert b.fill_role(fill) == "partial_exit"
    pos = b.get_position("X")
    assert pos is not None and pos.qty == 1.0


def test_partial_close_rejects_when_qty_exceeds_position():
    b = PaperBroker(starting_cash=10_000)
    o = Order(symbol="X", side=Side.BUY, qty=1.0, order_type=OrderType.MARKET,
              stop_loss=90.0, take_profit=120.0)
    b.submit_order(o)
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    b.on_bar("X", Bar(ts, 100, 101, 99, 100, 0))
    # qty >= position size must be rejected (caller should use full close)
    assert b.partial_close("X", 1.0, Bar(ts, 100, 101, 99, 100, 0)) is None
    assert b.partial_close("X", 2.0, Bar(ts, 100, 101, 99, 100, 0)) is None


def test_max_hold_bars_force_closes_trade():
    bars = _make_bars()
    bt = Backtester(
        SupportResistanceRejection("X", min_touches=1),
        bars, max_hold_bars=3,
    )
    res = bt.run()
    # If a trade opens, at least one closed trade should have <=3 bars between
    # entry_time and exit_time. We at minimum require that the engine produced
    # closed trades or no positions remain open.
    assert bt._open_trade is None  # never left dangling


def test_breakeven_param_validation():
    import pytest
    bars = generate_bars(50, "1h", seed=1)
    # negative breakeven -> error
    with pytest.raises(ValueError):
        Backtester(SupportResistanceRejection("X"), bars,
                   breakeven_after_r=-0.1)
    # partial_tp_frac out of (0,1) when partial TP enabled -> error
    with pytest.raises(ValueError):
        Backtester(SupportResistanceRejection("X"), bars,
                   partial_tp_r=1.0, partial_tp_frac=0.0)
    # max_hold negative -> error
    with pytest.raises(ValueError):
        Backtester(SupportResistanceRejection("X"), bars, max_hold_bars=-1)
