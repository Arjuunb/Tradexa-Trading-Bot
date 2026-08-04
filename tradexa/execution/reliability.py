"""Retry, circuit breaking and latency measurement.

Three mechanisms that all answer "what do we do when a venue misbehaves", kept
together because they have to agree: a retry policy that keeps hammering a venue
the breaker has opened is not a policy, it is a denial-of-service against your
own account.

The dangerous idea in all of this is that **retrying is free**. In execution it
is not — every retry is a chance to place the same order twice. So the policy
here is deliberately conservative in one specific way: **a timeout is not
retryable by default.** A request that timed out may have reached the venue, and
the only safe response is to reconcile — ask the venue what happened — rather
than to send it again. Retrying timeouts is the single most common way a
well-intentioned execution layer opens double positions.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Optional, Sequence, TypeVar

from tradexa.core.exceptions import TradexaError

T = TypeVar("T")


# ═══════════════════════════════════════════════════ retry

class RetryDecision(str, Enum):
    RETRY = "retry"
    #: Do not retry, but the order's fate is UNKNOWN — reconcile before acting.
    RECONCILE = "reconcile"
    FAIL = "fail"


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with jitter, and a classification of what to retry.

    Jitter is not decoration. Without it, every client that failed during the
    same venue blip retries at the same instant, and the recovering venue is hit
    by a synchronised wave — the thundering herd that turns a ten-second
    degradation into a minute-long one.
    """

    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 8.0
    multiplier: float = 2.0
    #: Fraction of the delay randomised. 0 disables jitter (tests only).
    jitter: float = 0.25
    #: Retry a timeout? Off by default — see the module docstring.
    retry_timeouts: bool = False

    def delay_for(self, attempt: int) -> float:
        """Seconds to wait before ``attempt`` (1-based). Deterministic when
        ``jitter`` is 0, which is what lets a test assert the schedule."""
        raw = min(self.max_delay, self.base_delay * (self.multiplier ** max(0, attempt - 1)))
        if self.jitter <= 0:
            return raw
        spread = raw * self.jitter
        return max(0.0, raw + random.uniform(-spread, spread))

    def classify(self, exc: BaseException) -> RetryDecision:
        """What to do about a failure.

        Uses the ``retryable`` flag the platform's exceptions already carry, so
        retry policy is a property of the error type rather than a guess made by
        matching strings in a message — which is how a "connection reset" and a
        "position would exceed limit" end up treated the same.
        """
        if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
            return RetryDecision.RETRY if self.retry_timeouts else RetryDecision.RECONCILE
        if isinstance(exc, TradexaError):
            return RetryDecision.RETRY if exc.retryable else RetryDecision.FAIL
        if isinstance(exc, (ConnectionError, OSError)):
            # A connection that never opened cannot have delivered an order.
            # This is the one network failure that is safely retryable.
            return RetryDecision.RETRY
        return RetryDecision.FAIL


@dataclass
class Attempt:
    """One try, and what came of it. The audit trail behind a retried order."""

    number: int
    started_at: datetime
    latency_ms: float
    ok: bool
    error: str = ""
    decision: Optional[RetryDecision] = None


def run_with_retry(call: Callable[[], T], policy: RetryPolicy, *,
                   sleep: Callable[[float], None] = time.sleep,
                   on_attempt: Optional[Callable[[Attempt], None]] = None
                   ) -> tuple[Optional[T], list[Attempt], Optional[BaseException]]:
    """Run ``call`` under ``policy``. Returns ``(result, attempts, error)``.

    Never raises on the operation's behalf — the attempts and the final error
    are returned so the caller can decide. An execution engine that lets a retry
    helper raise loses the record of what was tried, which is the record needed
    to work out whether an order might be live at the venue.
    """
    attempts: list[Attempt] = []
    last_error: Optional[BaseException] = None
    for number in range(1, policy.max_attempts + 1):
        started = datetime.now(timezone.utc)
        clock = time.perf_counter()
        try:
            result = call()
        except BaseException as exc:  # noqa: BLE001 — classified, then re-decided
            decision = policy.classify(exc)
            record = Attempt(number, started, (time.perf_counter() - clock) * 1000,
                             False, f"{type(exc).__name__}: {exc}", decision)
            attempts.append(record)
            if on_attempt:
                on_attempt(record)
            last_error = exc
            if decision is not RetryDecision.RETRY or number >= policy.max_attempts:
                return None, attempts, exc
            sleep(policy.delay_for(number))
            continue
        record = Attempt(number, started, (time.perf_counter() - clock) * 1000, True)
        attempts.append(record)
        if on_attempt:
            on_attempt(record)
        return result, attempts, None
    return None, attempts, last_error


# ═══════════════════════════════════════════════════ circuit breaker

