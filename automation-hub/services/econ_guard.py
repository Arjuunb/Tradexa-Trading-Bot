"""Economic Event Protection (#7).

High-impact macro events (CPI, FOMC, NFP, interest-rate decisions) routinely
spike volatility and gap stops. This guard, given a list of upcoming events,
decides whether to halt new entries, reduce size or widen stops around them.

The protection POLICY is real and testable; exact event times come from a
connected economic-calendar provider or a user-set list — when none is
configured we report it honestly rather than inventing dates.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

HIGH_IMPACT = ("CPI", "FOMC", "NFP", "Interest rate decision", "Rate decision",
               "PCE", "Unemployment")
EVENT_TYPES = [
    {"name": "CPI", "impact": "high", "desc": "US inflation print"},
    {"name": "FOMC", "impact": "high", "desc": "Fed rate decision / statement"},
    {"name": "NFP", "impact": "high", "desc": "US non-farm payrolls"},
    {"name": "Interest rate decision", "impact": "high", "desc": "Central-bank rate decision"},
]


def _parse(ts):
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _is_high(name: str) -> bool:
    n = (name or "").upper()
    return any(h.upper() in n for h in HIGH_IMPACT)


def evaluate(events: list, now=None, *, blackout_min: int = 30, caution_min: int = 120) -> dict:
    """Protection decision for the nearest upcoming high-impact event.

    Within ``blackout_min`` -> halt new entries; within ``caution_min`` ->
    reduce size + widen stops; otherwise normal."""
    now = now or datetime.now(timezone.utc)
    upcoming = []
    for e in events or []:
        t = _parse(e.get("time"))
        if t and t >= now and _is_high(e.get("name", "")):
            upcoming.append((t, e))
    upcoming.sort(key=lambda x: x[0])

    if not upcoming:
        return {"mode": "normal", "risk_multiplier": 1.0, "stop_multiplier": 1.0,
                "halt_new_entries": False, "next_event": None, "minutes_to_event": None,
                "actions": [], "note": "No upcoming high-impact events in range."}

    t, ev = upcoming[0]
    mins = (t - now).total_seconds() / 60.0
    if mins <= blackout_min:
        mode, risk, stop, halt = "blackout", 0.0, 1.0, True
        actions = [f"Halt new entries — {ev['name']} in {mins:.0f} min.",
                   "Let open trades run with their existing stops."]
    elif mins <= caution_min:
        mode, risk, stop, halt = "caution", 0.5, 1.5, False
        actions = [f"Reduce position size to ~50% ahead of {ev['name']}.",
                   "Widen new stops by ~1.5× to survive the volatility spike."]
    else:
        mode, risk, stop, halt = "normal", 1.0, 1.0, False
        actions = []
    return {
        "mode": mode, "risk_multiplier": risk, "stop_multiplier": stop,
        "halt_new_entries": halt,
        "next_event": {"name": ev["name"], "time": t.isoformat(), "impact": ev.get("impact", "high")},
        "minutes_to_event": round(mins, 1), "actions": actions,
        "note": f"Next high-impact event: {ev['name']} in {mins/60:.1f}h.",
    }


class EconCalendar:
    """User-set / provider-fed upcoming events (gitignored JSON)."""

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else None

    def events(self) -> list:
        try:
            if self.path and self.path.exists():
                return json.loads(self.path.read_text()).get("events", [])
        except Exception:  # noqa: BLE001
            pass
        return []

    def set_events(self, events: list) -> list:
        clean = [{"name": e.get("name", ""), "impact": e.get("impact", "high"),
                  "time": e.get("time")} for e in (events or []) if e.get("name") and e.get("time")]
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"events": clean}, indent=2))
        return clean

    @property
    def connected(self) -> bool:
        return bool(self.events()) or bool(os.environ.get("ECON_CALENDAR_KEY"))
