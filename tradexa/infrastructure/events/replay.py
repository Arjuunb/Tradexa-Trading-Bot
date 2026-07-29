"""Event recording and replay.

Debugging a trading bot after the fact is normally archaeology: a ledger row,
a log line, a position that exists for reasons nobody can reconstruct. A
recorded event stream turns that into a question you can re-run — take the
sequence that produced a bad trade and push it through the system again, with
a debugger attached and nothing hitting a real venue.

Two guarantees make that useful rather than misleading.

*Recording never affects what it records.* The recorder is an ordinary
subscriber at BACKGROUND priority, so it runs after everything that matters,
and its failures are isolated like any other handler's.

*Replay is honest about what it is.* Every replayed event carries
``metadata["replayed"] = True`` and keeps its ORIGINAL event_id and timestamp.
A replayed fill must never be mistaken for a live one — by a subscriber, by a
log reader, or by a metric. Anything that writes to a real store should refuse
replayed events, and it can only do that if they say so.

Serialisation is best-effort by design. Events carry domain objects — Bars,
Orders, Positions — and a journal that refuses to write anything it cannot
perfectly round-trip would record nothing on the events most worth having. So
a payload is stored as its repr when it will not serialise, and the entry is
marked lossy. A lossy record still answers "what happened, in what order, with
what correlation id", which is the question replay is for.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

from tradexa.core.events import ENVELOPE_FIELDS, Event
from tradexa.infrastructure.events.bus import EventRegistry, Priority, default_registry


@dataclass
class RecordedEvent:
    """One journal entry: the event, plus whether it survived serialisation."""

    event: Event
    lossy_fields: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return type(self.event).__name__


def _jsonable(value: Any) -> tuple[Any, bool]:
    """Return ``(serialisable_value, was_lossy)``."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value, False
    if isinstance(value, datetime):
        return value.isoformat(), False
    if isinstance(value, (list, tuple)):
        out, lossy = [], False
        for item in value:
            v, l = _jsonable(item)
            out.append(v)
            lossy = lossy or l
        return out, lossy
    if isinstance(value, dict):
        out_d, lossy = {}, False
        for k, v in value.items():
            jv, l = _jsonable(v)
            out_d[str(k)] = jv
            lossy = lossy or l
        return out_d, lossy
    # A domain object. Flatten dataclasses one level so a Bar's numbers survive
    # rather than becoming an opaque repr — those are exactly the fields worth
    # reading back.
    if hasattr(value, "__dataclass_fields__"):
        out_d, lossy = {}, False
        for f in fields(value):
            jv, l = _jsonable(getattr(value, f.name))
            out_d[f.name] = jv
            lossy = lossy or l
        return out_d, lossy
    return repr(value), True


class EventRecorder:
    """Captures every event passing through a bus.

    Subscribes to ``Event`` itself, so it sees the whole vocabulary rather than
    a list someone has to remember to extend.
    """

    def __init__(self, *, limit: int = 10_000,
                 predicate: Optional[Callable[[Event], bool]] = None) -> None:
        #: Bounded. An unbounded recorder on a long-running bot is a memory
        #: leak with a helpful name; the oldest entries are dropped first,
        #: because the recent past is what a debugging session needs.
        self.limit = limit
        self._predicate = predicate
        self._events: list[RecordedEvent] = []
        self._lock = threading.RLock()
        self._dropped = 0

    # ------------------------------------------------------------ recording
    def __call__(self, event: Event) -> None:
        if self._predicate is not None and not self._predicate(event):
            return
        lossy: list[str] = []
        for key, value in getattr(event, "payload", {}).items():
            _, was_lossy = _jsonable(value)
            if was_lossy:
                lossy.append(key)
        with self._lock:
            self._events.append(RecordedEvent(event, tuple(lossy)))
            while len(self._events) > self.limit:
                self._events.pop(0)
                self._dropped += 1

    def attach(self, bus: Any) -> Callable[[], None]:
        """Subscribe at BACKGROUND priority — after everything that matters,
        so recording can never delay or reorder real work."""
        return bus.subscribe(Event, self, priority=Priority.BACKGROUND,
                             name="EventRecorder")

    # ----------------------------------------------------------- inspection
    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def dropped(self) -> int:
        """Entries evicted by the limit. Reported rather than silent: a replay
        that starts mid-chain is misleading unless you know it was truncated."""
        return self._dropped

    def events(self) -> list[Event]:
        with self._lock:
            return [r.event for r in self._events]

    def records(self) -> list[RecordedEvent]:
        with self._lock:
            return list(self._events)

    def by_correlation(self, correlation_id: str) -> list[Event]:
        """One causal chain, in order. The reason correlation ids exist."""
        with self._lock:
            return [r.event for r in self._events
                    if r.event.correlation_id == correlation_id]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._dropped = 0

    # --------------------------------------------------------- serialisation
    def to_jsonl(self) -> str:
        """One JSON object per line — appendable, greppable, and readable with
        `tail` while a bot is running."""
        lines = []
        for record in self.records():
            payload, _ = _jsonable(record.event.payload)
            entry = record.event.envelope()
            entry["payload"] = payload
            if record.lossy_fields:
                entry["lossy_fields"] = list(record.lossy_fields)
            lines.append(json.dumps(entry, sort_keys=True))
        return "\n".join(lines)

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_jsonl(), encoding="utf-8")
        return p


class EventReplayer:
    """Re-publishes a recorded sequence.

    Replay is for reproducing a decision path, not for reproducing side
    effects. Every replayed event is marked, and a subscriber that writes to a
    real store is expected to check.
    """

    def __init__(self, bus: Any, *, registry: Optional[EventRegistry] = None) -> None:
        self._bus = bus
        self.registry = registry or default_registry

    @staticmethod
    def mark(event: Event) -> Event:
        """Stamp an event as replayed, preserving id and timestamp.

        Keeping the ORIGINAL event_id is deliberate: it is what lets a replayed
        event be matched against the log line the live one wrote. Minting a new
        id would make the two impossible to correlate — which is the whole
        point of the exercise.
        """
        meta = dict(getattr(event, "metadata", {}) or {})
        meta["replayed"] = True
        return replace(event, metadata=meta)

    def replay(self, events: Iterable[Event], *,
               predicate: Optional[Callable[[Event], bool]] = None) -> int:
        """Publish each event in order. Returns how many were published."""
        count = 0
        for event in events:
            if predicate is not None and not predicate(event):
                continue
            self._bus.publish(self.mark(event))
            count += 1
        return count

    def replay_correlation(self, recorder: EventRecorder,
                           correlation_id: str) -> int:
        """Replay exactly one causal chain — the common debugging case."""
        return self.replay(recorder.by_correlation(correlation_id))


def is_replayed(event: Any) -> bool:
    """True when this event came from a replay.

    The check any handler with side effects should make before writing to a
    ledger, submitting an order, or sending a notification.
    """
    return bool((getattr(event, "metadata", None) or {}).get("replayed"))


__all__ = ["EventRecorder", "EventReplayer", "RecordedEvent", "is_replayed"]
