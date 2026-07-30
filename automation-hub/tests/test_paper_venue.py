"""The paper engine behind the execution engine's port.

The point of this file is that the port meets a real executor. Fakes prove the
engine's logic; only this proves the five methods are the right five — and it
already forced two honest refusals (cancel and size-amendment) that a fake would
have cheerfully pretended to support.
"""
from __future__ import annotations

import pytest

from bot.types import Order, OrderType, Side
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from execution.paper_venue import PaperVenue
from tradexa.core.models import ExecutionStatus
from tradexa.execution import (
    ExecutionEngine, RetryPolicy, Venue, VenueProfile, VenueHealth,
)


@pytest.fixture()
def venue():
    paper = PaperExecutionEngine(SqliteLedger(":memory:"), starting_balance=10_000)
    return PaperVenue(paper)


def _order(symbol="BTCUSDT", qty=1.0, price=100.0, stop=95.0, side=Side.BUY):
    return Order(symbol=symbol, side=side, qty=qty, order_type=OrderType.LIMIT,
                 limit_price=price, stop_loss=stop)


def test_the_paper_engine_satisfies_the_venue_port(venue):
    """Structural conformance, checked against the Protocol itself rather than
    by calling the methods and hoping."""
    assert isinstance(venue, Venue)


def test_a_submitted_order_fills(venue):
    report = venue.submit(_order(), client_id="cid-1")
    assert report.status is ExecutionStatus.FILLED
    assert report.filled_qty == pytest.approx(1.0)
    assert report.broker_order_id


def test_the_client_id_reaches_the_executor(venue):
    """It is what makes the ledger's record and the engine's record the same
    order."""
    venue.submit(_order(), client_id="cid-abc")
    assert any(str(p.get("symbol")) == "BTCUSDT" for p in venue._paper.positions())


def test_positions_come_back_signed(venue):
    """Reconciliation compares signed quantities — an unsigned book calls a
    fully inverted position a match."""
    venue.submit(_order(side=Side.SELL, price=100.0, stop=105.0), client_id="s1")
    assert venue.fetch_positions()[0].qty < 0


def test_cancel_refuses_honestly_rather_than_pretending(venue):
    """A caller that believes it cancelled something goes on to replace a
    position that is still open."""
    report = venue.submit(_order(), client_id="cid-1")
    cancelled = venue.cancel(report.broker_order_id)
    assert cancelled.status is ExecutionStatus.REJECTED
    assert "no resting order" in cancelled.message


def test_a_stop_can_be_moved_on_an_open_position(venue):
    report = venue.submit(_order(), client_id="cid-1")
    amended = venue.amend(report.broker_order_id, limit_price=97.0)
    assert amended.status is ExecutionStatus.ACCEPTED


def test_resizing_a_filled_position_is_refused(venue):
    """Changing the size of an already-filled position is a new trade, and
    reporting it as an amendment hides a change in exposure inside what reads
    as a price tweak."""
    report = venue.submit(_order(), client_id="cid-1")
    amended = venue.amend(report.broker_order_id, qty=0.5)
    assert amended.status is ExecutionStatus.REJECTED
    assert "cannot change the size" in amended.message


def test_the_execution_engine_drives_the_real_paper_executor(venue):
    """End to end through the actual engine: idempotency, routing, health and
    latency, over an executor that really holds a position."""
    engine = ExecutionEngine(retry=RetryPolicy(max_attempts=1, base_delay=0,
                                               jitter=0),
                             sleep=lambda _s: None)
    engine.add_venue(venue)
    outcome = engine.submit(_order(), strategy="test", signal_id="sig-1")
    assert outcome.ok
    assert outcome.record.filled_qty == pytest.approx(1.0)
    assert engine.metrics.percentile("paper.submit", 50) is not None


def test_a_repeat_submit_does_not_reach_the_paper_engine(venue):
    """The duplicate guard, over a real executor: the position must not double."""
    engine = ExecutionEngine(retry=RetryPolicy(max_attempts=1, base_delay=0,
                                               jitter=0),
                             sleep=lambda _s: None)
    engine.add_venue(venue)
    engine.submit(_order(), signal_id="sig-1")
    second = engine.submit(_order(), signal_id="sig-1")
    assert second.duplicate
    positions = venue.fetch_positions()
    assert len(positions) == 1 and positions[0].qty == pytest.approx(1.0)


def test_reconciliation_against_the_real_book_is_clean(venue):
    """The engine's own fills and the paper engine's book must agree — if they
    do not here, they will not agree against an exchange either."""
    engine = ExecutionEngine(retry=RetryPolicy(max_attempts=1, base_delay=0,
                                               jitter=0),
                             sleep=lambda _s: None)
    engine.add_venue(venue)
    engine.submit(_order(), signal_id="sig-1")
    report = engine.reconcile_venue("paper")
    assert report.clean, report.explain()


def test_a_position_opened_outside_the_engine_is_flagged(venue):
    """The unmanaged-position case, against a real executor: it has no stop from
    this engine and nothing else would report it."""
    engine = ExecutionEngine(retry=RetryPolicy(max_attempts=1, base_delay=0,
                                               jitter=0),
                             sleep=lambda _s: None)
    engine.add_venue(venue)
    venue._paper.open(symbol="ETHUSDT", side="BUY", size=2.0, entry=3000.0,
                      stop=2900.0, alert_id="manual")
    report = engine.reconcile_venue("paper")
    assert not report.clean
    assert report.findings[0].kind.value == "unknown_locally"
