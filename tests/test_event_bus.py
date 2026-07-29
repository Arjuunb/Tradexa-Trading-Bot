"""The event bus and structured logging.

The bus tests concentrate on the properties that make a bus safe to put in a
trading loop rather than on the mechanics of dispatch. The one that matters
most is isolation: a bus that lets a subscriber's exception escape to the
publisher is strictly worse than a direct call, because it fails the publisher
on behalf of code the publisher never chose to depend on.
"""
from __future__ import annotations

import logging
import threading

import pytest

from tradexa.core.events import (
    BotStarted, Event, MarketDataReceived, OrderFilled, RiskBreached,
)
from tradexa.infrastructure.events import (
    EventBusError, InMemoryEventBus, MAX_PUBLISH_DEPTH, NullEventBus, default_bus,
)
from tradexa.infrastructure.logging import NullLogger, StructuredLogger


@pytest.fixture()
def bus():
    return InMemoryEventBus()


# ── dispatch ────────────────────────────────────────────────────────────────

def test_a_subscriber_receives_its_event(bus):
    seen = []
    bus.subscribe(BotStarted, seen.append)
    bus.publish(BotStarted(mode="paper"))
    assert len(seen) == 1 and seen[0].mode == "paper"


def test_a_subscriber_does_not_receive_unrelated_events(bus):
    seen = []
    bus.subscribe(BotStarted, seen.append)
    bus.publish(OrderFilled())
    assert seen == []


def test_publishing_with_no_subscribers_is_not_an_error(bus):
    bus.publish(BotStarted())          # must not raise


def test_every_subscriber_of_a_type_is_called(bus):
    a, b = [], []
    bus.subscribe(RiskBreached, a.append)
    bus.subscribe(RiskBreached, b.append)
    bus.publish(RiskBreached(rule="daily_loss"))
    assert len(a) == 1 and len(b) == 1


def test_subscribing_to_event_receives_everything(bus):
    """What makes an audit log or decision recorder an ordinary subscriber
    rather than a special case wired into every publisher."""
    seen = []
    bus.subscribe(Event, seen.append)
    bus.publish(BotStarted())
    bus.publish(OrderFilled())
    bus.publish(RiskBreached(rule="x"))
    assert len(seen) == 3


def test_handlers_run_in_subscription_order(bus):
    order = []
    bus.subscribe(BotStarted, lambda e: order.append("first"))
    bus.subscribe(BotStarted, lambda e: order.append("second"))
    bus.publish(BotStarted())
    assert order == ["first", "second"]


# ── isolation: the property that makes this safe in a trading loop ──────────

def test_a_failing_subscriber_does_not_reach_the_publisher(bus):
    """A notifier that raises while handling OrderFilled must not prevent the
    fill from being recorded."""
    def explode(event):
        raise RuntimeError("telegram is down")

    bus.subscribe(OrderFilled, explode)
    bus.publish(OrderFilled())          # must not raise


def test_a_failing_subscriber_does_not_stop_the_others(bus):
    """Registration order must not decide whether the ledger gets written."""
    recorded = []

    def explode(event):
        raise RuntimeError("boom")

    bus.subscribe(OrderFilled, explode)
    bus.subscribe(OrderFilled, recorded.append)
    bus.publish(OrderFilled())
    assert len(recorded) == 1


def test_handler_failures_are_reported_to_the_error_sink(bus_errors=None):
    """Isolated is not the same as ignored — a silently dropped handler error
    is an integration that looks wired up and does nothing."""
    caught = []
    bus = InMemoryEventBus(
        on_handler_error=lambda exc, event, handler: caught.append((exc, event)))
    bus.subscribe(OrderFilled, lambda e: (_ for _ in ()).throw(ValueError("nope")))
    bus.publish(OrderFilled())
    assert len(caught) == 1 and isinstance(caught[0][0], ValueError)


def test_handler_errors_are_counted(bus):
    bus.subscribe(OrderFilled, lambda e: (_ for _ in ()).throw(ValueError()))
    bus.publish(OrderFilled())
    bus.publish(OrderFilled())
    assert bus.handler_error_count == 2


def test_a_broken_error_sink_does_not_cascade():
    """The reporter failing must not turn one handler fault into two."""
    def bad_sink(exc, event, handler):
        raise RuntimeError("the sink is broken too")

    bus = InMemoryEventBus(on_handler_error=bad_sink)
    bus.subscribe(OrderFilled, lambda e: (_ for _ in ()).throw(ValueError()))
    bus.publish(OrderFilled())          # must not raise


