"""The event backbone: envelope, registry, dispatcher, priorities, retry,
metrics, async, and replay.

Grouped by the property being defended rather than by class, because the
properties are what make this safe to put under a trading loop — which class
implements them is an implementation detail that may change.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from tradexa.core.events import (
    ALL_EVENTS, BotStarted, CandleClosed, ErrorOccurred, Event,
    MarketDataReceived, OrderFilled, OrderRejected, OrderRejectedEvent,
    PositionUpdated, RiskApproved, RiskCheckStarted, RiskRejected,
    TradeCompleted, new_id,
)
from tradexa.core.models import Bar
from tradexa.infrastructure.events import (
    EventBusError, EventDispatcher, EventPublisher, EventRecorder,
    EventRegistry, EventReplayer, EventSubscriber, InMemoryEventBus,
    NullEventBus, Priority, default_registry, is_replayed,
)


@pytest.fixture()
def bus():
    return InMemoryEventBus()


def _bar(close=100.0):
    from datetime import datetime, timezone
    return Bar(datetime.now(timezone.utc), 100.0, 101.0, 99.0, close, 10.0)


# ═════════════════════════════════════════════════════ the envelope

def test_every_event_carries_the_full_envelope():
    e = BotStarted(mode="paper")
    assert e.event_id and len(e.event_id) >= 16
    assert e.timestamp == e.occurred_at
    assert e.source == "" and e.correlation_id == ""
    assert e.metadata == {} and isinstance(e.payload, dict)


def test_event_ids_are_unique():
    """Deduplication and log joins both depend on it."""
    ids = {BotStarted().event_id for _ in range(500)}
    assert len(ids) == 500


def test_payload_is_the_typed_fields_without_the_envelope():
    e = MarketDataReceived(symbol="BTCUSDT", timeframe="4h", bar=_bar(),
                           data_source="live", source="engine")
    assert set(e.payload) == {"symbol", "timeframe", "bar", "data_source"}
    assert e.payload["symbol"] == "BTCUSDT"
    assert "event_id" not in e.payload and "source" not in e.payload


def test_payload_is_derived_not_stored():
    """One frozen object holding the same data twice is one bad constructor
    away from a payload that disagrees with the fields it describes."""
    e = BotStarted(mode="live")
    assert e.payload["mode"] == "live"
    assert not hasattr(type(e), "__dataclass_fields__") or "payload" not in {
        f for f in type(e).__dataclass_fields__}


def test_the_envelope_serialises_for_a_journal():
    e = OrderFilled(source="execution", correlation_id="abc", metadata={"k": 1})
    env = e.envelope()
    assert env["event"] == "OrderFilled" and env["source"] == "execution"
    assert env["correlation_id"] == "abc" and env["metadata"] == {"k": 1}
    json.dumps(env)      # must be serialisable


def test_data_source_and_envelope_source_are_different_things():
    """They were one field before the envelope existed. A live-mode engine
    served bundled data will never see a new candle, and that is invisible
    unless the DATA's provenance travels beside the publisher's identity."""
    e = MarketDataReceived(data_source="bundled sample", source="auto_engine")
    assert e.data_source == "bundled sample" and e.source == "auto_engine"


# ═════════════════════════════════════════════════════ the vocabulary

@pytest.mark.parametrize("name", [
    "BotStarted", "BotStopped", "MarketDataReceived", "CandleClosed",
    "SignalGenerated", "RiskCheckStarted", "RiskApproved", "RiskRejected",
    "OrderCreated", "OrderSubmitted", "OrderAccepted", "OrderRejected",
    "OrderFilled", "PositionOpened", "PositionUpdated", "PositionClosed",
    "PortfolioUpdated", "TradeCompleted", "ErrorOccurred",
])
def test_every_required_event_exists_and_is_registered(name):
    assert name in {c.__name__ for c in ALL_EVENTS}
    assert default_registry.resolve(name) is not None


def test_the_phase_two_alias_still_resolves():
    """Backwards compatibility: OrderRejectedEvent was the phase-2 name."""
    assert OrderRejectedEvent is OrderRejected


def test_candle_closed_is_distinct_from_market_data_received():
    """Only a closed candle may be acted on. An in-progress bar changes under
    the subscriber's feet."""
    assert CandleClosed is not MarketDataReceived
    assert issubclass(CandleClosed, Event)


