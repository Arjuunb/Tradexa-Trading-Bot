"""Making a submit safe to repeat.

The single most expensive failure in execution is not a rejected order — it is
a duplicated one. Every mechanism in this package that improves reliability
(retry, failover, reconnect, replay) works by *doing something again*, and each
one is a way to open a position twice unless the venue can tell that the second
attempt is the same intent as the first.

The whole scheme rests on one thing: **the client order id is derived from the
intent, not generated per attempt.** Two submits of the same trade produce the
same id, so a retry after a timeout is recognised — by the local store and by
any venue that honours client ids — as the attempt it is rather than a new
order. A random id per attempt makes every retry a fresh order and turns a
network blip into a double position.

The intent hash deliberately excludes anything that varies between attempts:
no timestamp, no attempt number, no venue. It includes what makes a trade a
different trade — symbol, side, quantity, type, prices and the originating
signal — so a genuinely new order at the same price is a new id, and a resend
of the same one is not.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from bot.types import Order

#: How long a completed submission stays remembered. Long enough to cover the
#: pathological retry (a request that times out client-side but lands minutes
#: later), short enough that a legitimate re-entry on the same signal the next
#: day is not mistaken for a duplicate.
DEFAULT_TTL = timedelta(hours=24)

#: Prefix so an id is recognisable in a venue's UI and a support ticket.
PREFIX = "tx"


def intent_key(order: Order, *, strategy: str = "", signal_id: str = "",
               extra: Optional[Mapping[str, Any]] = None) -> str:
    """A stable fingerprint of what this order IS.

    ``signal_id`` matters more than it looks: two identical orders from two
    different signals are genuinely two orders (scaling into a position), while
    two submits of one signal are one order retried. Without it, the second
    entry of a legitimate pyramid would be silently swallowed as a duplicate —
    which is the failure mode of over-eager deduplication, and it is worse than
    the duplicate it prevents because nothing reports it.
    """
    parts = [
        order.symbol,
        str(getattr(order.side, "value", order.side)),
        f"{float(order.qty):.10g}",
        str(getattr(order.order_type, "value", order.order_type)),
        f"{float(order.limit_price):.10g}" if order.limit_price is not None else "-",
        f"{float(order.stop_loss):.10g}" if order.stop_loss is not None else "-",
        f"{float(order.take_profit):.10g}" if order.take_profit is not None else "-",
        strategy, signal_id,
    ]
    if extra:
        parts += [f"{k}={extra[k]}" for k in sorted(extra)]
    return "|".join(parts)


def client_order_id(order: Order, *, strategy: str = "", signal_id: str = "",
                    extra: Optional[Mapping[str, Any]] = None) -> str:
    """The id sent to the venue. Deterministic for a given intent.

    Truncated to 32 characters because exchanges impose length limits (Binance
    allows 36, Bybit 36, Alpaca 128) and an id rejected for length would push
    the caller into generating a random one — losing the property this exists
    for at exactly the moment it matters.
    """
    digest = hashlib.sha256(
        intent_key(order, strategy=strategy, signal_id=signal_id, extra=extra)
        .encode()).hexdigest()
    return f"{PREFIX}{digest[:30]}"


@dataclass
class Submission:
    """What is known about one submitted intent."""

    client_id: str
    intent: str
    venue: str = ""
    broker_order_id: Optional[str] = None
    status: str = "in_flight"
    attempts: int = 0
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    result: Any = None

    @property
    def settled(self) -> bool:
        return self.status in ("filled", "rejected", "cancelled")


class IdempotencyStore:
    """Remembers submitted intents so a repeat is recognised.

    In memory and process-local, which is the honest scope: it prevents the
    duplicate that a retry loop, a failover or a redelivered signal would cause
    inside one process. It does NOT survive a restart, and two processes
    submitting the same intent would each see a first attempt — which is why the
    client id is also sent to the venue, where a venue that honours client ids
    provides the cross-process guarantee this cannot.

    Stating that boundary is the point. A store that silently pretends to a
    guarantee it cannot make is how a restart during a retry storm becomes a
    double position.
    """

    def __init__(self, ttl: timedelta = DEFAULT_TTL) -> None:
        self.ttl = ttl
        self._by_id: dict[str, Submission] = {}
        # Submissions are read by the caller and written by the engine, which
        # may be a worker thread. A dict is not atomic across read-modify-write.
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- write
    def begin(self, client_id: str, intent: str, *, venue: str = ""
              ) -> tuple[Submission, bool]:
        """Claim an intent. Returns ``(submission, is_new)``.

        ``is_new`` false means this exact intent is already in flight or was
        recently completed, and the caller must NOT submit again — it should
        return the existing outcome. That single boolean is the duplicate
        guard; everything else here is bookkeeping.
        """
        with self._lock:
            self._evict()
            existing = self._by_id.get(client_id)
            if existing is not None:
                existing.attempts += 1
                existing.last_seen = datetime.now(timezone.utc)
                return existing, False
            record = Submission(client_id=client_id, intent=intent, venue=venue,
                                attempts=1)
            self._by_id[client_id] = record
            return record, True

    def complete(self, client_id: str, *, status: str, result: Any = None,
                 broker_order_id: Optional[str] = None,
                 venue: Optional[str] = None) -> Optional[Submission]:
        with self._lock:
            record = self._by_id.get(client_id)
            if record is None:
                return None
            record.status = status
            record.result = result
            record.last_seen = datetime.now(timezone.utc)
            if broker_order_id:
                record.broker_order_id = broker_order_id
            if venue:
                record.venue = venue
            return record

    def release(self, client_id: str) -> None:
        """Forget an intent so it may be submitted again.

        Used when an attempt failed in a way that provably did NOT reach the
        venue — a connection refused before any bytes were sent. A timeout is
        NOT such a case: the order may have landed, and releasing it would
        authorise the duplicate this class exists to prevent.
        """
        with self._lock:
            self._by_id.pop(client_id, None)

    # ----------------------------------------------------------------- read
    def get(self, client_id: str) -> Optional[Submission]:
        with self._lock:
            return self._by_id.get(client_id)

    def in_flight(self) -> tuple[Submission, ...]:
        with self._lock:
            return tuple(s for s in self._by_id.values() if s.status == "in_flight")

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_id)

    def __contains__(self, client_id: object) -> bool:
        with self._lock:
            return client_id in self._by_id

    # -------------------------------------------------------------- private
    def _evict(self) -> None:
        """Drop settled entries past the TTL.

        Only settled ones. An in-flight submission is never evicted regardless
        of age: an order whose fate is unknown is exactly the one whose id must
        not be reissued, and letting a stuck entry expire would hand the
        duplicate back on a timer.
        """
        cutoff = datetime.now(timezone.utc) - self.ttl
        for key in [k for k, v in self._by_id.items()
                    if v.settled and v.last_seen < cutoff]:
            self._by_id.pop(key, None)


__all__ = ["DEFAULT_TTL", "PREFIX", "intent_key", "client_order_id",
           "Submission", "IdempotencyStore"]
