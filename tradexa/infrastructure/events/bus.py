"""The event bus — registry, dispatcher, publisher, subscriber, metrics.

Synchronous by default, with opt-in async handlers. That default is deliberate:
an always-async bus introduces ordering, backpressure and delivery-guarantee
problems worse than the coupling it removes, and a synchronous bus is simply a
decoupled function call — the publisher does not know who listens, but still
knows the work is done when ``publish`` returns.

The invariant everything else is built around:

    **a subscriber's failure never reaches the publisher.**

If a Telegram notifier raises while handling ``OrderFilled``, the fill must
still be recorded. A bus that propagates handler failures is strictly worse
than a direct call, because it fails a publisher on behalf of code the
publisher never chose to depend on. Handler exceptions are caught, counted,
reported to an error sink, and republished as ``ErrorOccurred`` — isolated is
not the same as ignored.

Pieces, and why each exists separately:

    EventRegistry    name -> type. Replay needs it to rebuild an event from a
                     journal line; without it a journal is unreadable text.
    EventDispatcher  delivery: priority ordering, retries, metrics, isolation.
                     Separate from the bus so delivery policy can be tested
                     without a publisher, and swapped without touching either.
    EventBus         the seam callers hold. Registry + dispatcher + routing.
    EventPublisher   a bus handle bound to a source and correlation id, so a
                     module stamps them once instead of at every call.
    EventSubscriber  a base class that registers its own handlers, for
                     subscribers with state.
"""
from __future__ import annotations

import asyncio
import inspect
import threading
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from tradexa.core.events import ALL_EVENTS, ErrorOccurred, Event, new_id

Handler = Callable[[Any], Any]
ErrorSink = Callable[[BaseException, Any, Handler], None]

#: A publish chain deeper than this is treated as a cycle. Trading chains are
#: shallow — a fill leads to a position update leads to a portfolio update is
#: three. Twenty is far beyond anything legitimate and short of a stack
#: overflow, so a cycle reports itself instead of arriving as a RecursionError
#: thousands of frames from the handler that caused it.
MAX_PUBLISH_DEPTH = 20


class EventBusError(RuntimeError):
    """A bus-level fault (a publish cycle, a bad registration). Never a
    handler's own exception — those are isolated, not raised."""


# ── priorities ──────────────────────────────────────────────────────────────
class Priority:
    """Higher runs first.

    Ordering matters when handlers are not independent: an audit record must be
    written before a notification claims the trade happened, and a risk halt
    must be applied before anything else reacts to the event that tripped it.
    Named constants rather than bare ints so a registration reads as intent.
    """

    CRITICAL = 100      # risk halts, kill switches
    HIGH = 75           # persistence, audit, ledger
    NORMAL = 50         # default
    LOW = 25            # metrics, analytics
    BACKGROUND = 0      # notifications, nice-to-have


# ── registry ────────────────────────────────────────────────────────────────
class EventRegistry:
    """Name → event type.

    Replay reads a journal of names and payloads; without a registry those are
    strings with no way back to a class. Registration is explicit so a typo in
    a journal fails loudly rather than silently reconstructing nothing.
    """

    def __init__(self, events: Iterable[type] = ()) -> None:
        self._types: dict[str, type] = {}
        for evt in events:
            self.register(evt)

    def register(self, event_type: type) -> type:
        """Register a type. Idempotent for the same class; a second, DIFFERENT
        class under one name is an error — silently overwriting would make
        replay reconstruct the wrong type."""
        name = event_type.__name__
        existing = self._types.get(name)
        if existing is not None and existing is not event_type:
            raise EventBusError(
                f"two different classes registered as {name!r}: "
                f"{existing!r} and {event_type!r}")
        self._types[name] = event_type
        return event_type

    def resolve(self, name: str) -> Optional[type]:
        return self._types.get(name)

    def names(self) -> list[str]:
        return sorted(self._types)

    def __contains__(self, name: object) -> bool:
        return name in self._types

    def __len__(self) -> int:
        return len(self._types)


#: Every event in the vocabulary, pre-registered.
default_registry = EventRegistry(ALL_EVENTS)


# ── subscriptions ───────────────────────────────────────────────────────────
@dataclass
class Subscription:
    """One registered handler and the policy attached to it."""

    event_type: type
    handler: Handler
    priority: int = Priority.NORMAL
    retries: int = 0
    retry_backoff_s: float = 0.0
    name: str = ""
    #: Monotonic tiebreaker so equal priorities keep registration order.
    #: Without it, sorting is unstable across runs and two handlers that must
    #: run in a fixed order would swap unpredictably.
    seq: int = 0

    def __post_init__(self) -> None:
        if not self.name:
            self.name = getattr(self.handler, "__name__", repr(self.handler))


