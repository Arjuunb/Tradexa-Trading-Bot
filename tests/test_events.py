"""EventBus + backtester event emission."""
from datetime import datetime, timezone

from bot.backtester import Backtester
from bot.data.synthetic import generate_bars
from bot.events import EventBus, ev_signal
from bot.strategies import SupportResistanceRejection


def test_bus_subscribe_publish_unsub():
    bus = EventBus()
    seen = []
    unsub = bus.subscribe(lambda e: seen.append(e))
    bus.publish({"type": "ping", "n": 1})
    assert seen == [{"type": "ping", "n": 1}]
    unsub()
    bus.publish({"type": "ping", "n": 2})
    assert len(seen) == 1


def test_bus_replay_buffers_history():
    bus = EventBus(history=3)
    for i in range(5):
        bus.publish({"type": "x", "i": i})
    rep = bus.replay()
    assert [e["i"] for e in rep] == [2, 3, 4]


def test_bus_bad_subscriber_does_not_break_engine():
    bus = EventBus()
    bus.subscribe(lambda e: 1 / 0)  # raises
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    bus.publish({"type": "x"})
    assert seen == [{"type": "x"}]


def test_backtester_emits_lifecycle_events():
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e["type"]))
    bars = generate_bars(400, "1h", seed=1)
    bt = Backtester(SupportResistanceRejection("BTC-USD"), bars, bus=bus)
    bt.run()
    # Must have at minimum lifecycle and bar events
    assert "run_started" in events
    assert "run_finished" in events
    assert events.count("bar") == 400


def test_event_signal_constructor_shape():
    ev = ev_signal("BTC", "buy", 100.0, 95.0, 110.0, "test",
                   datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert ev["type"] == "signal"
    assert ev["symbol"] == "BTC"
    assert ev["side"] == "buy"
    assert ev["entry"] == 100.0
