"""The execution engine.

Everything else in this package is a mechanism; this is the thing that uses
them in the right order. One submit does:

    idempotency  → has this exact intent already been sent?
    routing      → which venue, and which venues after that?
    circuit      → is this venue allowed to be called right now?
    retry        → attempt, classify the failure, back off
    failover     → next venue on the route, same client id
    record       → status, partial fills, latency, the whole attempt trail

The ordering is not arbitrary. Idempotency comes first because every mechanism
below it involves doing something again. Routing comes before the breaker so
that a refusal is a routing outcome rather than an exception. Retry sits inside
a venue and failover outside it, because a venue that is failing does not stop
failing while you back off against it.

**The client id survives failover.** The same intent submitted to a second venue
after the first timed out keeps its id, so if the first attempt did land, the
duplicate is visible in reconciliation as one intent at two venues — a finding
someone can act on — rather than as two unrelated orders nobody connects.

**Nothing here decides whether a trade is a good idea.** Size and permission
come from the risk engine; this engine's only judgement is how to get an
already-approved order to a venue and what to believe about the result.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from bot.types import Order, Position
from tradexa.core.models import ExecutionReport, ExecutionStatus
from tradexa.execution.idempotency import IdempotencyStore, client_order_id, intent_key
from tradexa.execution.monitor import StreamMonitor
from tradexa.execution.orders import (
    Amendment, FillEvent, OrderRecord, OrderStatus, signed_qty,
)
from tradexa.execution.reconciliation import ReconciliationReport, reconcile
from tradexa.execution.reliability import (
    Attempt, CircuitBreaker, LatencyMetrics, RetryDecision, RetryPolicy,
    run_with_retry,
)
from tradexa.execution.router import Route, RoutingStrategy, SmartOrderRouter, VenueProfile
from tradexa.execution.venues import Venue, VenueHealth, VenueState


@dataclass
class SubmitOutcome:
    """What happened to one submit, across every venue and attempt it touched."""

    client_id: str
    record: Optional[OrderRecord] = None
    report: Optional[ExecutionReport] = None
    route: Optional[Route] = None
    attempts: list[Attempt] = field(default_factory=list)
    venues_tried: list[str] = field(default_factory=list)
    duplicate: bool = False
    error: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.report and self.report.ok)

    @property
    def unresolved(self) -> bool:
        """The order's fate is unknown — it may be live at a venue.

        The state that must never be treated as a failure. A caller that
        resubmits on this opens the position twice.
        """
        return bool(self.record and self.record.status is OrderStatus.UNKNOWN)

    def explain(self) -> str:
        if self.duplicate:
            return f"{self.client_id}: duplicate intent — not resubmitted"
        if self.unresolved:
            return (f"{self.client_id}: UNRESOLVED after "
                    f"{', '.join(self.venues_tried)} — reconcile before retrying")
        if self.ok and self.record:
            return (f"{self.client_id}: {self.record.status.value} on "
                    f"{self.record.venue} after {len(self.attempts)} attempt(s)")
        return f"{self.client_id}: failed — {self.error}"

    def as_dict(self) -> dict[str, Any]:
        return {"client_id": self.client_id, "ok": self.ok,
                "duplicate": self.duplicate, "unresolved": self.unresolved,
                "order": self.record.as_dict() if self.record else None,
                "route": self.route.as_dict() if self.route else None,
                "venues_tried": list(self.venues_tried),
                "attempts": [{"n": a.number, "ok": a.ok,
                              "latency_ms": round(a.latency_ms, 3),
                              "error": a.error,
                              "decision": a.decision.value if a.decision else None}
                             for a in self.attempts],
                "error": self.error, "notes": list(self.notes)}


class ExecutionEngine:
    """Places orders across multiple venues, idempotently.

    Holds the local truth about every order it has submitted. That state is
    what reconciliation compares against the venues', and what makes a partial
    fill something the engine knows rather than something a caller reconstructs.
    """

    def __init__(self, *, router: Optional[SmartOrderRouter] = None,
                 retry: Optional[RetryPolicy] = None,
                 store: Optional[IdempotencyStore] = None,
                 metrics: Optional[LatencyMetrics] = None,
                 streams: Optional[StreamMonitor] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 on_event: Optional[Callable[[str, dict], None]] = None) -> None:
        self.router = router or SmartOrderRouter()
        self.retry = retry or RetryPolicy()
        self.store = store or IdempotencyStore()
        self.metrics = metrics or LatencyMetrics()
        self.streams = streams or StreamMonitor()
        self._sleep = sleep
        self._on_event = on_event
        self._venues: dict[str, Venue] = {}
        self._records: dict[str, OrderRecord] = {}
        self._lock = threading.RLock()

    # ─────────────────────────────────────────────────────────── registration
    def add_venue(self, venue: Venue, *, profile: Optional[VenueProfile] = None,
                  breaker: Optional[CircuitBreaker] = None) -> VenueProfile:
        """Register a venue and the state the engine keeps about it.

        Health and breaker are created here rather than taken from the venue:
        both are the engine's observations, and a venue reporting its own health
        is the last thing to notice it is broken.
        """
        name = getattr(venue, "name", None) or str(venue)
        profile = profile or VenueProfile(
            name=name, health=VenueHealth(name=name),
            breaker=breaker or CircuitBreaker(name=name))
        if profile.breaker is None:
            profile.breaker = breaker or CircuitBreaker(name=name)
        with self._lock:
            self._venues[name] = venue
            self.router.add(profile)
        return profile

    def venue(self, name: str) -> Optional[Venue]:
        return self._venues.get(name)

    @property
    def venue_names(self) -> tuple[str, ...]:
        return tuple(self._venues)

    # ──────────────────────────────────────────────────────────────── submit
    def submit(self, order: Order, *, strategy: str = "", signal_id: str = "",
               routing: Optional[RoutingStrategy] = None,
               max_venues: int = 2) -> SubmitOutcome:
        """Place an order, idempotently, with retry and failover.

        ``max_venues`` bounds failover. Unbounded failover across a five-venue
        chain during a market-wide outage is five chances to double a position,
        and the marginal venue is the one you trust least.
        """
        cid = client_order_id(order, strategy=strategy, signal_id=signal_id)
        intent = intent_key(order, strategy=strategy, signal_id=signal_id)
        outcome = SubmitOutcome(client_id=cid)

        submission, is_new = self.store.begin(cid, intent)
        if not is_new:
            # The guard. Everything reliability-related in this package is a way
            # of doing something twice; this is the one place that says no.
            outcome.duplicate = True
            outcome.record = self._records.get(cid)
            outcome.notes.append(
                f"intent already submitted (attempt {submission.attempts}, "
                f"status {submission.status}) — returning the existing outcome "
                "rather than placing a second order")
            return outcome

        route = self.router.route(order, strategy=routing)
        outcome.route = route
        if not route.candidates:
            outcome.error = route.explain()
            self.store.complete(cid, status="rejected")
            return outcome

        record = OrderRecord(client_id=cid, order=order)
        with self._lock:
            self._records[cid] = record
        # Attached immediately, not on success. Every branch below — accepted,
        # rejected, unresolved — needs the caller to be able to see the order's
        # state, and `unresolved` is READ from the record: without this the most
        # dangerous outcome in the engine reports itself as a plain failure,
        # which is the one thing a caller must not conclude.
        outcome.record = record

        for venue_name in route.venues[:max(1, max_venues)]:
            profile = self.router.profile(venue_name)
            venue = self._venues.get(venue_name)
            if venue is None or profile is None:
                continue
            if profile.breaker is not None and not profile.breaker.allows():
                outcome.notes.append(f"{venue_name}: circuit open, not attempted")
                continue

            outcome.venues_tried.append(venue_name)
            record.venue = venue_name
            report, attempts, error = self._attempt(venue, order, cid, profile)
            outcome.attempts.extend(attempts)

            if report is not None:
                self._apply_report(record, report)
                outcome.report = report
                self.store.complete(cid, status=record.status.value, result=report,
                                    broker_order_id=record.broker_order_id,
                                    venue=venue_name)
                self._emit("order.submitted", outcome.as_dict())
                return outcome

            # No report. Whether it is safe to try elsewhere depends entirely on
            # whether this attempt could have reached the venue.
            decision = attempts[-1].decision if attempts else RetryDecision.FAIL
            outcome.error = str(error) if error else "no report"
            if decision is RetryDecision.RECONCILE:
                record.mark(OrderStatus.UNKNOWN, error=outcome.error)
                self.store.complete(cid, status="unknown", venue=venue_name)
                outcome.notes.append(
                    f"{venue_name}: the request may have been received. NOT "
                    "failing over — a second venue would risk a duplicate "
                    "position. Reconcile this client id first.")
                self._emit("order.unresolved", outcome.as_dict())
                return outcome
            outcome.notes.append(f"{venue_name}: {outcome.error} — failing over")

        record.mark(OrderStatus.REJECTED, error=outcome.error or "no venue accepted")
        self.store.complete(cid, status="rejected")
        self._emit("order.rejected", outcome.as_dict())
        return outcome

    # ──────────────────────────────────────────────────────── amend / replace
    def amend(self, client_id: str, *, qty: Optional[float] = None,
              limit_price: Optional[float] = None) -> SubmitOutcome:
        """Change a resting order, by amendment where possible.

        Falls back to cancel/replace on a venue that cannot amend, and says
        which happened. The fallback is sized to the REMAINDER, so amending a
        half-filled order does not resubmit the whole quantity.
        """
        outcome = SubmitOutcome(client_id=client_id)
        record = self._records.get(client_id)
        if record is None:
            outcome.error = f"unknown order {client_id!r}"
            return outcome
        if record.status.terminal:
            outcome.error = (f"order is {record.status.value} — a terminal order "
                             "cannot be amended")
            return outcome

        profile = self.router.profile(record.venue)
        venue = self._venues.get(record.venue)
        if venue is None or profile is None:
            outcome.error = f"venue {record.venue!r} is not registered"
            return outcome

        if profile.capabilities.amend and record.broker_order_id:
            started = time.perf_counter()
            try:
                report = venue.amend(record.broker_order_id, qty=qty,
                                     limit_price=limit_price)
            except Exception as exc:  # noqa: BLE001
                record.record_amendment(Amendment(
                    at=datetime.now(timezone.utc), qty=qty, limit_price=limit_price,
                    applied=False, reason=f"{type(exc).__name__}: {exc}"))
                outcome.error = f"{type(exc).__name__}: {exc}"
                return outcome
            self.metrics.record(f"{record.venue}.amend",
                                (time.perf_counter() - started) * 1000)
            record.record_amendment(Amendment(
                at=datetime.now(timezone.utc), qty=qty, limit_price=limit_price,
                applied=bool(report and report.ok),
                reason="" if report and report.ok else (report.message if report else "")))
            self._apply_report(record, report)
            outcome.report, outcome.record = report, record
            return outcome

        return self.cancel_replace(client_id, qty=qty, limit_price=limit_price,
                                   reason="venue does not support amendment")

    def cancel_replace(self, client_id: str, *, qty: Optional[float] = None,
                       limit_price: Optional[float] = None,
                       reason: str = "") -> SubmitOutcome:
        """Cancel a resting order and submit its remainder at new terms.

        The cancel must succeed before the replacement is sent. Submitting first
        would briefly double the exposure, and if the cancel then fails, both
        orders are live — the exact outcome cancel/replace exists to avoid.
        """
        outcome = SubmitOutcome(client_id=client_id)
        record = self._records.get(client_id)
        if record is None:
            outcome.error = f"unknown order {client_id!r}"
            return outcome

        cancelled = self.cancel(client_id)
        if not cancelled.ok and record.status not in (OrderStatus.CANCELLED,
                                                      OrderStatus.PARTIALLY_FILLED):
            outcome.error = (f"cancel failed ({cancelled.error}) — the replacement "
                             "was NOT sent, because two live orders is worse than "
                             "none")
            return outcome

        remainder = record.replacement_order(limit_price=limit_price, qty=qty)
        if remainder.qty <= 0:
            outcome.notes.append("nothing left to replace — the order was fully "
                                 "filled before the cancel landed")
            outcome.record = record
            return outcome

        record.record_amendment(Amendment(
            at=datetime.now(timezone.utc), qty=remainder.qty,
            limit_price=limit_price, applied=True, via_replace=True, reason=reason))
        # A new intent, deliberately: different quantity or price means a
        # different order, and reusing the original client id would make the
        # idempotency store reject the replacement as a duplicate of the thing
        # it replaces.
        replacement = self.submit(remainder, signal_id=f"replace:{client_id}")
        if replacement.record is not None:
            replacement.record.replaces = client_id
            record.replaced_by = replacement.client_id
        replacement.notes.append(f"replaces {client_id} ({reason or 'requested'})")
        return replacement

    def cancel(self, client_id: str) -> SubmitOutcome:
        outcome = SubmitOutcome(client_id=client_id)
        record = self._records.get(client_id)
        if record is None:
            outcome.error = f"unknown order {client_id!r}"
            return outcome
        venue = self._venues.get(record.venue)
        if venue is None or not record.broker_order_id:
            outcome.error = "order was never acknowledged by a venue"
            return outcome
        started = time.perf_counter()
        try:
            report = venue.cancel(record.broker_order_id)
        except Exception as exc:  # noqa: BLE001
            outcome.error = f"{type(exc).__name__}: {exc}"
            return outcome
        self.metrics.record(f"{record.venue}.cancel",
                            (time.perf_counter() - started) * 1000)
        self._apply_report(record, report)
        if report.ok or report.status is ExecutionStatus.CANCELLED:
            record.mark(OrderStatus.CANCELLED)
        outcome.report, outcome.record = report, record
        return outcome

    # ───────────────────────────────────────────────────────────────── fills
    def apply_fill(self, client_id: str, fill: FillEvent) -> bool:
        """Record an incremental fill. Returns False for a duplicate.

        Public because fills arrive from the stream, not from the submit call
        that created the order — and the same fill arrives twice often enough
        that the deduplication is the feature.
        """
        record = self._records.get(client_id)
        if record is None:
            return False
        applied = record.apply_fill(fill)
        if applied:
            self._emit("order.fill", {"client_id": client_id, "qty": fill.qty,
                                      "price": fill.price,
                                      "filled": record.filled_qty,
                                      "remaining": record.remaining_qty})
        return applied

    # ─────────────────────────────────────────────────────── reconciliation
    def local_positions(self) -> dict[str, float]:
        """Net signed quantity per symbol, from this engine's own fills."""
        out: dict[str, float] = {}
        for record in self._records.values():
            if record.filled_qty <= 0:
                continue
            out[record.order.symbol] = out.get(record.order.symbol, 0.0) + signed_qty(record)
        return {k: v for k, v in out.items() if abs(v) > 1e-12}

    def reconcile_venue(self, name: str, *,
                        venue_orders: Optional[Mapping[str, Any]] = None
                        ) -> ReconciliationReport:
        """Compare this engine's book against one venue's."""
        venue = self._venues.get(name)
        if venue is None:
            return ReconciliationReport(venue=name,
                                        notes=("venue is not registered",))
        try:
            positions: Sequence[Position] = venue.fetch_positions()
        except Exception as exc:  # noqa: BLE001
            return ReconciliationReport(
                venue=name,
                notes=(f"could not fetch positions: {type(exc).__name__}: {exc} — "
                       "nothing was compared, which is NOT the same as being in "
                       "sync",))
        records = [r for r in self._records.values() if r.venue == name]
        return reconcile(venue=name, local_positions=self.local_positions(),
                         venue_positions=positions, records=records,
                         venue_orders=venue_orders)

    def reconcile_all(self) -> dict[str, ReconciliationReport]:
        return {name: self.reconcile_venue(name) for name in self._venues}

    # ──────────────────────────────────────────────────────────────── status
    def order(self, client_id: str) -> Optional[OrderRecord]:
        return self._records.get(client_id)

    def open_orders(self) -> tuple[OrderRecord, ...]:
        return tuple(r for r in self._records.values() if not r.status.terminal)

    def health(self) -> dict[str, Any]:
        """Everything an operator needs in one call."""
        return {
            "venues": {name: (self.router.profile(name).health.as_dict()
                              if self.router.profile(name) else {})
                       for name in self._venues},
            "circuits": {name: p.breaker.as_dict()
                         for name, p in ((n, self.router.profile(n))
                                         for n in self._venues)
                         if p and p.breaker},
            "streams": self.streams.as_dict(),
            "latency": self.metrics.summary(),
            "orders": {"open": len(self.open_orders()), "total": len(self._records)},
            "in_flight_intents": len(self.store.in_flight()),
        }

    # ─────────────────────────────────────────────────────────────── private
    def _attempt(self, venue: Venue, order: Order, client_id: str,
                 profile: VenueProfile):
        """One venue, under retry. Records latency and health either way."""
        name = profile.name

        def call() -> ExecutionReport:
            started = time.perf_counter()
            try:
                report = venue.submit(order, client_id=client_id)
            except BaseException:
                elapsed = (time.perf_counter() - started) * 1000
                self.metrics.record(f"{name}.submit", elapsed)
                raise
            elapsed = (time.perf_counter() - started) * 1000
            self.metrics.record(f"{name}.submit", elapsed)
            profile.health.record_success(elapsed)
            if profile.breaker:
                profile.breaker.record_success()
            return report

        def on_attempt(attempt: Attempt) -> None:
            if attempt.ok:
                return
            profile.health.record_failure(attempt.error)
            if profile.breaker:
                profile.breaker.record_failure(attempt.error)
            if profile.health.consecutive_failures >= 3:
                profile.health.state = VenueState.DEGRADED

        return run_with_retry(call, self.retry, sleep=self._sleep,
                              on_attempt=on_attempt)

    @staticmethod
    def _apply_report(record: OrderRecord, report: Optional[ExecutionReport]) -> None:
        if report is None:
            return
        if report.broker_order_id:
            record.broker_order_id = report.broker_order_id
        mapping = {
            ExecutionStatus.ACCEPTED: OrderStatus.OPEN,
            ExecutionStatus.FILLED: OrderStatus.FILLED,
            ExecutionStatus.PARTIAL: OrderStatus.PARTIALLY_FILLED,
            ExecutionStatus.CANCELLED: OrderStatus.CANCELLED,
            ExecutionStatus.REJECTED: OrderStatus.REJECTED,
            ExecutionStatus.ERROR: OrderStatus.UNKNOWN,
        }
        # A report carrying a fill quantity is recorded as a fill, not just a
        # status: an ACCEPTED report that already includes 0.4 filled would
        # otherwise leave the engine believing nothing had executed.
        if report.filled_qty and report.avg_fill_price:
            already = record.filled_qty
            delta = float(report.filled_qty) - already
            if delta > 1e-12:
                record.apply_fill(FillEvent(
                    fill_id=f"{record.client_id}:report:{report.filled_qty:.10g}",
                    qty=delta, price=float(report.avg_fill_price),
                    fee=float(report.fees or 0.0)))
        status = mapping.get(report.status)
        if status and not (status is OrderStatus.OPEN and record.filled_qty > 0):
            record.mark(status, error=report.message if not report.ok else "")

    def _emit(self, name: str, payload: dict) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(name, payload)
        except Exception:  # noqa: BLE001 — a listener must never break execution
            pass


__all__ = ["ExecutionEngine", "SubmitOutcome"]
