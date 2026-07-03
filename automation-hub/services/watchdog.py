"""Watchdog — a silent dead bot is worse than a losing one.

Every cycle it checks the things that fail quietly and alerts (ledger +
Telegram) when one trips, with a per-issue cooldown so a persistent problem
doesn't spam. ``evaluate`` is pure — inject the observed state, get findings —
so every rule is unit-testable; the thread just feeds it real state on an
interval and stamps a heartbeat the dashboard can display.

Checks:
    engine-stalled   engine says running but hasn't processed a bar in far
                     longer than the timeframe should deliver one
    feed-not-live    live mode, but data is coming from a non-live source
                     (bundled sample / synthetic) — no new candles will EVER arrive
    engine-down      engine was started but its thread died
    ws-degraded      the websocket stream dropped and the bot fell back to REST
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

_TF_S = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
         "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def evaluate(*, running: bool, live: bool, timeframe: str,
             last_activity_age_s: Optional[float], thread_alive: bool,
             data_source: Optional[str], ws_status: Optional[dict] = None) -> list[dict]:
    """Pure rule evaluation -> list of findings {key, severity, title, detail}."""
    findings: list[dict] = []
    if not running:
        return findings                      # a stopped bot is a choice, not a fault

    if not thread_alive:
        findings.append({"key": "engine-down", "severity": "critical",
                         "title": "Engine thread died",
                         "detail": "The engine reports running but its thread is gone. Restart the bot."})
        return findings

    tf_s = _TF_S.get(timeframe, 3600)
    if live and last_activity_age_s is not None and last_activity_age_s > max(3 * tf_s, 300):
        findings.append({"key": "engine-stalled", "severity": "critical",
                         "title": "Feed stalled — no new candles",
                         "detail": (f"No bar processed for {int(last_activity_age_s / 60)}m "
                                    f"(timeframe {timeframe}). Feed or exchange may be down.")})

    src = (data_source or "").lower()
    if live and src and not src.startswith("live"):
        findings.append({"key": "feed-not-live", "severity": "warning",
                         "title": "Live mode without a live feed",
                         "detail": f"Data source is '{data_source}' — no new candles will arrive, no trades will fire."})

    if ws_status and ws_status.get("available") and ws_status.get("last_error"):
        if not ws_status.get("running"):
            findings.append({"key": "ws-degraded", "severity": "warning",
                             "title": "WebSocket stream down — using REST fallback",
                             "detail": f"Last stream error: {ws_status['last_error']}"})
    return findings


class Watchdog:
    def __init__(self, engine, ledger, notifier=None, *, ws_feed=None,
                 interval_s: float = 60.0, cooldown_s: float = 1800.0):
        self.engine = engine
        self.ledger = ledger
        self.notifier = notifier            # Notifier.dispatch-compatible or None
        self.ws_feed = ws_feed
        self.interval_s = interval_s
        self.cooldown_s = cooldown_s
        self._last_sent: dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.last_heartbeat: Optional[str] = None
        self.last_findings: list[dict] = []

    # ------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="watchdog", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check()
            except Exception:  # noqa: BLE001 — the watchdog must never die
                pass
            self._stop.wait(self.interval_s)

    # ----------------------------------------------------------------- check
    def check(self, now: Optional[float] = None) -> list[dict]:
        import time
        now = now if now is not None else time.time()
        eng = self.engine
        age = None
        if getattr(eng, "last_activity", None):
            try:
                last = datetime.fromisoformat(eng.last_activity)
                age = (datetime.now(timezone.utc) - last).total_seconds()
            except ValueError:
                age = None
        findings = evaluate(
            running=bool(getattr(eng, "running", False)),
            live=bool(getattr(eng, "live", False)),
            timeframe=getattr(eng, "timeframe", "1h"),
            last_activity_age_s=age,
            thread_alive=bool(getattr(eng, "_thread", None) and eng._thread.is_alive()),
            data_source=getattr(eng, "last_source", None),
            ws_status=self.ws_feed.status() if self.ws_feed else None,
        )
        self.last_findings = findings
        self.last_heartbeat = datetime.now(timezone.utc).isoformat()
        for f in findings:
            if now - self._last_sent.get(f["key"], 0.0) < self.cooldown_s:
                continue                     # already alerted recently
            self._last_sent[f["key"]] = now
            self.ledger.add_alert(severity=f["severity"], category="watchdog",
                                  title=f["title"], detail=f["detail"])
            self.ledger.log(level="warning" if f["severity"] != "critical" else "error",
                            stage="watchdog", message=f"{f['title']} — {f['detail']}")
            if self.notifier:
                try:
                    self.notifier("risk", f"🐕 {f['title']}", f["detail"])
                except Exception:  # noqa: BLE001
                    pass
        return findings

    def status(self) -> dict:
        return {"running": self._thread is not None and self._thread.is_alive(),
                "interval_s": self.interval_s,
                "last_heartbeat": self.last_heartbeat,
                "findings": self.last_findings,
                "ws_feed": self.ws_feed.status() if self.ws_feed else None}
