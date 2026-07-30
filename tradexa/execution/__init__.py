"""Production-grade order execution across multiple venues.

    engine = ExecutionEngine(router=SmartOrderRouter(), retry=RetryPolicy())
    engine.add_venue(binance)
    engine.add_venue(bybit)

    outcome = engine.submit(order, strategy="ema", signal_id="sig-42")
    outcome.ok, outcome.unresolved, outcome.record.remaining_qty

Idempotency is the foundation, not a feature: every other mechanism here —
retry, failover, reconnection, replay — works by doing something again, and
each is a way to open a position twice without a client id derived from the
intent rather than from the attempt.

The package is pure logic over injected transports. A ``Venue`` is a Protocol
with five methods and a websocket is a ``connect(endpoint)`` callable, which is
what lets a timeout mid-submit, a stale-but-open socket and a venue that
disagrees about your position all be tested rather than hoped about.
"""
from tradexa.execution.engine import ExecutionEngine, SubmitOutcome
from tradexa.execution.idempotency import (
    DEFAULT_TTL, IdempotencyStore, Submission, client_order_id, intent_key,
)
from tradexa.execution.monitor import (
    ConnectionSupervisor, Endpoint, LinkState, LinkStats, ReconnectPolicy,
    StreamMonitor,
)
from tradexa.execution.orders import (
    Amendment, FillEvent, OrderRecord, OrderStatus, signed_qty,
)
from tradexa.execution.reconciliation import (
    Discrepancy, Finding, QTY_TOLERANCE, ReconciliationReport, Severity,
    reconcile, reconcile_orders, reconcile_positions,
)
from tradexa.execution.reliability import (
    Attempt, CircuitBreaker, CircuitOpen, CircuitState, LatencyMetrics,
    RetryDecision, RetryPolicy, run_with_retry,
)
from tradexa.execution.router import (
    Candidate, Route, RoutingStrategy, SmartOrderRouter, VenueProfile,
)
from tradexa.execution.venues import (
    Venue, VenueCapabilities, VenueHealth, VenueState,
)

__all__ = [
    "ExecutionEngine", "SubmitOutcome",
    "IdempotencyStore", "Submission", "client_order_id", "intent_key",
    "DEFAULT_TTL",
    "OrderRecord", "OrderStatus", "FillEvent", "Amendment", "signed_qty",
    "RetryPolicy", "RetryDecision", "Attempt", "run_with_retry",
    "CircuitBreaker", "CircuitState", "CircuitOpen", "LatencyMetrics",
    "SmartOrderRouter", "RoutingStrategy", "VenueProfile", "Route", "Candidate",
    "Venue", "VenueState", "VenueHealth", "VenueCapabilities",
    "ConnectionSupervisor", "StreamMonitor", "Endpoint", "ReconnectPolicy",
    "LinkState", "LinkStats",
    "reconcile", "reconcile_positions", "reconcile_orders",
    "ReconciliationReport", "Finding", "Discrepancy", "Severity",
    "QTY_TOLERANCE",
]
