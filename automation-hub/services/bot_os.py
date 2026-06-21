"""Bot Operating System (#20).

A lightweight, in-process service + event layer that names the bot's nine
engines and lets them communicate through a shared event bus instead of direct
calls. This is the integration seam — it formalises "everything communicates
through events and services" without rewriting the existing engines, and it's
exactly the boundary Tradexa can plug into later.

EventBus is sync, fail-safe (a dead handler never breaks a publish) and keeps a
ring buffer of recent events for observability.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# the canonical engine roster + the event topics they own
ENGINES = [
    {"name": "Market Engine", "topic": "market", "desc": "Real candle store, watchlist, scanner"},
    {"name": "Strategy Engine", "topic": "strategy", "desc": "Strategy registry, selection, signals"},
    {"name": "Risk Engine", "topic": "risk", "desc": "Sizing, correlation, portfolio VaR, recovery"},
    {"name": "Execution Engine", "topic": "execution", "desc": "Paper execution, order routing"},
    {"name": "Evolution Engine", "topic": "evolution", "desc": "Lessons, versions, experiments"},
    {"name": "Analytics Engine", "topic": "analytics", "desc": "Performance, attribution, health"},
    {"name": "Replay Engine", "topic": "replay", "desc": "No-lookahead historical replay"},
    {"name": "Journal Engine", "topic": "journal", "desc": "Auto trade journal + lessons"},
    {"name": "AI Coach Engine", "topic": "coach", "desc": "Mentor review + explainability"},
]


class EventBus:
    def __init__(self, maxlen: int = 200):
        self._subs: dict = {}
        self._log: deque = deque(maxlen=maxlen)

    def subscribe(self, topic: str, handler) -> None:
        self._subs.setdefault(topic, []).append(handler)

    def publish(self, topic: str, kind: str = "event", payload: dict | None = None) -> dict:
        ev = {"topic": topic, "kind": kind, "payload": payload or {}, "ts": _now()}
        self._log.appendleft(ev)
        for fn in self._subs.get(topic, []) + self._subs.get("*", []):
            try:
                fn(ev)
            except Exception:  # noqa: BLE001 — one bad subscriber can't break the bus
                pass
        return ev

    def recent(self, n: int = 50) -> list:
        return list(self._log)[:n]


class BotOS:
    def __init__(self):
        self.bus = EventBus()
        self.services: dict = {}
        for e in ENGINES:
            self.register(e["name"], e["topic"], e["desc"])

    def register(self, name: str, topic: str, desc: str, status_fn=None) -> None:
        self.services[name] = {"name": name, "topic": topic, "desc": desc, "status_fn": status_fn}

    def set_status_fn(self, name: str, fn) -> None:
        if name in self.services:
            self.services[name]["status_fn"] = fn

    def snapshot(self) -> dict:
        services = []
        up = 0
        for s in self.services.values():
            st = {"state": "up", "detail": ""}
            if s["status_fn"]:
                try:
                    st = {**st, **(s["status_fn"]() or {})}
                except Exception as e:  # noqa: BLE001
                    st = {"state": "error", "detail": str(e)[:80]}
            up += 1 if st["state"] == "up" else 0
            services.append({"name": s["name"], "topic": s["topic"], "desc": s["desc"],
                             "state": st["state"], "detail": st.get("detail", "")})
        return {
            "engines": len(self.services), "up": up,
            "status": "healthy" if up == len(self.services) else "degraded",
            "services": services, "recent_events": self.bus.recent(40),
            "architecture": "event-bus (services publish/subscribe; no direct cross-engine calls)",
        }
