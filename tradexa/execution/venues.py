"""What the execution engine needs from an exchange, and what it tracks about one.

The port is deliberately narrow. A ``Venue`` is asked to place, amend, cancel
and report — nothing about candles, websockets or authentication appears here,
because the engine's job is order lifecycle and those belong to the adapter.
A narrow port is also what makes a fake venue a two-line class, which is what
makes retry, failover and reconciliation testable at all.

``VenueHealth`` is separate from the venue itself on purpose: health is the
engine's *opinion*, formed from what it has observed, not something a venue
reports about itself. An exchange that is timing out is in no position to tell
you it is unhealthy.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from bot.types import Order, Position
from tradexa.core.models import ExecutionReport


class VenueState(str, Enum):
    """How usable a venue is right now.

    ``DEGRADED`` exists between UP and DOWN because most venue trouble is
    partial — elevated latency, intermittent 5xx — and collapsing that into
    "up" routes orders into a brownout while collapsing it into "down" drops
    capacity that still works.
    """

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    #: Configured but deliberately not accepting orders (live lock, maintenance).
    DISABLED = "disabled"


@runtime_checkable
class Venue(Protocol):
    """One exchange or broker, as the execution engine sees it.

    A Protocol rather than a base class, matching the rest of the platform: an
    existing broker conforms without importing anything from here.
    """

    name: str

    def submit(self, order: Order, *, client_id: str,
               **params: Any) -> ExecutionReport:
        """Place an order. ``client_id`` MUST be forwarded to the venue.

        ``**params`` carries venue-specific flags the domain ``Order`` has no
        field for — post-only, reduce-only, margin mode, the paper engine's
        maker flag. Passed through rather than modelled: every venue has a
        different set, and a union of all of them on the core Order type would
        make it the place every integration goes to add a field.

        Forwarding it is what makes a retry safe across a process boundary: a
        venue that honours client ids rejects the duplicate itself, which is the
        only guarantee an in-process store cannot provide.
        """

    def cancel(self, broker_order_id: str) -> ExecutionReport:
        ...

    def amend(self, broker_order_id: str, *, qty: Optional[float] = None,
              limit_price: Optional[float] = None) -> ExecutionReport:
        """Modify a resting order in place, where the venue supports it."""

    def fetch_order(self, broker_order_id: str) -> Optional[ExecutionReport]:
        """The venue's own view of one order. The input to reconciliation."""

    def fetch_positions(self) -> Sequence[Position]:
        """The venue's own view of the book. The other input to reconciliation."""


@dataclass
class VenueCapabilities:
    """What a venue can actually do.

    Declared rather than assumed, because the engine's fallbacks depend on it:
    a venue that cannot amend must be served by cancel/replace, and doing that
    silently on a venue that CAN amend would turn one call into two and give up
    queue position for nothing.
    """

    amend: bool = True
    #: Whether the venue rejects a duplicate client id itself.
    honours_client_ids: bool = True
    partial_fills: bool = True
    post_only: bool = False
    reduce_only: bool = False
    max_leverage: float = 1.0
    asset_classes: tuple[str, ...] = ()
    #: Taker fee in basis points — one input the router ranks on.
    taker_fee_bps: float = 0.0
    maker_fee_bps: float = 0.0


@dataclass
class VenueHealth:
    """The engine's running opinion of one venue.

    Deliberately observation-based: every field here is something the engine
    watched happen. Nothing is taken from a venue's own status endpoint, which
    is the last thing to notice an outage and, during one, is often the thing
    that is down.
    """

    name: str
    state: VenueState = VenueState.UP
    #: Rolling latency samples, milliseconds. Bounded — an unbounded list is a
    #: slow leak in a process that runs for weeks.
    samples: list[float] = field(default_factory=list)
    max_samples: int = 200
    consecutive_failures: int = 0
    total_requests: int = 0
    total_failures: int = 0
    last_ok: Optional[datetime] = None
    last_error: str = ""
    #: Set when a heartbeat is expected; staleness is judged against it.
    last_heartbeat: Optional[datetime] = None
    note: str = ""

    def __post_init__(self) -> None:
        self._lock = threading.RLock()

    # -------------------------------------------------------------- record
    def record_success(self, latency_ms: float) -> None:
        with self._lock:
            self.total_requests += 1
            self.consecutive_failures = 0
            self.last_ok = datetime.now(timezone.utc)
            self.samples.append(float(latency_ms))
            if len(self.samples) > self.max_samples:
                del self.samples[:-self.max_samples]
            if self.state is VenueState.DOWN:
                # Recovery is not automatic promotion to UP: one success after
                # an outage is a sign, not a guarantee. The circuit breaker owns
                # the promotion; this only stops it being DOWN on evidence.
                self.state = VenueState.DEGRADED

    def record_failure(self, error: str) -> None:
        with self._lock:
            self.total_requests += 1
            self.total_failures += 1
            self.consecutive_failures += 1
            self.last_error = error

    def beat(self, at: Optional[datetime] = None) -> None:
        with self._lock:
            self.last_heartbeat = at or datetime.now(timezone.utc)

    # ---------------------------------------------------------------- read
    @property
    def failure_rate(self) -> float:
        return self.total_failures / self.total_requests if self.total_requests else 0.0

    def latency(self, percentile: float = 50.0) -> Optional[float]:
        """Latency at a percentile, or ``None`` with no samples.

        ``None`` rather than 0.0: a venue nobody has called is not the fastest
        one available, and a router ranking on latency would otherwise send
        every order to whichever venue it has never used.
        """
        with self._lock:
            if not self.samples:
                return None
            ordered = sorted(self.samples)
            if percentile <= 0:
                return ordered[0]
            index = min(len(ordered) - 1,
                        int(round((percentile / 100.0) * (len(ordered) - 1))))
            return ordered[index]

    def is_stale(self, *, max_silence: timedelta,
                 now: Optional[datetime] = None) -> bool:
        """Whether the heartbeat has gone quiet.

        A venue that has never beaten is NOT stale — it may simply have no
        heartbeat configured. Treating "never heard from" as "gone silent" would
        mark every REST-only venue dead at startup.
        """
        if self.last_heartbeat is None:
            return False
        return (now or datetime.now(timezone.utc)) - self.last_heartbeat > max_silence

    @property
    def usable(self) -> bool:
        return self.state in (VenueState.UP, VenueState.DEGRADED)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state.value,
                "p50_ms": self.latency(50), "p95_ms": self.latency(95),
                "p99_ms": self.latency(99), "samples": len(self.samples),
                "requests": self.total_requests, "failures": self.total_failures,
                "failure_rate": round(self.failure_rate, 4),
                "consecutive_failures": self.consecutive_failures,
                "last_ok": self.last_ok.isoformat() if self.last_ok else None,
                "last_heartbeat": (self.last_heartbeat.isoformat()
                                   if self.last_heartbeat else None),
                "last_error": self.last_error, "note": self.note}


__all__ = ["Venue", "VenueState", "VenueCapabilities", "VenueHealth"]