class CircuitState(str, Enum):
    CLOSED = "closed"        # normal
    OPEN = "open"            # refusing, venue is presumed broken
    HALF_OPEN = "half_open"  # one probe allowed


class CircuitOpen(Exception):
    """Raised when a call is refused because the breaker is open."""

    def __init__(self, name: str, until: datetime) -> None:
        self.name, self.until = name, until
        super().__init__(f"circuit '{name}' is open until {until.isoformat()}")


@dataclass
class CircuitBreaker:
    """Stops calling a venue that is failing, and tests it before trusting it.

    The half-open state is what makes this a breaker rather than a timer: after
    the cooldown, exactly ONE request is allowed through. If it succeeds the
    circuit closes; if it fails the cooldown restarts. Letting the full flow
    resume on a timer means an outage that has not ended is met with the entire
    backlog at once.

    Successes are also counted in half-open: one success after a sustained
    outage is noise as often as it is recovery, so ``success_threshold`` probes
    must land before normal flow resumes.
    """

    name: str
    failure_threshold: int = 5
    #: Consecutive successes required in HALF_OPEN before closing.
    success_threshold: int = 2
    cooldown: timedelta = timedelta(seconds=30)
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    successes: int = 0
    opened_at: Optional[datetime] = None
    trips: int = 0
    last_error: str = ""

    def __post_init__(self) -> None:
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- state
    def allows(self, now: Optional[datetime] = None) -> bool:
        """Whether a call may proceed. Also performs the OPEN → HALF_OPEN move."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self.state is CircuitState.CLOSED:
                return True
            if self.state is CircuitState.OPEN:
                if self.opened_at and now - self.opened_at >= self.cooldown:
                    self.state = CircuitState.HALF_OPEN
                    self.successes = 0
                    return True          # the single probe
                return False
            # HALF_OPEN: probes are allowed, and each result moves the state.
            return True

    def record_success(self) -> None:
        with self._lock:
            if self.state is CircuitState.HALF_OPEN:
                self.successes += 1
                if self.successes >= self.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.failures = 0
                return
            self.failures = 0

    def record_failure(self, error: str = "", now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self.last_error = error
            if self.state is CircuitState.HALF_OPEN:
                # A failed probe means the outage is ongoing. Full cooldown
                # again, not a shortened one — a venue that just failed its test
                # has earned no credit for having been tried.
                self._open(now)
                return
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self._open(now)

    def reset(self) -> None:
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failures = self.successes = 0
            self.opened_at = None

    def _open(self, now: datetime) -> None:
        self.state = CircuitState.OPEN
        self.opened_at = now
        self.successes = 0
        self.trips += 1

    @property
    def open_until(self) -> Optional[datetime]:
        return self.opened_at + self.cooldown if self.opened_at else None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state.value,
                "failures": self.failures, "trips": self.trips,
                "opened_at": self.opened_at.isoformat() if self.opened_at else None,
                "open_until": self.open_until.isoformat() if self.open_until else None,
                "last_error": self.last_error}


# ═══════════════════════════════════════════════════ latency

@dataclass
class LatencyMetrics:
    """Per-operation latency, as percentiles.

    Percentiles, not averages. An average latency of 40ms across a venue that
    answers in 5ms and occasionally in 4 seconds describes neither case; p99 is
    where the orders that miss their price live, and it is the number worth
    alerting on.
    """

    max_samples: int = 1000
    _by_op: dict[str, list[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._lock = threading.RLock()

    def record(self, operation: str, milliseconds: float) -> None:
        with self._lock:
            bucket = self._by_op.setdefault(operation, [])
            bucket.append(float(milliseconds))
            if len(bucket) > self.max_samples:
                del bucket[:-self.max_samples]

    def percentile(self, operation: str, p: float) -> Optional[float]:
        with self._lock:
            samples = sorted(self._by_op.get(operation, ()))
        if not samples:
            return None
        index = min(len(samples) - 1, int(round((p / 100.0) * (len(samples) - 1))))
        return samples[index]

    def summary(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            operations = list(self._by_op)
        return {
            op: {"count": len(self._by_op[op]),
                 "p50": self.percentile(op, 50), "p95": self.percentile(op, 95),
                 "p99": self.percentile(op, 99),
                 "max": max(self._by_op[op]) if self._by_op[op] else None}
            for op in operations}

    def slowest(self) -> Optional[str]:
        summary = self.summary()
        if not summary:
            return None
        return max(summary, key=lambda op: summary[op]["p99"] or 0.0)


__all__ = ["RetryDecision", "RetryPolicy", "Attempt", "run_with_retry",
           "CircuitState", "CircuitOpen", "CircuitBreaker", "LatencyMetrics"]