def test_error_occurred_captures_an_exception_without_holding_it():
    """An event may be journalled and replayed; a live exception holds
    tracebacks and frames that keep whole object graphs alive."""
    from tradexa.core.exceptions import OrderRejected as OrderRejectedError
    e = ErrorOccurred.from_exception(
        OrderRejectedError("venue refused", symbol="BTCUSDT"), module="execution")
    assert e.error == "OrderRejected" and "refused" in e.message
    assert e.context["symbol"] == "BTCUSDT" and e.retryable is False
    assert not isinstance(e.context.get("exc"), BaseException)


def test_error_occurred_handles_a_plain_exception():
    e = ErrorOccurred.from_exception(ValueError("bad"), module="x")
    assert e.error == "ValueError" and e.retryable is False


# ═════════════════════════════════════════════════════ registry

def test_the_registry_resolves_a_name_to_its_type():
    r = EventRegistry([BotStarted])
    assert r.resolve("BotStarted") is BotStarted
    assert r.resolve("Nope") is None


def test_registering_the_same_class_twice_is_fine():
    r = EventRegistry([BotStarted])
    r.register(BotStarted)
    assert len(r) == 1


def test_two_different_classes_under_one_name_is_an_error():
    """Silently overwriting would make replay reconstruct the wrong type."""
    class BotStarted:      # shadows deliberately
        pass
    r = EventRegistry()
    r.register(BotStarted)
    from tradexa.core.events import BotStarted as Real
    with pytest.raises(EventBusError):
        r.register(Real)


def test_the_default_registry_holds_the_whole_vocabulary():
    assert len(default_registry) == len(ALL_EVENTS)


# ═════════════════════════════════════════════════════ isolation

