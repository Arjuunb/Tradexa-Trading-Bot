"""Keeping a streaming connection alive, and knowing when it is not.

Websocket supervision, expressed as logic over an injected transport rather
than as a websocket client. The supervisor decides *when* to reconnect, *how
long* to wait, *which endpoint* to try next and *whether* the stream is
trustworthy right now; opening the socket is the transport's job.

That split is what makes any of this testable. A supervisor that owns its own
socket can only be exercised against a real server, so the cases that matter —
a heartbeat that stops arriving, an endpoint that accepts the connection and
then goes silent, a reconnect storm — get tested by hoping.

**The failure this exists to catch is the silent one.** A websocket that drops
loudly is easy: the read fails and you reconnect. The dangerous case is the
connection that stays *open* while the venue stops sending — TCP holds, the
client believes it is subscribed, and fills arrive nowhere. Only a heartbeat
deadline catches that, which is why staleness is judged on time since the last
message rather than on socket state.
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Optional, Sequence


class LinkState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    #: Connected, but nothing has arrived within the heartbeat deadline. The
    #: state that exists because an open-but-silent socket is the one that
    #: quietly loses fills.
    STALE = "stale"
    #: Given up on every endpoint. Loud on purpose.
    FAILED = "failed"


@dataclass(frozen=True)
class Endpoint:
    """One place a stream can be opened, and how much we prefer it."""

    url: str
    name: str = ""
    #: Lower is preferred. Equal priorities are tried in declaration order.
    priority: int = 0
    region: str = ""

    def label(self) -> str:
        return self.name or self.url


@dataclass
class ReconnectPolicy:
    """Backoff for reconnection attempts.

    Capped and jittered for the same reason retry is: every client that dropped
    during one venue restart otherwise reconnects in lockstep, and the venue
    comes back up into a synchronised stampede.
    """

    base_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.3
    #: Attempts per endpoint before moving to the next one. 0 = unlimited, which
    #: is correct for a primary you always want to return to and wrong for a
    #: failover chain you want to walk.
    attempts_per_endpoint: int = 3
    #: Give up entirely after this many total attempts. 0 = never give up.
    max_total_attempts: int = 0

    def delay_for(self, attempt: int) -> float:
        raw = min(self.max_delay, self.base_delay * (self.multiplier ** max(0, attempt - 1)))
        if self.jitter <= 0:
            return raw
        spread = raw * self.jitter
        return max(0.0, raw + random.uniform(-spread, spread))


@dataclass
class LinkStats:
    connects: int = 0
    disconnects: int = 0
    failovers: int = 0
    stale_events: int = 0
    messages: int = 0
    heartbeats: int = 0
    total_downtime_s: float = 0.0


class ConnectionSupervisor:
    """Watches one venue's stream: heartbeat, staleness, reconnect, failover.

    Drives an injected ``connect(endpoint) -> Any`` callable. Everything else —
    when to call it, which endpoint to pass, how long to wait first, when to
    declare the link stale — lives here and is pure enough to test with a fake
    clock.
    """

    def __init__(self, name: str, endpoints: Sequence[Endpoint], *,
                 connect: Optional[Callable[[Endpoint], Any]] = None,
                 heartbeat_interval: timedelta = timedelta(seconds=15),
                 heartbeat_grace: float = 2.5,
                 policy: Optional[ReconnectPolicy] = None,
                 on_state: Optional[Callable[[str, LinkState], None]] = None) -> None:
        if not endpoints:
            raise ValueError("a supervisor needs at least one endpoint")
        self.name = name
        # Sorted by priority, stably — so a failover chain is declaration order
        # within a priority band, and a caller can express "these two are
        # equivalent, that one is the last resort".
        self.endpoints = tuple(sorted(endpoints, key=lambda e: e.priority))
        self._connect = connect
        self.heartbeat_interval = heartbeat_interval
        #: A missed beat is not a dead link. The deadline is a multiple of the
        #: interval, so one late message on a busy venue does not trigger a
        #: reconnect that costs more than the delay it was reacting to.
        self.heartbeat_grace = heartbeat_grace
        self.policy = policy or ReconnectPolicy()
        self._on_state = on_state

        self.state = LinkState.DISCONNECTED
        self.stats = LinkStats()
        self.endpoint: Optional[Endpoint] = self.endpoints[0]
        self.attempts_on_endpoint = 0
        self.total_attempts = 0
        self.last_message_at: Optional[datetime] = None
        self.connected_at: Optional[datetime] = None
        self.disconnected_at: Optional[datetime] = None
        self.last_error = ""
        self.connection: Any = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ state
    def _set(self, state: LinkState) -> None:
        if state is self.state:
            return
        self.state = state
        if self._on_state:
            try:
                self._on_state(self.name, state)
            except Exception:  # noqa: BLE001 — a listener must not break the link
                pass

    @property
    def heartbeat_deadline(self) -> timedelta:
        return self.heartbeat_interval * self.heartbeat_grace

    @property
    def healthy(self) -> bool:
        return self.state is LinkState.CONNECTED

    # ------------------------------------------------------------- lifecycle
    def connect(self, now: Optional[datetime] = None) -> bool:
        """Attempt the current endpoint. Returns whether it succeeded."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self._connect is None:
                self.last_error = "no transport supplied"
                self._set(LinkState.FAILED)
                return False
            self._set(LinkState.CONNECTING)
            self.attempts_on_endpoint += 1
            self.total_attempts += 1
            endpoint = self.endpoint or self.endpoints[0]
            try:
                self.connection = self._connect(endpoint)
            except Exception as exc:  # noqa: BLE001 — a failed dial is data
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.connection = None
                self._after_failed_attempt(now)
                return False
            self.stats.connects += 1
            self.connected_at = now
            # Seeded so a link that connects and then says nothing still goes
            # stale on schedule. Without this, `last_message_at` stays None and
            # a silent socket is never judged.
            self.last_message_at = now
            self.attempts_on_endpoint = 0
            if self.disconnected_at:
                self.stats.total_downtime_s += (now - self.disconnected_at).total_seconds()
                self.disconnected_at = None
            self._set(LinkState.CONNECTED)
            return True

    def disconnect(self, reason: str = "", now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self.state in (LinkState.CONNECTED, LinkState.STALE):
                self.stats.disconnects += 1
                self.disconnected_at = now
            self.connection = None
            self.last_error = reason or self.last_error
            self._set(LinkState.DISCONNECTED)

    def record_message(self, now: Optional[datetime] = None, *,
                       heartbeat: bool = False) -> None:
        """Any inbound traffic proves the link is alive.

        Heartbeats and data both count, because the question staleness answers
        is "is anything arriving?" — a venue streaming trades but not pings is
        not stale, and reconnecting it would drop a working subscription.
        """
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self.last_message_at = now
            self.stats.messages += 1
            if heartbeat:
                self.stats.heartbeats += 1
            if self.state is LinkState.STALE:
                self._set(LinkState.CONNECTED)

    def check(self, now: Optional[datetime] = None) -> LinkState:
        """Judge the link against the heartbeat deadline. Call periodically."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self.state not in (LinkState.CONNECTED, LinkState.STALE):
                return self.state
            if self.last_message_at is None:
                return self.state
            if now - self.last_message_at > self.heartbeat_deadline:
                if self.state is not LinkState.STALE:
                    self.stats.stale_events += 1
                    self._set(LinkState.STALE)
            return self.state

    def next_delay(self) -> float:
        return self.policy.delay_for(max(1, self.attempts_on_endpoint))

    def failover(self, now: Optional[datetime] = None) -> Optional[Endpoint]:
        """Move to the next endpoint. ``None`` when the chain is exhausted."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            current = self.endpoint
            index = self.endpoints.index(current) if current in self.endpoints else -1
            if index + 1 >= len(self.endpoints):
                # Wrap rather than stop: a primary that was down five minutes
                # ago is the endpoint you most want to be back on, and a chain
                # that only ever walks forwards ends up parked on the worst one.
                self.endpoint = self.endpoints[0]
            else:
                self.endpoint = self.endpoints[index + 1]
            self.attempts_on_endpoint = 0
            self.stats.failovers += 1
            return self.endpoint

    def should_failover(self) -> bool:
        limit = self.policy.attempts_per_endpoint
        return bool(limit) and self.attempts_on_endpoint >= limit

    def exhausted(self) -> bool:
        limit = self.policy.max_total_attempts
        return bool(limit) and self.total_attempts >= limit

    def _after_failed_attempt(self, now: datetime) -> None:
        if self.disconnected_at is None:
            self.disconnected_at = now
        if self.exhausted():
            self._set(LinkState.FAILED)
            return
        if self.should_failover() and len(self.endpoints) > 1:
            self.failover(now)
        self._set(LinkState.DISCONNECTED)

    # ------------------------------------------------------------------- view
    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "state": self.state.value,
            "endpoint": self.endpoint.label() if self.endpoint else None,
            "endpoints": [e.label() for e in self.endpoints],
            "healthy": self.healthy,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_message_at": (self.last_message_at.isoformat()
                                if self.last_message_at else None),
            "heartbeat_deadline_s": self.heartbeat_deadline.total_seconds(),
            "attempts_on_endpoint": self.attempts_on_endpoint,
            "total_attempts": self.total_attempts,
            "last_error": self.last_error,
            "stats": {"connects": self.stats.connects,
                      "disconnects": self.stats.disconnects,
                      "failovers": self.stats.failovers,
                      "stale_events": self.stats.stale_events,
                      "messages": self.stats.messages,
                      "heartbeats": self.stats.heartbeats,
                      "downtime_s": round(self.stats.total_downtime_s, 3)},
        }