@dataclass
class Metrics:
    """Counters and timings. A bus nobody can see into is hard to trust."""

    published: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    handled: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    retries: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    duration_ms: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def snapshot(self) -> dict[str, Any]:
        return {
            "published": dict(self.published),
            "handled": dict(self.handled),
            "errors": dict(self.errors),
            "retries": dict(self.retries),
            "duration_ms": {k: round(v, 3) for k, v in self.duration_ms.items()},
            "total_published": sum(self.published.values()),
            "total_errors": sum(self.errors.values()),
        }

    def reset(self) -> None:
        for d in (self.published, self.handled, self.errors, self.retries,
                  self.duration_ms):
            d.clear()


# ── dispatcher ──────────────────────────────────────────────────────────────
class EventDispatcher:
    """Delivers one event to a list of subscriptions.

    Owns priority ordering, retries, timing and isolation. Separate from the
    bus so delivery policy is testable without a publisher, and replaceable
    without touching either side.
    """

    def __init__(self, *, metrics: Optional[Metrics] = None,
                 on_error: Optional[ErrorSink] = None,
                 logger: Any = None) -> None:
        self.metrics = metrics or Metrics()
        self._on_error = on_error
        self._log = logger

    def dispatch(self, event: Any, subs: list[Subscription]) -> None:
        """Run every subscription. Never raises on a handler's behalf."""
        name = type(event).__name__
        for sub in subs:
            self._run(event, sub, name)

    def _run(self, event: Any, sub: Subscription, event_name: str) -> None:
        attempts = sub.retries + 1
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                result = sub.handler(event)
                # An async handler returns a coroutine from a sync call. Awaiting
                # it is the caller's job (publish_async); here it would be
                # created and never awaited, which leaks and warns. Reject it
                # loudly rather than silently dropping the work.
                if inspect.iscoroutine(result):
                    result.close()
                    raise EventBusError(
                        f"{sub.name} is async but was dispatched synchronously — "
                        "publish it with publish_async, or subscribe a sync handler")
            except Exception as exc:  # noqa: BLE001 — isolation is the point
                self.metrics.errors[f"{event_name}:{sub.name}"] += 1
                last = attempt == attempts - 1
                if not last:
                    self.metrics.retries[f"{event_name}:{sub.name}"] += 1
                    if sub.retry_backoff_s:
                        time.sleep(sub.retry_backoff_s * (attempt + 1))
                    continue
                self._report(exc, event, sub)
                return
            else:
                elapsed = (time.perf_counter() - started) * 1000
                self.metrics.handled[f"{event_name}:{sub.name}"] += 1
                self.metrics.duration_ms[f"{event_name}:{sub.name}"] += elapsed
                return

    async def dispatch_async(self, event: Any, subs: list[Subscription]) -> None:
        """Async delivery. Sync handlers still run inline, in priority order.

        Coroutine handlers are awaited one at a time rather than gathered:
        priority is an ordering promise, and gathering would break it the
        moment two async handlers had different priorities.
        """
        name = type(event).__name__
        for sub in subs:
            attempts = sub.retries + 1
            for attempt in range(attempts):
                started = time.perf_counter()
                try:
                    result = sub.handler(event)
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:  # noqa: BLE001
                    self.metrics.errors[f"{name}:{sub.name}"] += 1
                    last = attempt == attempts - 1
                    if not last:
                        self.metrics.retries[f"{name}:{sub.name}"] += 1
                        if sub.retry_backoff_s:
                            await asyncio.sleep(sub.retry_backoff_s * (attempt + 1))
                        continue
                    self._report(exc, event, sub)
                    break
                else:
                    elapsed = (time.perf_counter() - started) * 1000
                    self.metrics.handled[f"{name}:{sub.name}"] += 1
                    self.metrics.duration_ms[f"{name}:{sub.name}"] += elapsed
                    break

    def _report(self, exc: BaseException, event: Any, sub: Subscription) -> None:
        if self._log is not None:
            try:
                self._log.error("eventbus.handler_failed", handler=sub.name,
                                event=type(event).__name__, error=type(exc).__name__,
                                message=str(exc))
            except Exception:  # noqa: BLE001 — a broken logger must not cascade
                pass
        if self._on_error is None:
            if self._log is None:
                # No sink and no logger: still surface it. A silently dropped
                # handler error is an integration that looks wired and does
                # nothing.
                print(f"[eventbus] handler {sub.name!r} failed on "
                      f"{type(event).__name__}: {exc}\n{traceback.format_exc()}",
                      flush=True)
            return
        try:
            self._on_error(exc, event, sub.handler)
        except Exception:  # noqa: BLE001 — a broken sink must not cascade
            pass


