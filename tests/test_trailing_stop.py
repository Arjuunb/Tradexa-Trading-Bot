"""Trailing-stop ratchet behavior in PaperBroker."""
from datetime import datetime, timedelta, timezone

from bot.backtester import Backtester
from bot.brokers.paper import PaperBroker
from bot.strategies.base import Strategy
from bot.types import Bar, Order, OrderType, Side, Signal, SignalType


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _bar(i, o, h, l, c):
    return Bar(T0 + timedelta(hours=i), o, h, l, c, 100.0)


def test_trail_pct_ratchets_up_on_long():
    """A 2% trailing stop should follow the high-water mark as price rises."""
    pb = PaperBroker(starting_cash=10_000, fee_bps=0, slippage_bps=0)
    pb.set_trail_pct("X", 0.02)
    pb.submit_order(Order(symbol="X", side=Side.BUY, qty=10,
                          order_type=OrderType.MARKET,
                          stop_loss=98.0))  # initial stop
    # Bar 0: order is in the queue, fills at open (100). High=101.
    pb.on_bar("X", _bar(0, 100, 101, 99, 100))
    br0 = pb._brackets["X"]
    assert br0.trail_pct == 0.02
    # Trail ratchet runs at end of bar: high_water=101 -> new_stop = 101*0.98 = 98.98
    # which beats the planned 98.0, so the bracket's stop is 98.98 going into bar 1.
    assert abs(br0.stop_loss - 98.98) < 1e-9

    # Bar 1: price climbs to 110. Trail stop should now be 110*0.98 = 107.8.
    pb.on_bar("X", _bar(1, 102, 110, 101, 109))
    assert pb._brackets["X"].stop_loss > 107.7

    # Bar 2: price pulls back to 108 — stop should NOT loosen.
    prev = pb._brackets["X"].stop_loss
    pb.on_bar("X", _bar(2, 109, 109, 108, 108))
    assert pb._brackets["X"].stop_loss == prev


def test_trail_stop_eventually_hits_and_closes():
    """Trail stop should exit on a sharp pullback after a run-up."""
    pb = PaperBroker(starting_cash=10_000, fee_bps=0, slippage_bps=0)
    pb.set_trail_pct("X", 0.02)
    pb.submit_order(Order(symbol="X", side=Side.BUY, qty=10,
                          order_type=OrderType.MARKET, stop_loss=90.0))
    pb.on_bar("X", _bar(0, 100, 100, 100, 100))     # fill at 100
    pb.on_bar("X", _bar(1, 100, 120, 99, 120))      # ratchet to 117.6
    fills = pb.on_bar("X", _bar(2, 120, 120, 115, 115))  # 115 < 117.6 -> stop hit
    assert any(pb.fill_role(f) == "exit" for f in fills)
    assert "X" not in pb._brackets
    # cash should reflect a profitable exit (entry 100, exit ~117.6, qty 10)
    assert pb.get_account().cash > 10_000


def test_trail_pct_ratchets_down_for_short():
    pb = PaperBroker(starting_cash=10_000, fee_bps=0, slippage_bps=0)
    pb.set_trail_pct("X", 0.02)
    pb.submit_order(Order(symbol="X", side=Side.SELL, qty=10,
                          order_type=OrderType.MARKET,
                          stop_loss=102.0))
    pb.on_bar("X", _bar(0, 100, 100, 99, 100))
    pb.on_bar("X", _bar(1, 99, 99, 90, 91))  # low_water = 90
    # Trail for short = low_water * (1 + 0.02) = 91.8 — tighter than 102.
    assert pb._brackets["X"].stop_loss < 92.0
