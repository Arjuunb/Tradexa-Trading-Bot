"""Phase 5: real order routing, alerts, and multi-bot supervision.

No live exchange in CI, so order routing is verified against a recording mock
broker and alerts against a capturing sink.
"""
from bot.data.synthetic import generate_bars
from bot.events import EventBus, ev_order, ev_signal, ev_trade_closed

from bots.manager import BotManager
from data.websocket import ReplayFeed
from database.models import BotConfig, BotMode, BotState
from execution.execution_engine import ExecutionEngine
from execution.live_bridge import RealOrderRouter
from notifications import AlertDispatcher


class MockBroker:
    """Minimal Broker surface: records submitted orders."""
    name = "mock"

    def __init__(self):
        self.orders = []

    def submit_order(self, order):
        self.orders.append(order)
        return f"mock-{len(self.orders)}"

    def cancel_order(self, order_id):
        pass


def _cfg(name="Live Bot", strat="ema", sym="BTCUSDT"):
    return BotConfig(name=name, strategy=strat, exchange="binance",
                     symbol=sym, timeframe="1h", mode=BotMode.LIVE)


# ----------------------------------------------------- real order routing
def test_real_order_router_forwards_bracket_order():
    mock = MockBroker()
    router = RealOrderRouter(ExecutionEngine(mock, dry_run=False))
    bus = EventBus()
    router.attach(bus)

    import datetime as dt
    ts = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    bus.publish(ev_signal("BTCUSDT", "buy", 100.0, 95.0, 110.0, "x", ts))
    bus.publish(ev_order("eng-1", "BTCUSDT", "buy", 2.0))

    assert len(mock.orders) == 1
    o = mock.orders[0]
    assert o.symbol == "BTCUSDT" and o.qty == 2.0
    assert o.stop_loss == 95.0 and o.take_profit == 110.0   # SL/TP from the paired signal
    assert router.submitted[0]["broker_order_id"] == "mock-1"


def test_router_dry_run_does_not_hit_broker():
    mock = MockBroker()
    router = RealOrderRouter(ExecutionEngine(mock, dry_run=True))
    bus = EventBus()
    router.attach(bus)
    import datetime as dt
    bus.publish(ev_order("eng-1", "BTCUSDT", "buy", 1.0))
    assert mock.orders == []                       # dry-run: nothing sent
    assert router.submitted[0]["broker_order_id"].startswith("dry-run")


def test_live_runner_routes_orders_to_real_broker():
    mock = MockBroker()
    m = BotManager()
    bot = m.create(_cfg())
    m.start_live(bot.id, feed=ReplayFeed(generate_bars(400, "1h", seed=4)),
                 real_broker=mock, dry_run=False)
    m.runner(bot.id).wait(timeout=15)
    # Every entry the engine took was mirrored to the live broker.
    assert len(mock.orders) == bot.runtime.metrics["num_trades"]


# ----------------------------------------------------------------- alerts
def test_alert_dispatcher_on_trade_close():
    captured = []
    disp = AlertDispatcher("My Bot", send=captured.append)
    bus = EventBus()
    disp.attach(bus)
    import datetime as dt
    ts = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    bus.publish(ev_trade_closed("BTCUSDT", "buy", 100, 110, 1.0, 10.0, 2.0, ts))
    bus.publish(ev_trade_closed("BTCUSDT", "buy", 100, 90, 1.0, -10.0, -1.0, ts))
    assert len(captured) == 2
    assert "TP" in captured[0] and "SL" in captured[1]


# ------------------------------------------------------ multi-bot supervision
def test_multiple_live_bots_run_concurrently():
    m = BotManager()
    ids = []
    for i, strat in enumerate(("ema", "rsi")):
        b = m.create(_cfg(name=f"Bot {i}", strat=strat))
        m.start_live(b.id, feed=ReplayFeed(generate_bars(300, "1h", seed=i + 1)))
        ids.append(b.id)
    for bid in ids:
        m.runner(bid).wait(timeout=15)
    assert len(m.list()) == 2
    for bid in ids:
        bot = m.get(bid)
        assert bot.runtime.state == BotState.STOPPED
        assert "num_trades" in bot.runtime.metrics