# ── bus ─────────────────────────────────────────────────────────────────────
class InMemoryEventBus:
    """Synchronous publish/subscribe. Satisfies ``core.interfaces.EventBus``."""

    def __init__(self, *, on_handler_error: Optional[ErrorSink] = None,
                 registry: Optional[EventRegistry] = None,
                 dispatcher: Optional[EventDispatcher] = None,
                 logger: Any = None,
                 publish_errors_as_events: bool = True) -> None:
        self._subs: dict[type, list[Subscription]] = defaultdict(list)
        self._lock = threading.RLock()
        self._depth = threading.local()
        self._seq = 0
        self.registry = registry or default_registry
        self.dispatcher = dispatcher or EventDispatcher(
            on_error=on_handler_error, logger=logger)
        #: Republish handler failures as ErrorOccurred, so an error monitor is
        #: an ordinary subscriber rather than a special case wired separately.
        #: Guarded against recursion: a failing ErrorOccurred handler must not
        #: publish another ErrorOccurred.
        self._publish_errors = publish_errors_as_events
        if self._publish_errors:
            base_sink = self.dispatcher._on_error

            def sink(exc: BaseException, event: Any, handler: Handler) -> None:
                if base_sink is not None:
                    base_sink(exc, event, handler)
                if not isinstance(event, ErrorOccurred):
                    self.publish(ErrorOccurred.from_exception(
                        exc, module="eventbus",
                        correlation_id=getattr(event, "correlation_id", "")))

            self.dispatcher._on_error = sink

    # ------------------------------------------------------------ properties
    @property
    def metrics(self) -> Metrics:
        return self.dispatcher.metrics

    @property
    def published_count(self) -> int:
        return sum(self.dispatcher.metrics.published.values())

    @property
    def handler_error_count(self) -> int:
        return sum(self.dispatcher.metrics.errors.values())

    # ------------------------------------------------------------ subscribe
    def subscribe(self, event_type: type, handler: Handler, *,
                  priority: int = Priority.NORMAL, retries: int = 0,
                  retry_backoff_s: float = 0.0,
                  name: str = "") -> Callable[[], None]:
        """Register ``handler`` for ``event_type`` and its subclasses.

        Returns a disposer rather than requiring ``unsubscribe(type, handler)``:
        a caller cannot get the pair wrong, and a bound method or lambda —
        which does not compare equal to a fresh reference to itself — can still
        be removed.

        ``retries`` defaults to 0 deliberately. Retrying a handler with side
        effects duplicates them, so opting in is a decision the subscriber
        makes knowing whether its work is idempotent.
        """
        with self._lock:
            self._seq += 1
            sub = Subscription(event_type=event_type, handler=handler,
                               priority=priority, retries=retries,
                               retry_backoff_s=retry_backoff_s, name=name,
                               seq=self._seq)
            self._subs[event_type].append(sub)

        disposed = False

        def dispose() -> None:
            nonlocal disposed
            if disposed:          # idempotent: a double-dispose must not
                return            # remove a later identical subscription
            disposed = True
            with self._lock:
                try:
                    self._subs[sub.event_type].remove(sub)
                except ValueError:  # pragma: no cover — already gone
                    pass

        return dispose

    def _matching(self, event: Any) -> list[Subscription]:
        """Subscriptions for this event and every base class, highest priority
        first, registration order within a priority."""
        with self._lock:
            found: list[Subscription] = []
            for etype in type(event).__mro__:
                found.extend(self._subs.get(etype, ()))
            self.dispatcher.metrics.published[type(event).__name__] += 1
        return sorted(found, key=lambda s: (-s.priority, s.seq))

    # -------------------------------------------------------------- publish
    def publish(self, event: Any) -> None:
        """Deliver synchronously. Never raises on a handler's behalf.

        Handlers run OUTSIDE the lock so one may subscribe, unsubscribe or
        publish without deadlocking.
        """
        depth = getattr(self._depth, "value", 0)
        if depth >= MAX_PUBLISH_DEPTH:
            raise EventBusError(
                f"publish depth {depth} exceeded on {type(event).__name__} — "
                "a handler is publishing an event that leads back to itself")
        subs = self._matching(event)
        self._depth.value = depth + 1
        try:
            self.dispatcher.dispatch(event, subs)
        finally:
            self._depth.value = depth

    async def publish_async(self, event: Any) -> None:
        """Deliver, awaiting any coroutine handlers.

        The only way an async handler runs to completion. A sync ``publish``
        cannot await, and firing a coroutine off to a background loop would
        break the guarantee that the work is done when publish returns.
        """
        depth = getattr(self._depth, "value", 0)
        if depth >= MAX_PUBLISH_DEPTH:
            raise EventBusError(
                f"publish depth {depth} exceeded on {type(event).__name__}")
        subs = self._matching(event)
        self._depth.value = depth + 1
        try:
            await self.dispatcher.dispatch_async(event, subs)
        finally:
            self._depth.value = depth

    # ----------------------------------------------------------- inspection
    def subscriber_count(self, event_type: Optional[type] = None) -> int:
        with self._lock:
            if event_type is not None:
                return len(self._subs.get(event_type, ()))
            return sum(len(v) for v in self._subs.values())

    def clear(self) -> None:
        """Drop every subscription. For test isolation — a subscriber leaked
        from one test makes an unrelated one fail later."""
        with self._lock:
            self._subs.clear()

    def publisher(self, source: str, *, correlation_id: str = "") -> "EventPublisher":
        return EventPublisher(self, source=source, correlation_id=correlation_id)


