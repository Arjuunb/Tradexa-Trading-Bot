"""Event infrastructure — bus, dispatcher, registry, publisher, replay.

The implementation lives in ``bus.py`` and ``replay.py``; this module re-exports
it. The split happened when the bus grew priorities, retries, metrics and async
delivery — one file holding all of that plus replay would be the kind of module
people stop reading.

Everything phase 2 exported is still exported from here, with the same
behaviour, so ``from tradexa.infrastructure.events import default_bus`` keeps
working and no caller had to change.
"""
from tradexa.core.events import Event
from tradexa.infrastructure.events.bus import (
    MAX_PUBLISH_DEPTH,
    EventBusError,
    EventDispatcher,
    EventPublisher,
    EventRegistry,
    EventSubscriber,
    InMemoryEventBus,
    Metrics,
    NullEventBus,
    Priority,
    Subscription,
    default_bus,
    default_registry,
)
from tradexa.infrastructure.events.replay import (
    EventRecorder,
    EventReplayer,
    RecordedEvent,
    is_replayed,
)

__all__ = [
    # bus
    "InMemoryEventBus", "NullEventBus", "EventBusError",
    "EventRegistry", "EventDispatcher", "EventPublisher", "EventSubscriber",
    "Subscription", "Priority", "Metrics",
    "default_bus", "default_registry", "MAX_PUBLISH_DEPTH",
    # replay
    "EventRecorder", "EventReplayer", "RecordedEvent", "is_replayed",
    # convenience
    "Event",
]