def test_a_failing_subscriber_never_reaches_the_publisher(bus):
    """The invariant everything else is built on."""
    bus.subscribe(OrderFilled, lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.publish(OrderFilled())          # must not raise


def test_a_failing_subscriber_does_not_stop_the_others(bus):
    seen = []
    bus.subscribe(OrderFilled, lambda e: (_ for _ in ()).throw(RuntimeError()))
    bus.subscribe(OrderFilled, seen.append)
    bus.publish(OrderFilled())
    assert len(seen) == 1


def test_a_handler_failure_is_republished_as_an_error_event(bus):
    """So an error monitor is an ordinary subscriber rather than a special
    case wired separately into every publisher."""
    errors = []
    bus.subscribe(ErrorOccurred, errors.append)
    bus.subscribe(OrderFilled, lambda e: (_ for _ in ()).throw(ValueError("x")))
    bus.publish(OrderFilled())
    assert len(errors) == 1 and errors[0].error == "ValueError"


def test_a_failing_error_handler_does_not_recurse(bus):
    """An ErrorOccurred handler that itself raises must not publish another
    ErrorOccurred forever."""
    bus.subscribe(ErrorOccurred, lambda e: (_ for _ in ()).throw(RuntimeError()))
    bus.subscribe(OrderFilled, lambda e: (_ for _ in ()).throw(ValueError()))
    bus.publish(OrderFilled())          # must terminate
    assert bus.handler_error_count >= 1


# ═════════════════════════════════════════════════════ priorities

def test_higher_priority_runs_first(bus):
    """Ordering matters when handlers are not independent: an audit record must
    be written before a notification claims the trade happened."""
    order = []
    bus.subscribe(OrderFilled, lambda e: order.append("bg"), priority=Priority.BACKGROUND)
    bus.subscribe(OrderFilled, lambda e: order.append("critical"), priority=Priority.CRITICAL)
    bus.subscribe(OrderFilled, lambda e: order.append("normal"), priority=Priority.NORMAL)
    bus.publish(OrderFilled())
    assert order == ["critical", "normal", "bg"]


def test_equal_priorities_keep_registration_order(bus):
    """Without a tiebreaker, sorting is unstable and two handlers that must run
    in a fixed order would swap unpredictably between runs."""
    order = []
    for i in range(6):
        bus.subscribe(OrderFilled, lambda e, i=i: order.append(i))
    bus.publish(OrderFilled())
    assert order == [0, 1, 2, 3, 4, 5]


def test_priority_applies_across_base_class_subscriptions(bus):
    order = []
    bus.subscribe(Event, lambda e: order.append("any"), priority=Priority.LOW)
    bus.subscribe(OrderFilled, lambda e: order.append("specific"), priority=Priority.HIGH)
    bus.publish(OrderFilled())
    assert order == ["specific", "any"]


# ═════════════════════════════════════════════════════ retry

def test_a_handler_can_be_retried(bus):
    attempts = []

    def flaky(event):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")

    bus.subscribe(OrderFilled, flaky, retries=2)
    bus.publish(OrderFilled())
    assert len(attempts) == 3


def test_retries_are_exhausted_and_then_reported(bus):
    attempts = []
    bus.subscribe(OrderFilled,
                  lambda e: attempts.append(1) or (_ for _ in ()).throw(RuntimeError()),
                  retries=2)
    bus.publish(OrderFilled())
    assert len(attempts) == 3            # original + 2 retries
    assert bus.handler_error_count >= 3


def test_retries_default_to_none(bus):
    """Retrying a handler with side effects duplicates them, so opting in is a
    decision the subscriber makes knowing whether its work is idempotent."""
    attempts = []
    bus.subscribe(OrderFilled,
                  lambda e: attempts.append(1) or (_ for _ in ()).throw(RuntimeError()))
    bus.publish(OrderFilled())
    assert len(attempts) == 1


# ═════════════════════════════════════════════════════ metrics

def test_metrics_count_publishes_and_handled(bus):
    bus.subscribe(OrderFilled, lambda e: None, name="h")
    bus.publish(OrderFilled())
    bus.publish(OrderFilled())
    snap = bus.metrics.snapshot()
    assert snap["published"]["OrderFilled"] == 2
    assert snap["handled"]["OrderFilled:h"] == 2
    assert snap["total_errors"] == 0


def test_metrics_count_errors_and_retries_separately(bus):
    bus.subscribe(OrderFilled, lambda e: (_ for _ in ()).throw(RuntimeError()),
                  retries=1, name="bad")
    bus.publish(OrderFilled())
    snap = bus.metrics.snapshot()
    assert snap["errors"]["OrderFilled:bad"] == 2
    assert snap["retries"]["OrderFilled:bad"] == 1


def test_metrics_record_handler_duration(bus):
    bus.subscribe(OrderFilled, lambda e: None, name="h")
    bus.publish(OrderFilled())
    assert bus.metrics.snapshot()["duration_ms"]["OrderFilled:h"] >= 0


def test_metrics_can_be_reset(bus):
    bus.subscribe(OrderFilled, lambda e: None)
    bus.publish(OrderFilled())
    bus.metrics.reset()
    assert bus.metrics.snapshot()["total_published"] == 0


# ═════════════════════════════════════════════════════ async

def test_an_async_handler_runs_under_publish_async(bus):
    seen = []

    async def handler(event):
        await asyncio.sleep(0)
        seen.append(event)

    bus.subscribe(OrderFilled, handler)
    asyncio.run(bus.publish_async(OrderFilled()))
    assert len(seen) == 1


def test_sync_and_async_handlers_share_one_priority_ordering(bus):
    """Gathering coroutines would break the ordering promise the moment two
    async handlers had different priorities."""
    order = []

    async def slow(event):
        await asyncio.sleep(0.01)
        order.append("high-async")

    bus.subscribe(OrderFilled, slow, priority=Priority.HIGH)
    bus.subscribe(OrderFilled, lambda e: order.append("low-sync"), priority=Priority.LOW)
    asyncio.run(bus.publish_async(OrderFilled()))
    assert order == ["high-async", "low-sync"]


def test_an_async_handler_dispatched_synchronously_is_reported_not_dropped(bus):
    """A coroutine created and never awaited leaks and warns. Failing loudly
    beats silently discarding the work."""
    async def handler(event):
        pass

    bus.subscribe(OrderFilled, handler)
    bus.publish(OrderFilled())           # isolated, not raised
    assert bus.handler_error_count >= 1


def test_a_failing_async_handler_is_isolated_too(bus):
    async def bad(event):
        raise RuntimeError("async boom")

    seen = []
    bus.subscribe(OrderFilled, bad)
    bus.subscribe(OrderFilled, seen.append)
    asyncio.run(bus.publish_async(OrderFilled()))
    assert len(seen) == 1


# ═════════════════════════════════════════════════════ publisher

def test_the_publisher_stamps_its_source(bus):
    seen = []
    bus.subscribe(BotStarted, seen.append)
    bus.publisher("risk_engine").publish(BotStarted())
    assert seen[0].source == "risk_engine"


def test_the_publisher_never_overwrites_an_explicit_source(bus):
    """An event that already names its source knows better — clobbering would
    erase the provenance of anything forwarded from elsewhere."""
    seen = []
    bus.subscribe(BotStarted, seen.append)
    bus.publisher("wrapper").publish(BotStarted(source="original"))
    assert seen[0].source == "original"


def test_a_correlated_publisher_shares_one_id_across_a_chain(bus):
    """The whole point: one bar leads to a signal, a risk check, an order and a
    fill. Without a shared id, reconstructing that means matching on symbol and
    timestamp and hoping."""
    seen = []
    bus.subscribe(Event, seen.append)
    pub = bus.publisher("engine").correlated()
    pub.publish(MarketDataReceived(symbol="BTCUSDT"))
    pub.publish(RiskCheckStarted(symbol="BTCUSDT"))
    pub.publish(RiskApproved())
    ids = {e.correlation_id for e in seen}
    assert len(ids) == 1 and ids != {""}


def test_two_chains_get_different_correlation_ids(bus):
    p = bus.publisher("engine")
    assert p.correlated().correlation_id != p.correlated().correlation_id


# ═════════════════════════════════════════════════════ subscriber base

def test_a_subscriber_registers_and_detaches_symmetrically(bus):
    class Recorder(EventSubscriber):
        handles = {OrderFilled: "on_fill",
                   RiskRejected: ("on_reject", Priority.HIGH)}

        def __init__(self):
            super().__init__()
            self.fills, self.rejects = [], []

        def on_fill(self, event):
            self.fills.append(event)

        def on_reject(self, event):
            self.rejects.append(event)

    r = Recorder().attach(bus)
    bus.publish(OrderFilled())
    bus.publish(RiskRejected(rule="cap"))
    assert len(r.fills) == 1 and len(r.rejects) == 1

    r.detach()
    bus.publish(OrderFilled())
    assert len(r.fills) == 1, "detach did not remove every handler"


# ═════════════════════════════════════════════════════ replay

def test_the_recorder_captures_the_whole_vocabulary(bus):
    rec = EventRecorder()
    rec.attach(bus)
    bus.publish(BotStarted())
    bus.publish(OrderFilled())
    bus.publish(TradeCompleted())
    assert len(rec) == 3


def test_the_recorder_runs_last(bus):
    """At BACKGROUND priority, so recording can never delay or reorder real
    work."""
    order = []
    rec = EventRecorder()
    rec.attach(bus)
    bus.subscribe(OrderFilled, lambda e: order.append("work"), priority=Priority.NORMAL)
    bus.publish(OrderFilled())
    assert order == ["work"] and len(rec) == 1


def test_the_recorder_is_bounded(bus):
    """An unbounded recorder on a long-running bot is a memory leak with a
    helpful name."""
    rec = EventRecorder(limit=10)
    rec.attach(bus)
    for _ in range(25):
        bus.publish(OrderFilled())
    assert len(rec) == 10 and rec.dropped == 15


def test_a_chain_can_be_pulled_out_by_correlation_id(bus):
    rec = EventRecorder()
    rec.attach(bus)
    chain = bus.publisher("engine").correlated()
    chain.publish(MarketDataReceived(symbol="BTCUSDT"))
    chain.publish(RiskApproved())
    bus.publish(OrderFilled())              # unrelated, uncorrelated
    got = rec.by_correlation(chain.correlation_id)
    assert len(got) == 2


def test_replayed_events_are_marked(bus):
    """A replayed fill must never be mistaken for a live one — by a subscriber,
    a log reader, or a metric."""
    rec = EventRecorder()
    rec.attach(bus)
    bus.publish(OrderFilled())
    captured = rec.events()

    seen = []
    bus.clear()
    bus.subscribe(OrderFilled, seen.append)
    EventReplayer(bus).replay(captured)
    assert len(seen) == 1 and is_replayed(seen[0])


def test_a_live_event_is_not_marked_as_replayed(bus):
    seen = []
    bus.subscribe(OrderFilled, seen.append)
    bus.publish(OrderFilled())
    assert not is_replayed(seen[0])


def test_replay_preserves_the_original_id_and_timestamp(bus):
    """Keeping the id is what lets a replayed event be matched against the log
    line the live one wrote. A fresh id would make them uncorrelatable."""
    rec = EventRecorder()
    rec.attach(bus)
    bus.publish(OrderFilled())
    original = rec.events()[0]

    seen = []
    bus.clear()
    bus.subscribe(OrderFilled, seen.append)
    EventReplayer(bus).replay([original])
    assert seen[0].event_id == original.event_id
    assert seen[0].occurred_at == original.occurred_at


def test_replay_preserves_order(bus):
    rec = EventRecorder()
    rec.attach(bus)
    for i in range(5):
        bus.publish(MarketDataReceived(symbol=f"S{i}"))
    captured = rec.events()

    seen = []
    bus.clear()
    bus.subscribe(MarketDataReceived, seen.append)
    EventReplayer(bus).replay(captured)
    assert [e.symbol for e in seen] == ["S0", "S1", "S2", "S3", "S4"]


def test_a_journal_line_is_json(bus):
    rec = EventRecorder()
    rec.attach(bus)
    bus.publisher("engine").publish(
        MarketDataReceived(symbol="BTCUSDT", timeframe="4h", bar=_bar(42.0)))
    line = json.loads(rec.to_jsonl())
    assert line["event"] == "MarketDataReceived"
    assert line["payload"]["symbol"] == "BTCUSDT"
    assert line["payload"]["bar"]["close"] == 42.0      # dataclass flattened


def test_an_unserialisable_payload_is_recorded_and_flagged(bus):
    """A journal that refuses anything it cannot perfectly round-trip would
    record nothing on the events most worth having."""
    class Opaque:
        pass

    rec = EventRecorder()
    rec.attach(bus)
    bus.publish(BotStarted(metadata={"x": 1}, strategy="s"))
    bus.publish(MarketDataReceived(symbol="X", bar=Opaque()))
    lines = [json.loads(l) for l in rec.to_jsonl().splitlines()]
    flagged = [l for l in lines if l.get("lossy_fields")]
    assert flagged and "bar" in flagged[0]["lossy_fields"]


def test_the_journal_round_trips_through_a_file(bus, tmp_path):
    rec = EventRecorder()
    rec.attach(bus)
    bus.publish(BotStarted(mode="paper"))
    path = rec.write(tmp_path / "journal.jsonl")
    assert path.exists()
    assert json.loads(path.read_text())["event"] == "BotStarted"


# ═════════════════════════════════════════════════════ backwards compatibility

def test_the_phase_two_api_still_works(bus):
    """auto_engine and its tests use these exact calls."""
    seen = []
    dispose = bus.subscribe(MarketDataReceived, seen.append)
    bus.publish(MarketDataReceived(symbol="BTCUSDT"))
    dispose()
    bus.publish(MarketDataReceived(symbol="BTCUSDT"))
    assert len(seen) == 1
    assert bus.published_count == 2 and bus.handler_error_count == 0
    bus.clear()


def test_the_null_bus_accepts_the_whole_api():
    nb = NullEventBus()
    nb.publish(BotStarted())
    assert callable(nb.subscribe(BotStarted, lambda e: None))
    assert isinstance(nb.publisher("x"), EventPublisher)
    asyncio.run(nb.publish_async(BotStarted()))


def test_both_buses_still_satisfy_the_port():
    from tradexa.core.interfaces import EventBus
    assert isinstance(InMemoryEventBus(), EventBus)
    assert isinstance(NullEventBus(), EventBus)


# ═════════════════════════════════════════════════════ concurrency & cycles

def test_concurrent_publishes_all_arrive(bus):
    received, lock = [], threading.Lock()

    def handler(event):
        with lock:
            received.append(event)

    bus.subscribe(MarketDataReceived, handler)
    threads = [threading.Thread(target=lambda: [
        bus.publish(MarketDataReceived(symbol="BTCUSDT")) for _ in range(50)])
        for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(received) == 200


def test_a_publish_cycle_is_reported_rather_than_overflowing(bus):
    bus.subscribe(OrderFilled, lambda e: bus.publish(OrderFilled()))
    bus.publish(OrderFilled())          # isolated by the bus
    assert bus.handler_error_count >= 1


def test_a_handler_may_publish_a_different_event(bus):
    """The normal chain: a fill leads to a position update."""
    seen = []
    bus.subscribe(OrderFilled, lambda e: bus.publish(PositionUpdated(reason="fill")))
    bus.subscribe(PositionUpdated, seen.append)
    bus.publish(OrderFilled())
    assert len(seen) == 1 and seen[0].reason == "fill"