# ── unsubscribe ─────────────────────────────────────────────────────────────

def test_the_disposer_removes_the_subscription(bus):
    seen = []
    dispose = bus.subscribe(BotStarted, seen.append)
    bus.publish(BotStarted())
    dispose()
    bus.publish(BotStarted())
    assert len(seen) == 1


def test_disposing_twice_does_not_remove_a_later_identical_subscription(bus):
    """Two subscriptions of the same callable are distinct. A careless second
    dispose must not silently unsubscribe someone else."""
    seen = []
    dispose = bus.subscribe(BotStarted, seen.append)
    bus.subscribe(BotStarted, seen.append)      # same callable, second entry
    dispose()
    dispose()                                    # idempotent
    bus.publish(BotStarted())
    assert len(seen) == 1, "the second subscription was removed by a double dispose"


def test_a_handler_can_unsubscribe_itself_during_delivery(bus):
    """Iterating the live list would break here; the bus snapshots first."""
    seen = []

    def once(event):
        seen.append(event)
        dispose()

    dispose = bus.subscribe(BotStarted, once)
    bus.publish(BotStarted())
    bus.publish(BotStarted())
    assert len(seen) == 1


def test_a_handler_can_subscribe_during_delivery(bus):
    added = []

    def adder(event):
        bus.subscribe(OrderFilled, added.append)

    bus.subscribe(BotStarted, adder)
    bus.publish(BotStarted())          # must not deadlock
    bus.publish(OrderFilled())
    assert len(added) == 1


# ── re-entrancy ─────────────────────────────────────────────────────────────

def test_a_handler_may_publish_another_event(bus):
    """The normal chain: a fill leads to a position update leads to a portfolio
    update."""
    seen = []
    bus.subscribe(OrderFilled, lambda e: bus.publish(RiskBreached(rule="chained")))
    bus.subscribe(RiskBreached, seen.append)
    bus.publish(OrderFilled())
    assert len(seen) == 1 and seen[0].rule == "chained"


def test_a_publish_cycle_is_reported_rather_than_overflowing_the_stack(bus):
    """An unbounded cycle should name itself, not arrive as a RecursionError
    thousands of frames from the handler that caused it."""
    bus.subscribe(OrderFilled, lambda e: bus.publish(OrderFilled()))
    # The cycle is inside a handler, so the bus isolates the EventBusError and
    # counts it rather than propagating — the publisher stays protected.
    bus.publish(OrderFilled())
    assert bus.handler_error_count >= 1


def test_depth_resets_after_a_publish_completes(bus):
    """Otherwise a long-lived process would drift toward the limit and start
    rejecting legitimate publishes."""
    bus.subscribe(OrderFilled, lambda e: bus.publish(BotStarted()))
    for _ in range(MAX_PUBLISH_DEPTH + 5):
        bus.publish(OrderFilled())
    assert bus.handler_error_count == 0


# ── concurrency ─────────────────────────────────────────────────────────────

def test_concurrent_publishes_all_arrive(bus):
    """The engine, watchdog and monitor each publish from their own thread."""
    received = []
    lock = threading.Lock()

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


def test_subscribing_while_publishing_from_another_thread_is_safe(bus):
    stop = threading.Event()

    def churn():
        while not stop.is_set():
            bus.subscribe(BotStarted, lambda e: None)()

    t = threading.Thread(target=churn)
    t.start()
    try:
        for _ in range(200):
            bus.publish(BotStarted())
    finally:
        stop.set()
        t.join()
    # No assertion beyond "did not deadlock or raise" — that is the property.


# ── null bus ────────────────────────────────────────────────────────────────

def test_the_null_bus_accepts_everything_and_does_nothing():
    """So an optional bus needs no `if self._bus is not None` at each call
    site — those guards are how an event gets published on one path only."""
    nb = NullEventBus()
    nb.publish(BotStarted())
    assert callable(nb.subscribe(BotStarted, lambda e: None))


def test_both_buses_satisfy_the_port():
    from tradexa.core.interfaces import EventBus
    assert isinstance(InMemoryEventBus(), EventBus)
    assert isinstance(NullEventBus(), EventBus)


def test_the_default_bus_is_a_singleton():
    assert default_bus() is default_bus()


