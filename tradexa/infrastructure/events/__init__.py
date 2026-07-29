"""In-process event bus — the ``EventBus`` port, implemented.

Synchronous and in-process by design. An async or cross-process bus would be a
larger commitment than this system currently needs, and the failure modes it
introduces (ordering, backpressure, at-least-once delivery) are worse than the
coupling it removes. A synchronous bus is a decoupled function call: the
publisher does not know who listens, but it still knows the work is done when
``publish`` returns.

Four properties are load-bearing in a trading system, and each is tested:

*A failing subscriber cannot break the publisher.* If a Telegram notifier
raises while handling ``OrderFilled``, the fill must still be recorded. Handler
exceptions are caught, routed to an error sink, and the remaining subscribers
still run. This is the single most important rule here — a bus that propagates
handler failures is strictly worse than direct calls, because it fails a
publisher on behalf of code the publisher never chose to depend on.

*Publication is thread-safe.* The engine, the watchdog and the monitor each run
on their own thread and will publish concurrently.

*Subscribers see subclass events.* Subscribing to ``Event`` receives
everything, which is what makes an audit log or a decision recorder a
subscriber rather than a special case.

*Re-entrant publication terminates.* A handler may publish; the bus must not
deadlock on its own lock or recurse without bound.
"""
from __future__ import annotations

import threading
import traceback
from collections import defaultdict
from typing import Any, Callable, Optional

from tradexa.core.events import Event

Handler = Callable[[Any], None]
ErrorSink = Callable[[BaseException, Any, Handler], None]

#: A publish chain deeper than this is treated as a cycle. Trading loops are
#: shallow: a fill triggers a position update triggers a portfolio update is
#: three. Twenty is far beyond any legitimate chain and short of a stack
#: overflow, so a cycle is reported as a cycle rather than as a crash.
MAX_PUBLISH_DEPTH = 20


class EventBusError(RuntimeError):
    """Raised for a bus-level fault (a publish cycle), never for a handler's
    own exception — those are isolated, not raised."""


class InMemoryEventBus:
    """Synchronous publish/subscribe. Satisfies ``tradexa.core.interfaces.EventBus``."""

    def __init__(self, *, on_handler_error: Optional[ErrorSink] = None) -> None:
        self._handlers: dict[type, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()
        self._on_handler_error = on_handler_error
        self._depth = threading.local()
        #: Counters for diagnostics. A bus nobody can see into is hard to
        #: trust; these answer "is anything actually being published?".
        self.published_count = 0
        self.handler_error_count = 0

    # ------------------------------------------------------------ subscribe
    def subscribe(self, event_type: type, handler: Handler) -> Callable[[], None]:
        """Register ``handler`` for ``event_type`` and its subclasses.

        Returns a callable that unsubscribes. Returning the disposer rather
        than requiring ``unsubscribe(type, handler)`` means a caller cannot get
        the pair wrong, and a bound method or lambda — which does not compare
        equal to a fresh reference to itself — can still be removed.
        """
        with self._lock:
            self._handlers[event_type].append(handler)

        disposed = False

        def dispose() -> None:
            nonlocal disposed
            if disposed:                       # idempotent: a double-dispose
                return                         # must not remove a later
            disposed = True                    # identical subscription
            with self._lock:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:             # pragma: no cover - already gone
                    pass

        return dispose

    # -------------------------------------------------------------- publish
    def publish(self, event: Any) -> None:
        """Deliver ``event`` to every matching handler.

        Never raises on a handler's behalf. Handlers are invoked outside the
        lock so one may subscribe, unsubscribe or publish without deadlocking.
        """
        depth = getattr(self._depth, "value", 0)
        if depth >= MAX_PUBLISH_DEPTH:
            raise EventBusError(
                f"publish depth {depth} exceeded while handling "
                f"{type(event).__name__} — a handler is publishing an event "
                "that leads back to itself.")

        # Snapshot under the lock, then release it. Iterating the live list
        # would break if a handler unsubscribed mid-delivery, and holding the
        # lock across handler calls would deadlock the moment one publishes.
        with self._lock:
            matched: list[Handler] = []
            for etype in type(event).__mro__:
                matched.extend(self._handlers.get(etype, ()))
            self.published_count += 1

        self._depth.value = depth + 1
        try:
            for handler in matched:
                try:
                    handler(event)
                except Exception as exc:  # noqa: BLE001 — isolation is the point
                    self.handler_error_count += 1
                    self._report(exc, event, handler)
        finally:
            self._depth.value = depth

    def _report(self, exc: BaseException, event: Any, handler: Handler) -> None:
        if self._on_handler_error is None:
            # No sink configured: still surface it. A silently dropped handler
            # error is an integration that looks wired up and does nothing.
            print(f"[eventbus] handler {getattr(handler, '__name__', handler)!r} "
                  f"failed on {type(event).__name__}: {exc}\n"
                  f"{traceback.format_exc()}", flush=True)
            return
        try:
            self._on_handler_error(exc, event, handler)
        except Exception:  # noqa: BLE001 — a broken sink must not cascade
            pass

    # ----------------------------------------------------------- inspection
    def subscriber_count(self, event_type: Optional[type] = None) -> int:
        with self._lock:
            if event_type is not None:
                return len(self._handlers.get(event_type, ()))
            return sum(len(v) for v in self._handlers.values())

    def clear(self) -> None:
        """Drop every subscription. For test isolation — a leaked subscriber
        from a previous test makes the next one fail somewhere unrelated."""
        with self._lock:
            self._handlers.clear()


class NullEventBus:
    """A bus that accepts and discards.

    The default wherever a bus is optional, so a caller can always publish
    without a ``if self._bus is not None`` guard at every call site — those
    guards are how an event ends up published on one path and not another.
    """

    def publish(self, event: Any) -> None:  # noqa: D102
        return None

    def subscribe(self, event_type: type, handler: Handler) -> Callable[[], None]:  # noqa: D102
        return lambda: None


#: Process-wide default. Explicit injection is preferred and every consumer
#: takes a bus argument; this exists so the wiring in `automation-hub`, which
#: is module-level singletons today, has one bus to reach for rather than
#: constructing several that cannot see each other.
_default_bus = InMemoryEventBus()


def default_bus() -> InMemoryEventBus:
    return _default_bus


__all__ = ["InMemoryEventBus", "NullEventBus", "EventBusError", "default_bus",
           "MAX_PUBLISH_DEPTH", "Event"]