class NullEventBus:
    """Accepts and discards. The default wherever a bus is optional, so a
    caller never needs ``if self._bus is not None`` at a publish site — those
    guards are how an event ends up published on one path and not another."""

    def publish(self, event: Any) -> None:
        return None

    async def publish_async(self, event: Any) -> None:
        return None

    def subscribe(self, event_type: type, handler: Handler, **kw: Any) -> Callable[[], None]:
        return lambda: None

    def publisher(self, source: str, *, correlation_id: str = "") -> "EventPublisher":
        return EventPublisher(self, source=source, correlation_id=correlation_id)


# ── publisher ───────────────────────────────────────────────────────────────
class EventPublisher:
    """A bus handle bound to a source, and optionally a correlation id.

    Stamping the envelope here rather than at each call site means ``source``
    cannot drift from the module actually publishing, and a causal chain shares
    one correlation id without every call remembering to pass it.
    """

    def __init__(self, bus: Any, *, source: str, correlation_id: str = "") -> None:
        self._bus = bus
        self.source = source
        self.correlation_id = correlation_id

    def _stamp(self, event: Event) -> Event:
        """Fill in envelope fields the caller left empty.

        Never overwrites: an event that already names its source or chain knows
        better than this publisher does, and clobbering would erase the
        provenance of anything forwarded from elsewhere.
        """
        from dataclasses import replace
        changes: dict[str, Any] = {}
        if not getattr(event, "source", ""):
            changes["source"] = self.source
        if self.correlation_id and not getattr(event, "correlation_id", ""):
            changes["correlation_id"] = self.correlation_id
        return replace(event, **changes) if changes else event

    def publish(self, event: Event) -> None:
        self._bus.publish(self._stamp(event))

    async def publish_async(self, event: Event) -> None:
        await self._bus.publish_async(self._stamp(event))

    def correlated(self, correlation_id: str = "") -> "EventPublisher":
        """A publisher for one causal chain. Call once per chain — a bar
        arriving, say — and pass the result down, so every event it produces
        shares an id."""
        return EventPublisher(self._bus, source=self.source,
                              correlation_id=correlation_id or new_id())


# ── subscriber ──────────────────────────────────────────────────────────────
class EventSubscriber:
    """Base for subscribers that hold state.

    Subclasses declare ``handles`` — a mapping of event type to method name —
    and call ``attach``. Keeping the wiring in one place means a subscriber
    cannot half-register: attach and detach are symmetric by construction,
    which a scattering of manual subscribe calls is not.
    """

    #: {event_type: method_name} or {event_type: (method_name, priority)}
    handles: dict[type, Any] = {}

    def __init__(self) -> None:
        self._disposers: list[Callable[[], None]] = []

    def attach(self, bus: Any) -> "EventSubscriber":
        for event_type, spec in self.handles.items():
            method_name, priority = (spec if isinstance(spec, tuple)
                                     else (spec, Priority.NORMAL))
            handler = getattr(self, method_name)
            self._disposers.append(
                bus.subscribe(event_type, handler, priority=priority,
                              name=f"{type(self).__name__}.{method_name}"))
        return self

    def detach(self) -> None:
        for dispose in self._disposers:
            dispose()
        self._disposers.clear()


# ── process default ─────────────────────────────────────────────────────────
_default_bus = InMemoryEventBus()


def default_bus() -> InMemoryEventBus:
    """Process-wide default. Explicit injection is preferred and every consumer
    takes a bus argument; this exists because the wiring in ``automation-hub``
    is module-level singletons today, and several buses that cannot see each
    other would be worse than one shared."""
    return _default_bus


__all__ = [
    "InMemoryEventBus", "NullEventBus", "EventBusError",
    "EventRegistry", "EventDispatcher", "EventPublisher", "EventSubscriber",
    "Subscription", "Priority", "Metrics",
    "default_bus", "default_registry", "MAX_PUBLISH_DEPTH",
]