# ═══════════════════════════════════════════════════ structured logging

@pytest.fixture()
def caplog_json(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


def test_a_record_is_an_event_name_plus_fields(caplog_json):
    """Not a pre-formatted sentence — that is what makes it queryable later."""
    StructuredLogger("feed").warning("fetch_failed", symbol="BTCUSDT", exchange="kraken")
    rec = caplog_json.records[-1].structured
    assert rec["event"] == "fetch_failed" and rec["module"] == "feed"
    assert rec["symbol"] == "BTCUSDT" and rec["level"] == "WARNING"


def test_every_record_carries_a_timestamp_and_module(caplog_json):
    StructuredLogger("risk").info("checked")
    rec = caplog_json.records[-1].structured
    assert rec["timestamp"] and rec["module"] == "risk"


def test_a_context_key_cannot_overwrite_a_reserved_field(caplog_json):
    """A caller passing `level=` must not be able to rewrite the severity the
    record was emitted at."""
    StructuredLogger("x").info("evt", level="sneaky", event="also_sneaky")
    rec = caplog_json.records[-1].structured
    assert rec["level"] == "INFO" and rec["event"] == "evt"
    assert rec["ctx_level"] == "sneaky" and rec["ctx_event"] == "also_sneaky"


def test_json_format_emits_parseable_json(caplog_json):
    import json
    StructuredLogger("feed", fmt="json").info("bar_closed", symbol="ETHUSDT")
    parsed = json.loads(caplog_json.records[-1].getMessage())
    assert parsed["event"] == "bar_closed" and parsed["symbol"] == "ETHUSDT"


def test_an_unserialisable_value_does_not_break_the_log_call(caplog_json):
    """A log call must never be the thing that breaks a trading loop."""
    class Weird:
        pass
    StructuredLogger("x", fmt="json").info("evt", obj=Weird())
    assert caplog_json.records[-1].structured["obj"].__class__ is Weird


def test_timed_records_the_duration_once(caplog_json):
    log = StructuredLogger("backtest")
    with log.timed("run", symbol="BTCUSDT"):
        pass
    rec = caplog_json.records[-1].structured
    assert rec["event"] == "run" and rec["duration_ms"] >= 0
    assert len([r for r in caplog_json.records if r.structured["event"] == "run"]) == 1


def test_timed_lets_the_block_attach_what_it_learned(caplog_json):
    """Two lines for one operation cannot be joined without a correlation id
    nobody is issuing yet, so the facts go on the same record."""
    log = StructuredLogger("feed")
    with log.timed("fetch") as extra:
        extra["bars"] = 500
        extra["source"] = "live:kraken"
    rec = caplog_json.records[-1].structured
    assert rec["bars"] == 500 and rec["source"] == "live:kraken"


def test_timed_still_logs_the_duration_when_the_block_raises(caplog_json):
    """A request that took 30 seconds and then failed is exactly the slow path
    worth knowing about."""
    log = StructuredLogger("feed")
    with pytest.raises(ValueError):
        with log.timed("fetch", symbol="BTCUSDT"):
            raise ValueError("timeout")
    rec = caplog_json.records[-1].structured
    assert rec["level"] == "ERROR" and rec["duration_ms"] >= 0
    assert rec["error"] == "ValueError"


def test_exception_unpacks_a_tradexa_error_into_fields(caplog_json):
    from tradexa.core.exceptions import OrderRejected
    log = StructuredLogger("execution")
    log.exception("submit_failed", OrderRejected("venue refused", symbol="BTCUSDT"))
    rec = caplog_json.records[-1].structured
    assert rec["error"] == "OrderRejected" and rec["symbol"] == "BTCUSDT"
    assert rec["retryable"] is False


def test_exception_handles_a_plain_exception_too(caplog_json):
    StructuredLogger("x").exception("failed", ValueError("bad input"))
    rec = caplog_json.records[-1].structured
    assert rec["error"] == "ValueError" and "bad input" in rec["message"]


def test_the_null_logger_accepts_everything_and_does_nothing():
    n = NullLogger()
    n.info("evt", a=1)
    n.exception("evt", ValueError())
    with n.timed("evt") as extra:
        extra["x"] = 1


def test_both_loggers_satisfy_the_port():
    from tradexa.core.interfaces import Logger
    assert isinstance(StructuredLogger("x"), Logger)
    assert isinstance(NullLogger(), Logger)
