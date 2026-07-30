"""Comparing what we think we hold against what the exchange says.

Position reconciliation is the safety net under everything else in this
package. Retry, failover and reconnection all create windows where local state
and venue state can diverge — an order that landed after a timeout, a fill that
arrived while the socket was down. Reconciliation is what finds that, and it is
the only mechanism here that can.

**It reports; it does not repair.** Every function returns a diff and a
suggested action, and applying anything requires an explicit call. That is not
timidity: an automatic reconciler that "fixes" a discrepancy by trading is one
bad exchange response away from liquidating a real position, and the failure
mode of a wrong repair is unbounded while the failure mode of a wrong report is
someone reading it.

**The exchange is authoritative about fills, and local state is authoritative
about intent.** Those are different questions. The venue knows what was
executed; only we know what we meant to execute. A reconciler that treats the
exchange as authoritative about everything will happily adopt a position nobody
asked for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from bot.types import Position
from tradexa.execution.orders import OrderRecord, OrderStatus

#: Quantities closer than this are the same quantity. Exchanges round to a
#: symbol's lot size and floats do not survive addition unscathed; without a
#: tolerance every reconciliation reports drift that is not there.
QTY_TOLERANCE = 1e-8


class Discrepancy(str, Enum):
    #: We hold it, the venue does not.
    MISSING_AT_VENUE = "missing_at_venue"
    #: The venue holds it, we do not. The dangerous one — an unmanaged position.
    UNKNOWN_LOCALLY = "unknown_locally"
    QUANTITY_MISMATCH = "quantity_mismatch"
    SIDE_MISMATCH = "side_mismatch"
    #: An order we believe is live that the venue has never heard of.
    ORPHAN_ORDER = "orphan_order"
    #: An order whose fate we never learned.
    UNRESOLVED = "unresolved"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Finding:
    """One disagreement, and what to do about it."""

    kind: Discrepancy
    symbol: str
    severity: Severity = Severity.WARNING
    local: Optional[float] = None
    venue: Optional[float] = None
    detail: str = ""
    #: What a human should do. Never executed automatically.
    suggested_action: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def delta(self) -> Optional[float]:
        if self.local is None or self.venue is None:
            return None
        return self.venue - self.local

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "symbol": self.symbol,
                "severity": self.severity.value, "local": self.local,
                "venue": self.venue, "delta": self.delta, "detail": self.detail,
                "suggested_action": self.suggested_action,
                "context": dict(self.context)}


@dataclass(frozen=True)
class ReconciliationReport:
    """The whole comparison, agreements included.

    Agreements are counted rather than listed: "checked 14 positions, 1
    disagreed" is the sentence an operator needs, and a report that only lists
    problems cannot say whether the check ran at all.
    """

    venue: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    findings: tuple[Finding, ...] = ()
    positions_checked: int = 0
    orders_checked: int = 0
    notes: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def critical(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.CRITICAL)

    def explain(self) -> str:
        if self.clean:
            return (f"{self.venue}: in sync — {self.positions_checked} position(s) "
                    f"and {self.orders_checked} order(s) agree")
        return (f"{self.venue}: {len(self.findings)} discrepancy(ies) across "
                f"{self.positions_checked} position(s) and {self.orders_checked} "
                f"order(s); {len(self.critical)} critical")

    def as_dict(self) -> dict[str, Any]:
        return {"venue": self.venue, "at": self.at.isoformat(),
                "clean": self.clean, "positions_checked": self.positions_checked,
                "orders_checked": self.orders_checked,
                "findings": [f.as_dict() for f in self.findings],
                "critical": len(self.critical), "notes": list(self.notes)}


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= QTY_TOLERANCE


def reconcile_positions(local: Mapping[str, float],
                        venue_positions: Sequence[Position], *,
                        venue: str = "") -> list[Finding]:
    """Compare signed local quantities against the venue's book.

    Signed, so a long of 1 and a short of 1 are not "the same size". A
    reconciler comparing absolute quantities calls a fully inverted position a
    match, which is the most expensive possible false negative.
    """
    findings: list[Finding] = []
    by_symbol = {p.symbol: float(p.qty) for p in venue_positions}

    for symbol, local_qty in local.items():
        remote = by_symbol.get(symbol)
        if remote is None:
            if _same(local_qty, 0.0):
                continue
            findings.append(Finding(
                Discrepancy.MISSING_AT_VENUE, symbol, Severity.CRITICAL,
                local=local_qty, venue=0.0,
                detail=f"we hold {local_qty:+g} but {venue or 'the venue'} reports none",
                suggested_action="check whether the position was closed outside "
                                 "the bot (manual trade, liquidation, or a fill "
                                 "we never received) before trading this symbol"))
            continue
        if not _same(local_qty, remote):
            same_side = (local_qty >= 0) == (remote >= 0)
            findings.append(Finding(
                Discrepancy.QUANTITY_MISMATCH if same_side else Discrepancy.SIDE_MISMATCH,
                symbol,
                Severity.WARNING if same_side else Severity.CRITICAL,
                local=local_qty, venue=remote,
                detail=(f"local {local_qty:+g} vs venue {remote:+g}"
                        + ("" if same_side else " — opposite sides")),
                suggested_action=("adopt the venue's quantity after confirming no "
                                  "fill is still in flight" if same_side else
                                  "do not trade this symbol until the direction "
                                  "is resolved manually")))

    for symbol, remote in by_symbol.items():
        if symbol in local or _same(remote, 0.0):
            continue
        findings.append(Finding(
            Discrepancy.UNKNOWN_LOCALLY, symbol, Severity.CRITICAL,
            local=0.0, venue=remote,
            detail=f"{venue or 'the venue'} holds {remote:+g} that this engine "
                   "did not open",
            suggested_action="an unmanaged position: it has no stop from this "
                             "engine. Close it manually or adopt it deliberately"))
    return findings


def reconcile_orders(records: Sequence[OrderRecord],
                     venue_orders: Mapping[str, Any], *,
                     venue: str = "") -> list[Finding]:
    """Compare orders we believe are live against the venue's open orders.

    ``venue_orders`` maps broker order id to whatever the venue returned; only
    its keys are used, because every venue shapes the value differently and the
    question here is existence, not detail.
    """
    findings: list[Finding] = []
    for record in records:
        if record.status.terminal:
            continue
        if record.status is OrderStatus.UNKNOWN:
            findings.append(Finding(
                Discrepancy.UNRESOLVED, record.order.symbol, Severity.CRITICAL,
                detail=f"order {record.client_id} was submitted and its outcome "
                       "was never learned",
                suggested_action="query the venue by client id before resubmitting "
                                 "— it may be live",
                context={"client_id": record.client_id}))
            continue
        if record.broker_order_id and record.broker_order_id not in venue_orders:
            findings.append(Finding(
                Discrepancy.ORPHAN_ORDER, record.order.symbol, Severity.WARNING,
                local=record.remaining_qty, venue=0.0,
                detail=f"we believe {record.broker_order_id} is open; "
                       f"{venue or 'the venue'} does not list it",
                suggested_action="it probably filled or was cancelled while the "
                                 "stream was down — fetch it by id and apply the "
                                 "result rather than assuming either",
                context={"client_id": record.client_id,
                         "broker_order_id": record.broker_order_id}))
    return findings


def reconcile(*, venue: str, local_positions: Mapping[str, float],
              venue_positions: Sequence[Position],
              records: Sequence[OrderRecord] = (),
              venue_orders: Optional[Mapping[str, Any]] = None
              ) -> ReconciliationReport:
    """One venue, positions and orders, in a single report."""
    notes: list[str] = []
    findings = reconcile_positions(local_positions, venue_positions, venue=venue)
    if venue_orders is None:
        notes.append("open orders were not compared — the venue's order list was "
                     "not supplied, so an orphaned order would not be seen here")
        order_count = 0
    else:
        findings += reconcile_orders(records, venue_orders, venue=venue)
        order_count = len(records)
    return ReconciliationReport(
        venue=venue, findings=tuple(findings),
        positions_checked=len(set(local_positions) | {p.symbol for p in venue_positions}),
        orders_checked=order_count, notes=tuple(notes))


__all__ = ["QTY_TOLERANCE", "Discrepancy", "Severity", "Finding",
           "ReconciliationReport", "reconcile", "reconcile_positions",
           "reconcile_orders"]