class StreamMonitor:
    """Every venue's stream, in one place.

    The thing an operator actually asks: which links are up, which are stale,
    and how long has anything been down. Aggregating here rather than in the
    execution engine keeps stream health separate from order flow — they fail
    independently, and a page that conflates them cannot say which broke.
    """

    def __init__(self) -> None:
        self._links: dict[str, ConnectionSupervisor] = {}

    def add(self, supervisor: ConnectionSupervisor) -> ConnectionSupervisor:
        self._links[supervisor.name] = supervisor
        return supervisor

    def get(self, name: str) -> Optional[ConnectionSupervisor]:
        return self._links.get(name)

    def check_all(self, now: Optional[datetime] = None) -> dict[str, LinkState]:
        return {name: link.check(now) for name, link in self._links.items()}

    @property
    def healthy(self) -> tuple[str, ...]:
        return tuple(n for n, l in self._links.items() if l.healthy)

    @property
    def unhealthy(self) -> tuple[str, ...]:
        return tuple(n for n, l in self._links.items() if not l.healthy)

    def as_dict(self) -> dict[str, Any]:
        return {"links": {n: l.as_dict() for n, l in self._links.items()},
                "healthy": list(self.healthy), "unhealthy": list(self.unhealthy),
                "all_healthy": not self.unhealthy}


__all__ = ["LinkState", "Endpoint", "ReconnectPolicy", "LinkStats",
           "ConnectionSupervisor", "StreamMonitor"]
