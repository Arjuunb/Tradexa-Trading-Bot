"""Regression tests that pinned down the bugs before they were fixed.

Each test corresponds to a numbered bug in the audit. They should all pass
after the fix.
"""
from datetime import datetime, timedelta, timezone

from bot.brokers.paper import PaperBroker
from bot.types import Bar, Order, OrderType, Side


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _bar(i, o, h, l, c, v=100.0):
    return Bar(T0 + timedelta(hours=i), o, h, l, c, v)


def test_bug2_close_pnl_cash_math_is_correct():
    """Buy 1 unit @100, sell 1 unit @110 -> realized PnL = +10.

    Before the fix the paper broker booked +20 (PnL double-counted via
    `cash += realized` then `cash -= ... - realized`).
    """
    b = PaperBroker(starting_cash=1000.0, fee_bps=0.0, slippage_bps=0.0)
    # buy 1 @100 (filled at open of bar 1)
    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    assert b._cash == 900.0           # 1000 - 100
    assert b._positions["X"].qty == 1.0

    # sell 1 @110 (filled at open of bar 2)
    b.submit_order(Order("X", Side.SELL, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 110, 110, 110, 110))
    # Position closed -> cash = 900 + 110 = 1010, equity = 1010
    assert "X" not in b._positions
    assert round(b._cash, 6) == 1010.0
    assert round(b._equity, 6) == 1010.0


def test_bug2_short_close_pnl():
    """Sell short 1 @100, buy to cover @90 -> +10 PnL."""
    b = PaperBroker(starting_cash=1000.0, fee_bps=0.0, slippage_bps=0.0)
    b.submit_order(Order("X", Side.SELL, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(0, 100, 100, 100, 100))
    # cash after short open: 1000 + 100 = 1100
    assert b._cash == 1100.0
    assert b._positions["X"].qty == -1.0

    b.submit_order(Order("X", Side.BUY, 1.0, OrderType.MARKET))
    b.on_bar("X", _bar(1, 90, 90, 90, 90))
    # cash after cover: 1100 - 90 = 1010
    assert "X" not in b._positions
    assert round(b._cash, 6) == 1010.0


def test_bug1_backtester_records_only_real_exits():
    """Run a forced long trade and confirm exactly one closed trade is
    recorded — not two (entry + SL/TP).
    """
    from bot.backtester import Backtester
    from bot.strategies.base import Strategy
    from bot.types import Signal, SignalType

    class OneShot(Strategy):
        name = "one_shot"
        fired = False
        def generate(self, bar):
            if not self.fired and len(self.bars) == 3:
                self.fired = True
                return Signal(
                    timestamp=bar.timestamp, symbol=self.symbol,
                    type=SignalType.LONG,
                    entry=bar.close, stop_loss=bar.close * 0.99,
                    take_profit=bar.close * 1.02, reason="test",
                )
            return None

    # bars: prices walk up so TP hits cleanly
    bars = [_bar(i, 100 + i, 100 + i + 0.5, 100 + i - 0.5, 100 + i) for i in range(20)]
    bt = Backtester(OneShot("X"), bars, starting_cash=10_000,
                    fee_bps=0.0, slippage_bps=0.0)
    result = bt.run()
    assert len(result.trades) == 1, f"Expected 1 trade, got {len(result.trades)}: {result.trades}"
    t = result.trades[0]
    assert t["pnl"] > 0
    assert t["exit_price"] != t["entry_price"], "exit should not equal entry"


def test_bug7_8_risk_state_uses_bar_time_not_today():
    """RiskState.day should follow the bar time so backtests on old data
    still trigger the daily kill switch correctly.
    """
    from bot.risk import RiskConfig, RiskManager
    from bot.types import AccountSnapshot, Signal, SignalType

    rm = RiskManager(RiskConfig(risk_per_trade_pct=0.01, max_daily_loss_pct=0.05))
    sig = Signal(
        timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
        symbol="X", type=SignalType.LONG,
        entry=100, stop_loss=99, take_profit=102,
    )
    acct = AccountSnapshot(cash=10_000, equity=10_000, positions=[])
    allow, qty, _ = rm.evaluate(sig, acct, datetime(2020, 1, 1, 10, tzinfo=timezone.utc))
    assert allow
    # state should be anchored to 2020-01-01, not today
    assert rm.state.day.year == 2020

    # simulate equity dropping 6% — kill switch should fire
    acct_drop = AccountSnapshot(cash=9400, equity=9400, positions=[])
    allow, _, reason = rm.evaluate(sig, acct_drop,
                                   datetime(2020, 1, 1, 14, tzinfo=timezone.utc))
    assert not allow
    assert "loss" in reason.lower()
