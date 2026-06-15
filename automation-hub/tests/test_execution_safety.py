"""Execution-safety layer (Priority 3) + decision transparency (Priority 2)."""
import pytest

from bot.events import EventBus, ev_order, ev_signal, ev_trade_closed
from bot.types import Order, OrderType, Side

from execution.execution_engine import ExecutionEngine
from execution.live_bridge import RealOrderRouter
from execution.safety import (
    CircuitBreaker, ExecutionSafety, RetryPolicy, SafetyConfig, SafetyContext, reconcile,
)


def _order(symbol="BTC/USDT", qty=1.0, side=Side.BUY):
    return Order(symbol=symbol, side=side, qty=qty, order_type=OrderType.MARKET)


class MockBroker:
    name = "mock"

    def __init__(self):
        self.orders = []

    def submit_order(self, order):
        self.orders.append(order)
        return f"mock-{len(self.orders)}"

    def cancel_order(self, order_id):
        pass


class FlakyBroker(MockBroker):
    """Fails the first ``fail_n`` submits, then succeeds."""

    def __init__(self, fail_n: int):
        super().__init__()
        self.fail_n = fail_n
        self.calls = 0

    def submit_order(self, order):
        self.calls += 1
        if self.calls <= self.fail_n:
            raise ConnectionError("venue timeout")
        return super().submit_order(order)


# ----------------------------------------------------------- ExecutionSafety
def test_valid_order_passes_all_checks():
    d = ExecutionSafety().evaluate(SafetyContext(order=_order()))
    assert d.allowed and d.verdict == "allowed"
    assert all(c.passed for c in d.checks)


def test_invalid_order_rejected():
    d = ExecutionSafety().evaluate(SafetyContext(order=_order(qty=0)))
    assert not d.allowed and d.verdict == "rejected"
    assert any(c.rule == "valid_order" and not c.passed for c in d.checks)


def test_duplicate_order_blocked():
    d = ExecutionSafety().evaluate(
        SafetyContext(order=_order(symbol="ETH/USDT"), open_symbols=frozenset({"ETH/USDT"})))
    assert not d.allowed
    assert any(c.rule == "no_duplicate_order" and not c.passed for c in d.checks)


def test_disconnected_exchange_rejected():
    d = ExecutionSafety().evaluate(SafetyContext(order=_order(), connected=False))
    assert not d.allowed
    assert "unreachable" in d.reason


def test_stale_data_rejected():
    cfg = SafetyConfig(max_data_age_s=30)
    d = ExecutionSafety(cfg).evaluate(SafetyContext(order=_order(), data_age_s=120))
    assert not d.allowed
    assert any(c.rule == "data_feed_fresh" and not c.passed for c in d.checks)


def test_slippage_within_and_over_limit():
    cfg = SafetyConfig(max_slippage_bps=8)
    safe = ExecutionSafety(cfg)
    ok = safe.evaluate(SafetyContext(order=_order(), expected_price=100.0, quote_price=100.05))
    assert ok.allowed                                    # 5 bps <= 8
    bad = safe.evaluate(SafetyContext(order=_order(), expected_price=100.0, quote_price=100.2))
    assert not bad.allowed and "bps" in bad.reason       # 20 bps > 8


def test_unknowns_are_lenient():
    # No quote / connectivity / data-age supplied -> all those checks pass.
    d = ExecutionSafety().evaluate(SafetyContext(order=_order()))
    assert d.allowed


def test_decision_to_event_serialises():
    ev = ExecutionSafety().evaluate(SafetyContext(order=_order())).to_event()
    assert ev["type"] == "decision" and ev["verdict"] == "allowed"
    assert isinstance(ev["checks"], list) and ev["checks"][0]["rule"]


# ----------------------------------------------------------------- RetryPolicy
def test_retry_succeeds_after_failures():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    out = RetryPolicy(attempts=3, sleep=lambda _: None).run(fn)
    assert out == "ok" and calls["n"] == 3


def test_retry_raises_after_exhausting():
    with pytest.raises(ConnectionError):
        RetryPolicy(attempts=2, sleep=lambda _: None).run(lambda: (_ for _ in ()).throw(ConnectionError("x")))


