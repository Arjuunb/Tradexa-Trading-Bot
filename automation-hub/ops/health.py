"""Liveness, readiness and startup — three questions, three answers.

The hub had one ``/health`` endpoint that queried Supabase status, persistence
tiers and tenancy on every call. As a Kubernetes *liveness* probe that is
actively harmful: liveness answers "should this process be killed and
restarted", so wiring it to a dependency means an upstream blip restarts a
healthy pod mid-trade and makes the outage worse. The three probes differ:

    /health/live     Is the process alive? Cheap, no dependencies, no I/O.
                     A failure here means "restart me".
    /health/ready    Can it serve traffic? Checks dependencies. A failure
                     means "take me out of the load balancer", not "restart me".
    /health/startup  Has boot finished? Gates the other two so a slow start
                     is not mistaken for a hang and killed in a loop.

``/health`` itself is untouched and still returns the rich payload the existing
dashboard and Render health check consume.

Checks are registered by ``app.py`` rather than imported here, so this module
stays free of any dependency on the store, the engine or the ledger.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

_log = logging.getLogger("hub.health")

# name -> (callable returning (ok, detail), critical)
Check = Callable[[], tuple[bool, str]]
_checks: dict[str, tuple[Check, bool]] = {}
_lock = threading.Lock()

_started_at = time.time()
_boot_complete = False
_draining = False


def register_check(name: str, fn: Check, *, critical: bool = True) -> None:
    """Register a readiness check.

    A non-critical check is reported but never fails readiness — right for
    things that are degraded-but-servable, such as the optional Supabase mirror.
    """
    with _lock:
        _checks[name] = (fn, critical)


def mark_boot_complete() -> None:
    """Boot finished — start answering readiness.

    Clears the drain flag as well. A process that has just completed startup is
    by definition not shutting down, and leaving the flag set from a previous
    lifecycle would make the new one permanently unready. In a normal container
    that never happens, because the process boots once and exits; it shows up
    anywhere the app is started more than once inside a single interpreter,
    which is exactly what the test suite does.
    """
    global _boot_complete, _draining
    _boot_complete = True
    _draining = False
    _log.info("boot complete", extra={"boot_seconds": round(time.time() - _started_at, 3)})


def begin_drain() -> None:
    """Start failing readiness while continuing to serve in-flight requests.

    Called on SIGTERM. Kubernetes removes a pod from Service endpoints and sends
    SIGTERM at roughly the same moment, and that race drops requests: the pod can
    stop before the last routing update has propagated. Failing readiness first,
    then sleeping in a preStop hook, gives endpoints time to converge before the
    process actually goes away.
    """
    global _draining
    _draining = True
    _log.info("draining: readiness now failing, in-flight requests still served")


def draining() -> bool:
    return _draining


def uptime_s() -> float:
    return time.time() - _started_at


def liveness() -> dict:
    """Deliberately trivial. If the event loop can run this, the process is
    alive and restarting it would not help anything."""
    return {"status": "alive", "uptime_s": round(uptime_s(), 1)}


def startup() -> tuple[dict, bool]:
    ok = _boot_complete
    return {"status": "started" if ok else "starting",
            "uptime_s": round(uptime_s(), 1)}, ok


def readiness() -> tuple[dict, bool]:
    """Run every registered check. Returns the payload and whether to serve."""
    if not _boot_complete:
        return {"status": "starting", "reason": "boot not complete"}, False
    if _draining:
        return {"status": "draining", "reason": "shutting down"}, False

    with _lock:
        items = list(_checks.items())

    results: dict[str, dict] = {}
    ready = True
    for name, (fn, critical) in items:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results[name] = {"ok": ok, "detail": detail, "critical": critical}
        if critical and not ok:
            ready = False

    return {"status": "ready" if ready else "not_ready",
            "uptime_s": round(uptime_s(), 1), "checks": results}, ready
