"""The execution engine, tested at the failures it exists to survive.

The ordering of this file follows the cost of getting each thing wrong.
Duplicate orders come first, because every other mechanism here — retry,
failover, reconnection — is a way of doing something again, and each is a way to
open a position twice.

Venues are fakes throughout, and deliberately hostile ones: they time out, they
half-fill, they report the same fill twice, they disagree about the book. A
venue that only ever succeeds tests nothing an execution engine is for.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Order, OrderType, Position, Side
from tradexa.core.models import ExecutionReport, ExecutionStatus
from tradexa.execution import (
    CircuitBreaker, CircuitState, ConnectionSupervisor, Endpoint, ExecutionEngine,
    FillEvent, IdempotencyStore, LatencyMetrics, LinkState, OrderRecord,
    OrderStatus, ReconnectPolicy, RetryDecision, RetryPolicy, RoutingStrategy,
    SmartOrderRouter, StreamMonitor, VenueCapabilities, VenueHealth, VenueProfile,
    VenueState, client_order_id, reconcile, run_with_retry,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


def _order(symbol="BTCUSDT", side=Side.BUY, qty=1.0, price=100.0):
    return Order(symbol=symbol, side=side, qty=qty, order_type=OrderType.LIMIT,
                 limit_price=price)


class FakeVenue:
    """A venue that can be told exactly how to misbehave."""

    def __init__(self, name="fake", *, fail_times=0, error=None, fill=None,
                 positions=(), can_amend=True):
        self.name = name
        self.fail_times = fail_times
        self.error = error or ConnectionError("connection refused")
        self.fill = fill
        self._positions = list(positions)
        self.can_amend = can_amend
        self.submitted: list[str] = []
        self.cancelled: list[str] = []
        self.amended: list[tuple] = []

    def submit(self, order, *, client_id):
        self.submitted.append(client_id)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.error
        if self.fill is not None:
            qty, price = self.fill
            status = (ExecutionStatus.FILLED if qty >= order.qty
                      else ExecutionStatus.PARTIAL)
            return ExecutionReport(status=status, order=order,
                                   broker_order_id=f"{self.name}-1",
                                   filled_qty=qty, avg_fill_price=price)
        return ExecutionReport(status=ExecutionStatus.ACCEPTED, order=order,
                               broker_order_id=f"{self.name}-1")

    def cancel(self, broker_order_id):
        self.cancelled.append(broker_order_id)
        return ExecutionReport(status=ExecutionStatus.CANCELLED,
                               order=_order(), broker_order_id=broker_order_id)

    def amend(self, broker_order_id, *, qty=None, limit_price=None):
        if not self.can_amend:
            raise NotImplementedError("this venue cannot amend")
        self.amended.append((broker_order_id, qty, limit_price))
        return ExecutionReport(status=ExecutionStatus.ACCEPTED, order=_order(),
                               broker_order_id=broker_order_id)

    def fetch_order(self, broker_order_id):
        return None

    def fetch_positions(self):
        return list(self._positions)


def _engine(**kw):
    kw.setdefault("retry", RetryPolicy(max_attempts=2, base_delay=0, jitter=0))
    kw.setdefault("sleep", lambda _s: None)
    return ExecutionEngine(**kw)


# ═══════════════════════════════════════════ idempotency

def test_the_same_intent_produces_the_same_client_id():
    """The property everything else rests on. A random id per attempt turns
    every retry into a new order."""
    assert client_order_id(_order()) == client_order_id(_order())


def test_a_different_trade_produces_a_different_id():
    assert client_order_id(_order(qty=1.0)) != client_order_id(_order(qty=2.0))
    assert client_order_id(_order(price=100)) != client_order_id(_order(price=101))
    assert client_order_id(_order(side=Side.BUY)) != client_order_id(_order(side=Side.SELL))


def test_two_signals_wanting_the_same_trade_are_two_orders():
    """Scaling into a position is legitimate. Deduplicating on the trade alone
    would silently swallow the second entry — the failure mode of over-eager
    deduplication, and worse than the duplicate it prevents because nothing
    reports it."""
    assert (client_order_id(_order(), signal_id="a")
            != client_order_id(_order(), signal_id="b"))


def test_the_id_is_short_enough_for_a_real_exchange():
    """Exchanges cap client id length; a rejection for length pushes the caller
    into generating a random one, losing the property at the moment it matters."""
    assert len(client_order_id(_order())) <= 36


def test_a_repeated_submit_is_not_sent_twice():
    engine = _engine()
    venue = FakeVenue()
    engine.add_venue(venue)
    order = _order()
    first = engine.submit(order, signal_id="s1")
    second = engine.submit(order, signal_id="s1")
    assert first.ok and second.duplicate
    assert len(venue.submitted) == 1, "the venue saw the same order twice"


def test_the_duplicate_returns_the_original_order_not_an_error():
    engine = _engine()
    engine.add_venue(FakeVenue())
    engine.submit(_order(), signal_id="s1")
    second = engine.submit(_order(), signal_id="s1")
    assert second.record is not None
    assert "not resubmitted" in second.explain()


def test_an_in_flight_intent_is_never_evicted_by_the_ttl():
    """An order whose fate is unknown is exactly the one whose id must not be
    reissued. Letting it expire hands the duplicate back on a timer."""
    store = IdempotencyStore(ttl=timedelta(seconds=0))
    store.begin("cid-1", "intent")
    store.begin("cid-2", "intent-2")
    store.complete("cid-2", status="filled")
    store.begin("cid-3", "intent-3")          # triggers eviction
    assert "cid-1" in store, "an unresolved submission was forgotten"


def test_release_allows_a_resubmit_after_a_provable_non_delivery():
    store = IdempotencyStore()
    store.begin("cid", "intent")
    store.release("cid")
    _record, is_new = store.begin("cid", "intent")
    assert is_new


# ═══════════════════════════════════════════ retry

def test_a_connection_error_is_retried():
    """A connection that never opened cannot have delivered an order — the one
    network failure that is safely retryable."""
    calls = []

    def call():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("refused")
        return "ok"

    result, attempts, error = run_with_retry(
        call, RetryPolicy(max_attempts=3, base_delay=0, jitter=0),
        sleep=lambda _s: None)
    assert result == "ok" and error is None and len(attempts) == 3


def test_a_timeout_is_not_retried_by_default():
    """The most important line in the package. A timed-out request may have
    reached the venue; resending is how a blip becomes a double position."""
    policy = RetryPolicy()
    assert policy.classify(TimeoutError("no answer")) is RetryDecision.RECONCILE


def test_a_timeout_can_be_retried_when_a_caller_insists():
    assert (RetryPolicy(retry_timeouts=True).classify(TimeoutError())
            is RetryDecision.RETRY)


def test_retry_policy_reads_the_platforms_own_retryable_flag():
    """Retry as a property of the error type, not a guess from its message —
    which is how "connection reset" and "position would exceed limit" end up
    treated the same."""
    from tradexa.core.exceptions import ExchangeConnectionError, OrderRejected
    policy = RetryPolicy()
    assert policy.classify(ExchangeConnectionError("blip")) is RetryDecision.RETRY
    assert policy.classify(OrderRejected("bad price")) is RetryDecision.FAIL


def test_backoff_grows_and_is_capped():
    policy = RetryPolicy(base_delay=1, multiplier=2, max_delay=5, jitter=0)
    assert [policy.delay_for(n) for n in (1, 2, 3, 4, 5)] == [1, 2, 4, 5, 5]


def test_jitter_spreads_the_retry():
    """Without it every client that failed in one blip retries at the same
    instant, and the recovering venue meets a synchronised wave."""
    policy = RetryPolicy(base_delay=1, jitter=0.5)
    delays = {policy.delay_for(1) for _ in range(20)}
    assert len(delays) > 1


def test_every_attempt_is_recorded_even_when_all_fail():
    """The record of what was tried is what says whether an order might be live
    at the venue."""
    result, attempts, error = run_with_retry(
        lambda: (_ for _ in ()).throw(ConnectionError("nope")),
        RetryPolicy(max_attempts=3, base_delay=0, jitter=0), sleep=lambda _s: None)
    assert result is None and len(attempts) == 3 and error is not None


# ═══════════════════════════════════════════ circuit breaker

def test_the_circuit_opens_after_repeated_failures():
    breaker = CircuitBreaker("v", failure_threshold=3)
    for _ in range(3):
        breaker.record_failure("boom")
    assert breaker.state is CircuitState.OPEN
    assert not breaker.allows(NOW)


def test_the_circuit_allows_exactly_one_probe_after_the_cooldown():
    """A timer that resumes full flow meets an ongoing outage with the entire
    backlog at once."""
    breaker = CircuitBreaker("v", failure_threshold=1, cooldown=timedelta(seconds=30))
    breaker.record_failure("boom", now=NOW)
    assert not breaker.allows(NOW + timedelta(seconds=10))
    assert breaker.allows(NOW + timedelta(seconds=31))
    assert breaker.state is CircuitState.HALF_OPEN


def test_a_failed_probe_restarts_the_full_cooldown():
    """A venue that just failed its test has earned no credit for being tried."""
    breaker = CircuitBreaker("v", failure_threshold=1, cooldown=timedelta(seconds=30))
    breaker.record_failure("boom", now=NOW)
    breaker.allows(NOW + timedelta(seconds=31))          # → half open
    breaker.record_failure("still broken", now=NOW + timedelta(seconds=31))
    assert breaker.state is CircuitState.OPEN
    assert not breaker.allows(NOW + timedelta(seconds=40))


def test_closing_needs_more_than_one_success():
    """One success after a sustained outage is noise as often as recovery."""
    breaker = CircuitBreaker("v", failure_threshold=1, success_threshold=2,
                             cooldown=timedelta(seconds=1))
    breaker.record_failure("boom", now=NOW)
    breaker.allows(NOW + timedelta(seconds=2))
    breaker.record_success()
    assert breaker.state is CircuitState.HALF_OPEN
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED


def test_an_open_circuit_keeps_orders_off_that_venue():
    engine = _engine()
    broken = FakeVenue("broken", fail_times=99)
    healthy = FakeVenue("healthy")
    profile = engine.add_venue(broken, breaker=CircuitBreaker("broken",
                                                              failure_threshold=1))
    engine.add_venue(healthy)
    engine.submit(_order(), signal_id="one")
    assert profile.breaker.state is CircuitState.OPEN
    before = len(broken.submitted)
    result = engine.submit(_order(), signal_id="two")
    assert len(broken.submitted) == before, "an open circuit was called anyway"
    assert result.ok and result.record.venue == "healthy"


# ═══════════════════════════════════════════ routing and failover

def test_routing_returns_a_chain_not_a_choice():
    """A router that returns one venue makes failover someone else's problem,
    and someone else re-implements the ranking in the retry loop."""
    router = SmartOrderRouter([
        VenueProfile("a", VenueHealth("a")), VenueProfile("b", VenueHealth("b"))])
    route = router.route(_order())
    assert route.primary and route.fallbacks


def test_a_down_venue_is_excluded_with_a_reason():
    router = SmartOrderRouter([
        VenueProfile("up", VenueHealth("up")),
        VenueProfile("down", VenueHealth("down", state=VenueState.DOWN,
                                         last_error="503s"))])
    route = router.route(_order())
    assert route.primary == "up"
    assert any("down" in c.venue and "503" in c.reason for c in route.excluded)


def test_a_venue_that_cannot_trade_the_symbol_is_excluded():
    router = SmartOrderRouter([
        VenueProfile("crypto", VenueHealth("crypto"), symbols=("BTCUSDT",)),
        VenueProfile("stocks", VenueHealth("stocks"), symbols=("AAPL",))])
    assert router.route(_order("BTCUSDT")).primary == "crypto"
    assert router.route(_order("AAPL")).primary == "stocks"


def test_an_unmeasured_venue_is_not_the_fastest():
    """Ranking it first sends every order to the venue nothing is known about."""
    fast = VenueHealth("fast")
    fast.record_success(5.0)
    router = SmartOrderRouter([VenueProfile("fast", fast),
                               VenueProfile("unknown", VenueHealth("unknown"))])
    assert router.route(_order(), strategy=RoutingStrategy.FASTEST).primary == "fast"


def test_balanced_routing_prefers_health_over_speed():
    """A fast venue that is half-failing is not fast — its speed is measured on
    the requests that succeeded."""
    quick_but_sick = VenueHealth("sick", state=VenueState.DEGRADED)
    quick_but_sick.record_success(1.0)
    slow_but_well = VenueHealth("well")
    slow_but_well.record_success(50.0)
    router = SmartOrderRouter([VenueProfile("sick", quick_but_sick),
                               VenueProfile("well", slow_but_well)])
    assert router.route(_order()).primary == "well"


def test_cheapest_routing_ranks_on_fees():
    router = SmartOrderRouter([
        VenueProfile("dear", VenueHealth("dear"),
                     capabilities=VenueCapabilities(taker_fee_bps=10)),
        VenueProfile("cheap", VenueHealth("cheap"),
                     capabilities=VenueCapabilities(taker_fee_bps=2))])
    assert router.route(_order(), strategy=RoutingStrategy.CHEAPEST).primary == "cheap"


def test_routing_is_deterministic():
    """A router whose output depends on dict ordering makes an incident
    impossible to reconstruct."""
    router = SmartOrderRouter([VenueProfile(n, VenueHealth(n))
                               for n in ("c", "a", "b")])
    assert {router.route(_order()).venues for _ in range(5)} == {("a", "b", "c")}


def test_a_refused_connection_fails_over_to_the_next_venue():
    engine = _engine()
    engine.add_venue(FakeVenue("first", fail_times=99))
    second = FakeVenue("second")
    engine.add_venue(second)
    result = engine.submit(_order())
    assert result.ok and result.record.venue == "second"
    assert result.venues_tried == ["first", "second"]


def test_failover_keeps_the_same_client_id():
    """So a first attempt that DID land shows up in reconciliation as one intent
    at two venues — a finding someone can act on — not two unrelated orders."""
    engine = _engine()
    first, second = FakeVenue("first", fail_times=99), FakeVenue("second")
    engine.add_venue(first)
    engine.add_venue(second)
    engine.submit(_order())
    assert first.submitted[0] == second.submitted[0]


def test_a_timeout_does_not_fail_over():
    """The most consequential rule in the engine. Failing over after a timeout
    is placing the same order at a second venue while it may already be live at
    the first."""
    engine = _engine(retry=RetryPolicy(max_attempts=1, base_delay=0, jitter=0))
    timing_out = FakeVenue("slow", fail_times=99, error=TimeoutError("no answer"))
    backup = FakeVenue("backup")
    # Preference, not alphabetical luck: BALANCED breaks ties by preference then
    # name, and an earlier version of this test only passed because "backup"
    # sorts before "slow" — it was asserting the timeout rule while exercising
    # the opposite routing order.
    engine.add_venue(timing_out, profile=VenueProfile(
        "slow", VenueHealth("slow"), breaker=CircuitBreaker("slow"), preference=0))
    engine.add_venue(backup, profile=VenueProfile(
        "backup", VenueHealth("backup"), breaker=CircuitBreaker("backup"),
        preference=1))
    result = engine.submit(_order(), routing=RoutingStrategy.PREFERRED)
    assert backup.submitted == [], "failed over after a timeout"
    assert result.unresolved
    assert any("duplicate position" in n for n in result.notes)


def test_an_unresolved_order_is_not_reported_as_a_failure():
    """A caller that treats it as failed and resubmits opens the position
    twice."""
    engine = _engine(retry=RetryPolicy(max_attempts=1, base_delay=0, jitter=0))
    engine.add_venue(FakeVenue("slow", fail_times=99, error=TimeoutError()))
    result = engine.submit(_order())
    assert result.record.status is OrderStatus.UNKNOWN
    assert "UNRESOLVED" in result.explain()


def test_failover_is_bounded():
    """Unbounded failover across a chain during a market-wide outage is one
    chance per venue to double a position."""
    engine = _engine()
    venues = [FakeVenue(f"v{i}", fail_times=99) for i in range(4)]
    for v in venues:
        engine.add_venue(v)
    result = engine.submit(_order(), max_venues=2)
    assert len(result.venues_tried) == 2


# ═══════════════════════════════════════════ partial fills

def test_fills_accumulate():
    engine = _engine()
    engine.add_venue(FakeVenue())
    result = engine.submit(_order(qty=1.0))
    engine.apply_fill(result.client_id, FillEvent("f1", 0.3, 100.0))
    engine.apply_fill(result.client_id, FillEvent("f2", 0.5, 102.0))
    record = engine.order(result.client_id)
    assert record.filled_qty == pytest.approx(0.8)
    assert record.remaining_qty == pytest.approx(0.2)
    assert record.status is OrderStatus.PARTIALLY_FILLED


def test_the_same_fill_twice_is_ignored():
    """A websocket push and a REST reconciliation poll both report it. Applying
    it twice inflates the position and the average price."""
    engine = _engine()
    engine.add_venue(FakeVenue())
    result = engine.submit(_order())
    assert engine.apply_fill(result.client_id, FillEvent("f1", 0.5, 100.0))
    assert not engine.apply_fill(result.client_id, FillEvent("f1", 0.5, 100.0))
    assert engine.order(result.client_id).filled_qty == pytest.approx(0.5)


def test_the_average_price_is_volume_weighted():
    record = OrderRecord("cid", _order(qty=3.0))
    record.apply_fill(FillEvent("a", 1.0, 100.0))
    record.apply_fill(FillEvent("b", 2.0, 130.0))
    assert record.average_price == pytest.approx(120.0)


def test_an_unfilled_order_has_no_average_price():
    """None, not zero and not the limit price — substituting the limit reports a
    fill that has not happened."""
    assert OrderRecord("cid", _order()).average_price is None


def test_a_completing_fill_moves_the_order_to_filled():
    record = OrderRecord("cid", _order(qty=1.0))
    record.apply_fill(FillEvent("a", 1.0, 100.0))
    assert record.status is OrderStatus.FILLED and record.remaining_qty == 0


def test_a_late_cancel_cannot_erase_a_fill():
    """Venues send stale updates out of order; a cancel that lost the race to a
    fill would otherwise delete a real position."""
    record = OrderRecord("cid", _order(qty=1.0))
    record.apply_fill(FillEvent("a", 1.0, 100.0))
    record.mark(OrderStatus.CANCELLED)
    assert record.status is OrderStatus.FILLED


def test_a_report_carrying_a_fill_is_recorded_as_one():
    """An ACCEPTED report that already includes a partial fill would otherwise
    leave the engine believing nothing executed."""
    engine = _engine()
    engine.add_venue(FakeVenue(fill=(0.4, 101.0)))
    result = engine.submit(_order(qty=1.0))
    record = engine.order(result.client_id)
    assert record.filled_qty == pytest.approx(0.4)
    assert record.status is OrderStatus.PARTIALLY_FILLED


# ═══════════════════════════════════════════ amend, cancel/replace

def test_an_amendment_updates_the_local_order_too():
    """An amendment that changed the venue's view but not ours makes every later
    calculation wrong by the difference."""
    engine = _engine()
    venue = FakeVenue()
    engine.add_venue(venue)
    result = engine.submit(_order(qty=1.0))
    engine.amend(result.client_id, qty=0.5, limit_price=99.0)
    record = engine.order(result.client_id)
    assert venue.amended and record.order.qty == 0.5
    assert record.order.limit_price == 99.0


def test_a_venue_that_cannot_amend_falls_back_to_cancel_replace():
    engine = _engine()
    venue = FakeVenue(can_amend=False)
    profile = engine.add_venue(venue)
    profile.capabilities = VenueCapabilities(amend=False)
    result = engine.submit(_order(qty=1.0))
    replacement = engine.amend(result.client_id, limit_price=99.0)
    assert venue.cancelled, "the original was not cancelled"
    assert replacement.record.replaces == result.client_id


def test_a_replacement_is_sized_to_the_remainder():
    """Replacing a half-filled order with a full-size one is how a convenience
    becomes a double position."""
    engine = _engine()
    venue = FakeVenue(can_amend=False)
    profile = engine.add_venue(venue)
    profile.capabilities = VenueCapabilities(amend=False)
    result = engine.submit(_order(qty=1.0))
    engine.apply_fill(result.client_id, FillEvent("f1", 0.6, 100.0))
    replacement = engine.amend(result.client_id, limit_price=99.0)
    assert replacement.record.order.qty == pytest.approx(0.4)


def test_the_replacement_is_not_sent_if_the_cancel_fails():
    """Two live orders is worse than none."""
    engine = _engine()

    class WontCancel(FakeVenue):
        def cancel(self, broker_order_id):
            raise ConnectionError("cancel failed")

    venue = WontCancel(can_amend=False)
    profile = engine.add_venue(venue)
    profile.capabilities = VenueCapabilities(amend=False)
    result = engine.submit(_order())
    outcome = engine.amend(result.client_id, limit_price=99.0)
    assert not outcome.ok and "NOT sent" in outcome.error
    assert len(venue.submitted) == 1


def test_a_fully_filled_order_cannot_be_amended():
    engine = _engine()
    engine.add_venue(FakeVenue(fill=(1.0, 100.0)))
    result = engine.submit(_order(qty=1.0))
    outcome = engine.amend(result.client_id, limit_price=99.0)
    assert not outcome.ok and "terminal" in outcome.error


def test_a_replacement_gets_its_own_client_id():
    """Reusing the original would make the idempotency store reject the
    replacement as a duplicate of the thing it replaces."""
    engine = _engine()
    venue = FakeVenue(can_amend=False)
    profile = engine.add_venue(venue)
    profile.capabilities = VenueCapabilities(amend=False)
    result = engine.submit(_order())
    replacement = engine.amend(result.client_id, limit_price=99.0)
    assert replacement.client_id != result.client_id


# ═══════════════════════════════════════════ reconciliation

def test_a_position_the_venue_does_not_have_is_critical():
    findings = reconcile(venue="binance", local_positions={"BTCUSDT": 1.0},
                         venue_positions=[]).findings
    assert findings[0].kind.value == "missing_at_venue"
    assert findings[0].severity.value == "critical"


def test_a_position_we_do_not_know_about_is_critical():
    """An unmanaged position has no stop from this engine."""
    report = reconcile(venue="binance", local_positions={},
                       venue_positions=[Position("ETHUSDT", 2.0, 3000.0)])
    assert report.findings[0].kind.value == "unknown_locally"
    assert "no stop" in report.findings[0].suggested_action


def test_an_inverted_position_is_not_a_match():
    """Comparing absolute quantities calls a fully inverted position a match —
    the most expensive possible false negative."""
    report = reconcile(venue="v", local_positions={"BTCUSDT": 1.0},
                       venue_positions=[Position("BTCUSDT", -1.0, 100.0)])
    assert report.findings[0].kind.value == "side_mismatch"
    assert report.findings[0].severity.value == "critical"


def test_rounding_noise_is_not_a_discrepancy():
    """Without a tolerance every reconciliation reports drift that is not
    there."""
    report = reconcile(venue="v", local_positions={"BTCUSDT": 1.0},
                       venue_positions=[Position("BTCUSDT", 1.0 + 1e-12, 100.0)])
    assert report.clean


def test_reconciliation_reports_and_does_not_repair():
    """An automatic reconciler that "fixes" a discrepancy by trading is one bad
    exchange response from liquidating a real position."""
    report = reconcile(venue="v", local_positions={"BTCUSDT": 1.0},
                       venue_positions=[Position("BTCUSDT", 0.5, 100.0)])
    assert report.findings[0].suggested_action
    assert all(hasattr(f, "suggested_action") for f in report.findings)


def test_a_clean_report_says_what_it_checked():
    """A report that only lists problems cannot say whether the check ran."""
    report = reconcile(venue="v", local_positions={"BTCUSDT": 1.0},
                       venue_positions=[Position("BTCUSDT", 1.0, 100.0)])
    assert report.clean and "1 position" in report.explain()


def test_a_failed_fetch_is_not_reported_as_being_in_sync():
    engine = _engine()

    class Unreachable(FakeVenue):
        def fetch_positions(self):
            raise ConnectionError("down")

    engine.add_venue(Unreachable("down"))
    report = engine.reconcile_venue("down")
    assert report.clean is True          # no findings…
    assert any("NOT the same as being in sync" in n for n in report.notes)


def test_the_engines_own_book_comes_from_its_fills():
    engine = _engine()
    engine.add_venue(FakeVenue(positions=[Position("BTCUSDT", 0.5, 100.0)]))
    result = engine.submit(_order(qty=1.0))
    engine.apply_fill(result.client_id, FillEvent("f1", 0.5, 100.0))
    assert engine.local_positions() == {"BTCUSDT": pytest.approx(0.5)}
    assert engine.reconcile_venue("fake").clean


def test_a_sell_reduces_the_local_position():
    engine = _engine()
    engine.add_venue(FakeVenue())
    long = engine.submit(_order(qty=1.0), signal_id="long")
    short = engine.submit(_order(side=Side.SELL, qty=0.4), signal_id="short")
    engine.apply_fill(long.client_id, FillEvent("a", 1.0, 100.0))
    engine.apply_fill(short.client_id, FillEvent("b", 0.4, 100.0))
    assert engine.local_positions()["BTCUSDT"] == pytest.approx(0.6)


# ═══════════════════════════════════════════ stream supervision

def _supervisor(**kw):
    kw.setdefault("connect", lambda endpoint: object())
    kw.setdefault("heartbeat_interval", timedelta(seconds=10))
    return ConnectionSupervisor("binance", [Endpoint("wss://primary"),
                                            Endpoint("wss://backup", priority=1)], **kw)


def test_a_connection_starts_healthy():
    link = _supervisor()
    assert link.connect(NOW) and link.state is LinkState.CONNECTED


def test_an_open_but_silent_socket_goes_stale():
    """The dangerous failure: TCP holds, the client believes it is subscribed,
    and fills arrive nowhere. Only a heartbeat deadline catches it."""
    link = _supervisor()
    link.connect(NOW)
    assert link.check(NOW + timedelta(seconds=10)) is LinkState.CONNECTED
    assert link.check(NOW + timedelta(seconds=60)) is LinkState.STALE


def test_any_traffic_clears_staleness():
    """A venue streaming trades but not pings is not stale, and reconnecting it
    would drop a working subscription."""
    link = _supervisor()
    link.connect(NOW)
    link.check(NOW + timedelta(seconds=60))
    link.record_message(NOW + timedelta(seconds=61))
    assert link.state is LinkState.CONNECTED


def test_a_link_that_never_beat_is_not_declared_stale():
    """Treating "never heard from" as "gone silent" marks every REST-only venue
    dead at startup."""
    link = _supervisor()
    assert link.check(NOW + timedelta(hours=1)) is LinkState.DISCONNECTED


def test_reconnect_backoff_grows():
    link = _supervisor(connect=_boom, policy=ReconnectPolicy(base_delay=1,
                                                             multiplier=2,
                                                             jitter=0))
    link.connect(NOW)
    first = link.next_delay()
    link.connect(NOW)
    assert link.next_delay() >= first


def _boom(endpoint):
    raise ConnectionError("refused")


def test_repeated_failures_move_to_the_next_endpoint():
    link = _supervisor(connect=_boom,
                       policy=ReconnectPolicy(attempts_per_endpoint=2, jitter=0))
    link.connect(NOW)
    link.connect(NOW)
    assert link.endpoint.url == "wss://backup"
    assert link.stats.failovers == 1


def test_the_endpoint_chain_wraps_back_to_the_primary():
    """A chain that only walks forwards ends up parked on the worst endpoint."""
    link = _supervisor(connect=_boom,
                       policy=ReconnectPolicy(attempts_per_endpoint=1, jitter=0))
    link.connect(NOW)
    assert link.endpoint.url == "wss://backup"
    link.connect(NOW)
    assert link.endpoint.url == "wss://primary", (
        "the chain walked off the end instead of returning to the primary")


def test_a_supervisor_can_give_up_loudly():
    link = _supervisor(connect=_boom,
                       policy=ReconnectPolicy(max_total_attempts=2, jitter=0))
    link.connect(NOW)
    link.connect(NOW)
    assert link.state is LinkState.FAILED


def test_downtime_is_measured():
    link = _supervisor()
    link.connect(NOW)
    link.disconnect("dropped", NOW + timedelta(seconds=10))
    link.connect(NOW + timedelta(seconds=25))
    assert link.stats.total_downtime_s == pytest.approx(15.0)


def test_the_monitor_separates_healthy_from_broken_links():
    monitor = StreamMonitor()
    up = _supervisor()
    up.connect(NOW)
    monitor.add(up)
    down = ConnectionSupervisor("bybit", [Endpoint("wss://x")], connect=_boom)
    down.connect(NOW)
    monitor.add(down)
    assert monitor.healthy == ("binance",)
    assert monitor.unhealthy == ("bybit",)
    assert monitor.as_dict()["all_healthy"] is False


# ═══════════════════════════════════════════ latency and health

def test_latency_is_reported_as_percentiles():
    """An average across a venue that answers in 5ms and sometimes 4s describes
    neither case."""
    metrics = LatencyMetrics()
    for value in list(range(1, 100)) + [4000]:
        metrics.record("submit", value)
    assert metrics.percentile("submit", 50) < metrics.percentile("submit", 99)
    assert metrics.summary()["submit"]["max"] == 4000


def test_latency_of_an_unused_operation_is_unavailable():
    assert LatencyMetrics().percentile("submit", 50) is None


def test_the_engine_records_latency_per_venue():
    engine = _engine()
    engine.add_venue(FakeVenue("binance"))
    engine.submit(_order())
    assert engine.metrics.percentile("binance.submit", 50) is not None


def test_health_tracks_failures_and_recovers_to_degraded_not_up():
    """One success after an outage is a sign, not a guarantee."""
    health = VenueHealth("v", state=VenueState.DOWN)
    health.record_success(10.0)
    assert health.state is VenueState.DEGRADED


def test_the_health_endpoint_answers_in_one_call():
    engine = _engine()
    engine.add_venue(FakeVenue("binance"))
    engine.submit(_order())
    health = engine.health()
    for key in ("venues", "circuits", "streams", "latency", "orders",
                "in_flight_intents"):
        assert key in health


# ═══════════════════════════════════════════ multiple exchanges at once

def test_orders_route_across_several_venues_simultaneously():
    engine = _engine()
    for name, symbol in (("binance", "BTCUSDT"), ("alpaca", "AAPL")):
        venue = FakeVenue(name)
        profile = engine.add_venue(venue)
        profile.symbols = (symbol,)
    crypto = engine.submit(_order("BTCUSDT"), signal_id="c")
    equity = engine.submit(_order("AAPL"), signal_id="e")
    assert crypto.record.venue == "binance"
    assert equity.record.venue == "alpaca"


def test_reconciliation_covers_every_venue():
    engine = _engine()
    engine.add_venue(FakeVenue("binance", positions=[Position("BTCUSDT", 1.0, 100.0)]))
    engine.add_venue(FakeVenue("bybit", positions=[]))
    reports = engine.reconcile_all()
    assert set(reports) == {"binance", "bybit"}
    assert not reports["binance"].clean          # an unmanaged position