# --------------------------------------------------------------- CircuitBreaker
def test_circuit_breaker_trips_and_resets():
    cb = CircuitBreaker(threshold=3)
    assert cb.allow()
    cb.record_failure(); cb.record_failure()
    assert cb.allow()                 # 2 < 3
    cb.record_failure()
    assert cb.tripped and not cb.allow()
    cb.record_success()               # stays open until reset
    assert cb.tripped
    cb.reset()
    assert cb.allow() and not cb.tripped


def test_circuit_breaker_success_clears_count():
    cb = CircuitBreaker(threshold=2)
    cb.record_failure()
    cb.record_success()               # resets the streak
    cb.record_failure()
    assert cb.allow()                 # not tripped — streak was cleared


# ----------------------------------------------------------------- reconcile
def test_reconcile_detects_desync():
    assert reconcile(1.0, 1.0).passed
    bad = reconcile(1.0, 0.5)
    assert not bad.passed and "desync" in bad.detail


# ------------------------------------------------------- router integration
def _ts():
    import datetime as dt
    return dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)


def test_router_blocks_unsafe_order_and_emits_decision():
    mock = MockBroker()
    router = RealOrderRouter(ExecutionEngine(mock, dry_run=False), connected_fn=lambda: False)
    bus = EventBus()
    router.attach(bus)
    bus.publish(ev_signal("BTC/USDT", "buy", 100.0, 95.0, 110.0, "x", _ts()))
    bus.publish(ev_order("eng-1", "BTC/USDT", "buy", 2.0))

    assert mock.orders == []                              # nothing sent
    assert router.decisions[-1].verdict == "rejected"
    decision_events = [e for e in bus.replay() if e.get("type") == "decision"]
    assert decision_events and decision_events[-1]["verdict"] == "rejected"


def test_router_allows_safe_order():
    mock = MockBroker()
    router = RealOrderRouter(ExecutionEngine(mock, dry_run=False))
    bus = EventBus()
    router.attach(bus)
    bus.publish(ev_signal("BTC/USDT", "buy", 100.0, 95.0, 110.0, "x", _ts()))
    bus.publish(ev_order("eng-1", "BTC/USDT", "buy", 2.0))
    assert len(mock.orders) == 1 and router.decisions[-1].verdict == "allowed"


def test_router_duplicate_prevention_until_closed():
    mock = MockBroker()
    router = RealOrderRouter(ExecutionEngine(mock, dry_run=False))
    bus = EventBus()
    router.attach(bus)
    bus.publish(ev_signal("BTC/USDT", "buy", 100.0, 95.0, 110.0, "x", _ts()))
    bus.publish(ev_order("eng-1", "BTC/USDT", "buy", 1.0))      # opens
    bus.publish(ev_order("eng-2", "BTC/USDT", "buy", 1.0))      # duplicate -> blocked
    assert len(mock.orders) == 1
    assert router.decisions[-1].verdict == "rejected"
    # close the position, then a new entry is allowed again
    bus.publish(ev_trade_closed("BTC/USDT", "buy", 100, 110, 1.0, 10.0, 2.0, _ts()))
    bus.publish(ev_order("eng-3", "BTC/USDT", "buy", 1.0))
    assert len(mock.orders) == 2


def test_router_retries_then_trips_breaker():
    # threshold 2: two submit failures (each exhausts its own retries) -> tripped.
    flaky = FlakyBroker(fail_n=99)
    safety = ExecutionSafety(SafetyConfig(circuit_threshold=2))
    router = RealOrderRouter(ExecutionEngine(flaky, dry_run=False), safety=safety,
                             retry=RetryPolicy(attempts=2, sleep=lambda _: None))
    bus = EventBus()
    router.attach(bus)
    bus.publish(ev_signal("BTC/USDT", "buy", 100.0, 95.0, 110.0, "x", _ts()))
    bus.publish(ev_order("e1", "BTC/USDT", "buy", 1.0))        # fails -> 1
    bus.publish(ev_trade_closed("BTC/USDT", "buy", 100, 110, 1, 1, 1, _ts()))  # clear dup
    bus.publish(ev_order("e2", "BTC/USDT", "buy", 1.0))        # fails -> trips
    bus.publish(ev_order("e3", "BTC/USDT", "buy", 1.0))        # blocked by breaker
    assert router.circuit.tripped
    assert router.decisions[-1].verdict == "blocked"
    assert flaky.orders == []                                  # never succeeded
