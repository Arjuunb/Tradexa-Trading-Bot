"""Cash-accounting unit tests — assert PaperBroker equity to the cent."""
from datetime import datetime, timedelta, timezone

import pytest

from bot.brokers.paper import PaperBroker
from bot.types import Bar, Order, OrderType, Side


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
def _bar(i, o, h, l, c): return Bar(T0 + timedelta(hours=i), o, h, l, c, 100.0)
ZERO = dict(fee_bps=0.0, slippage_bps=0.0)


def test_long_win():
    """Buy 1 @100, sell 1 @110 -> equity = 1010, cash = 1010, no position."""
    b = PaperBroker(starting_cash=1000.0, **ZERO)
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    b.submit_order(Order("X", Side.SELL, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 110, 110, 110, 110))
    assert "X" not in b._positions
    assert round(b._cash, 6) == 1010.0
    assert round(b._equity, 6) == 1010.0


def test_long_loss():
    """Buy 1 @100, sell 1 @90 -> equity = 990."""
    b = PaperBroker(starting_cash=1000.0, **ZERO)
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    b.submit_order(Order("X", Side.SELL, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 90, 90, 90, 90))
    assert round(b._cash, 6) == 990.0
    assert round(b._equity, 6) == 990.0


def test_short_win():
    """Sell short 1 @100, cover @90 -> equity = 1010."""
    b = PaperBroker(starting_cash=1000.0, **ZERO)
    b.submit_order(Order("X", Side.SELL, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 90, 90, 90, 90))
    assert "X" not in b._positions
    assert round(b._cash, 6) == 1010.0
    assert round(b._equity, 6) == 1010.0


def test_short_loss():
    """Sell short 1 @100, cover @110 -> equity = 990."""
    b = PaperBroker(starting_cash=1000.0, **ZERO)
    b.submit_order(Order("X", Side.SELL, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 110, 110, 110, 110))
    assert round(b._cash, 6) == 990.0
    assert round(b._equity, 6) == 990.0


def test_position_flip():
    """Long 1 @100, then sell 2 @110 -> short 1 leftover from the flip.

    Realized on the long leg: (110 - 100) * 1 = +10 (closed portion).
    Remaining: short 1 unit at 110.
    """
    b = PaperBroker(starting_cash=1000.0, **ZERO)
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    b.submit_order(Order("X", Side.SELL, 2.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 110, 110, 110, 110))
    # cash: 1000 - 100 (buy) + 220 (sell 2 @110) = 1120
    # equity mark-to-market at last_price 110, short 1 @ avg 110: equity = 1120 - 1*110 = 1010
    assert round(b._cash, 6) == 1120.0
    pos = b._positions["X"]
    assert pos.qty == -1.0
    assert pos.avg_price == 110.0
    assert round(b._equity, 6) == 1010.0


def test_partial_close():
    """Long 2 @100, sell 1 @110 -> still long 1 with avg_price 100."""
    b = PaperBroker(starting_cash=1000.0, **ZERO)
    b.submit_order(Order("X", Side.BUY, 2.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    b.submit_order(Order("X", Side.SELL, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 110, 110, 110, 110))
    pos = b._positions["X"]
    assert pos.qty == 1.0
    assert pos.avg_price == 100.0     # remaining avg unchanged
    # cash: 1000 - 200 + 110 = 910; equity = 910 + 1*110 = 1020
    assert round(b._cash, 6) == 910.0
    assert round(b._equity, 6) == 1020.0


def test_add_to_position_vwaps():
    """Long 1 @100, then long another 1 @120 -> avg_price = 110."""
    b = PaperBroker(starting_cash=1000.0, **ZERO)
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 120, 120, 120, 120))
    pos = b._positions["X"]
    assert pos.qty == 2.0
    assert pos.avg_price == 110.0


def test_fees_debited_per_side():
    """5 bps fee each side -> total fee paid on round-trip = notional * 10 bps."""
    b = PaperBroker(starting_cash=1000.0, fee_bps=5.0, slippage_bps=0.0)
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    b.submit_order(Order("X", Side.SELL, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 100, 100, 100, 100))
    # Round-trip at flat price: gross PnL 0; fees: 100*0.0005 + 100*0.0005 = 0.10
    assert round(b._cash, 6) == 999.9
    assert round(b._equity, 6) == 999.9
