"""Phase 8: HubEventHub aggregates and fans out live bot events."""
import datetime as dt

from bot.events import EventBus, ev_bar, ev_trade_closed

from dashboard.stream import HubEventHub, sse_format

TS = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)


def test_publish_replay_and_subscribe():
    hub = HubEventHub()
    q = hub.subscribe()
    hub.publish({"type": "lifecycle", "message": "hi"})
    assert q.get_nowait()["message"] == "hi"
    assert hub.replay()[-1]["message"] == "hi"


def test_unsubscribe_stops_delivery():
    hub = HubEventHub()
    q = hub.subscribe()
    hub.unsubscribe(q)
    hub.publish({"type": "x"})
    assert q.qsize() == 0
    assert hub.replay()[-1]["type"] == "x"   # history still records it


def test_forward_from_tags_bot_identity():
    hub = HubEventHub()
    bus = EventBus()
    hub.forward_from(bus, "bot-1", "EMA Bot")
    bus.publish(ev_trade_closed("BTCUSDT", "buy", 100, 110, 1.0, 10.0, 2.0, TS))
    ev = hub.replay()[-1]
    assert ev["type"] == "trade_closed"
    assert ev["bot_id"] == "bot-1" and ev["bot_name"] == "EMA Bot"


def test_sse_format_is_event_stream_framed():
    out = sse_format({"type": "bar", "equity": 1.5})
    assert out.startswith("data: ") and out.endswith("\n\n")
    assert '"equity": 1.5' in out


def test_slow_subscriber_drops_oldest_not_newest():
    hub = HubEventHub()
    q = hub.subscribe()
    # fill beyond the per-queue cap; publish must not raise
    for i in range(1100):
        hub.publish({"type": "bar", "i": i})
    assert q.qsize() <= 1000
    # newest survived
    drained = []
    while not q.empty():
        drained.append(q.get_nowait()["i"])
    assert max(drained) == 1099
