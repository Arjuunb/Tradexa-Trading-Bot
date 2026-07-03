"""Daily performance report — the sheet a professional reviews every morning.

Builds one honest digest from the bot's own records (P&L today/week/total,
win rate, open positions, missed entries, new lessons learned, watchdog
findings, data source) and sends it to Telegram once a day at a configured
UTC hour. ``build_report``/``format_report`` are pure; ``DailyTasks`` is the
tiny scheduler thread that also triggers the nightly ledger backup.

No Telegram configured -> the report still builds for GET /report/daily;
sending is simply skipped (and says so).
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable, Optional


def _day(ts: Optional[str]) -> str:
    return (ts or "")[:10]


def build_report(*, history: list[dict], positions: list[dict], balance: float,
                 starting_balance: float, learning_report: Optional[dict] = None,
                 watchdog_status: Optional[dict] = None,
                 engine_status: Optional[dict] = None,
                 counterfactual_report: Optional[dict] = None,
                 now: Optional[datetime] = None) -> dict:
    """Pure digest from the bot's records (history is newest-first)."""
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    week = now.isocalendar()[:2]
    closed = [t for t in history if t.get("status", "closed") == "closed"]

    def _stats(rows):
        n = len(rows)
        pnl = sum(t.get("pnl") or 0.0 for t in rows)
        wins = sum(1 for t in rows if (t.get("pnl") or 0.0) > 0)
        return {"trades": n, "pnl": round(pnl, 2),
                "win_rate": round(100 * wins / n, 1) if n else None}

    today_rows = [t for t in closed if _day(t.get("closed_at")) == today]
    week_rows = []
    for t in closed:
        try:
            d = datetime.fromisoformat(t.get("closed_at") or "")
            if d.isocalendar()[:2] == week:
                week_rows.append(t)
        except ValueError:
            continue

    lessons_today = []
    adjustments = {}
    if learning_report:
        adjustments = learning_report.get("active_adjustments", {}) or {}
        lessons_today = [h for h in (learning_report.get("evolution") or [])
                         if _day(h.get("ts")) == today]
    findings = (watchdog_status or {}).get("findings") or []
    eng = engine_status or {}
    return {
        "date": today,
        "balance": round(balance, 2),
        "total_pnl": round(balance - starting_balance, 2),
        "today": _stats(today_rows),
        "week": _stats(week_rows),
        "all_time": _stats(closed),
        "open_positions": [{"symbol": p.get("symbol"), "side": p.get("side"),
                            "entry": p.get("entry")} for p in positions],
        "engine": {"running": eng.get("running"), "mode": eng.get("mode"),
                   "strategy": eng.get("strategy"), "entry_mode": eng.get("entry_mode"),
                   "missed_entries": eng.get("missed_entries"),
                   "data_source": eng.get("data_source")},
        "active_learned_rules": len(adjustments),
        "lessons_today": lessons_today,
        "watchdog_findings": findings,
        "gates": ({"saved_r": counterfactual_report.get("total_saved_r"),
                   "costing": [k for k, s in (counterfactual_report.get("rules") or {}).items()
                               if s.get("verdict") == "costing"]}
                  if counterfactual_report else None),
    }


def format_report(r: dict) -> str:
    """Telegram-ready text. Short, scannable, nothing decorative."""
    def pnl(v):
        return f"{v:+.2f}" if v is not None else "—"

    lines = [f"📊 Daily report — {r['date']}",
             f"Balance {r['balance']:.2f} (total {pnl(r['total_pnl'])})",
             f"Today: {r['today']['trades']} trades, P&L {pnl(r['today']['pnl'])}"
             + (f", win {r['today']['win_rate']}%" if r['today']['win_rate'] is not None else ""),
             f"Week: {r['week']['trades']} trades, P&L {pnl(r['week']['pnl'])}"]
    if r["open_positions"]:
        syms = ", ".join(f"{p['symbol']} {p['side']}" for p in r["open_positions"])
        lines.append(f"Open: {syms}")
    else:
        lines.append("Open: none")
    eng = r["engine"]
    state = "running" if eng.get("running") else "STOPPED"
    lines.append(f"Engine: {state} ({eng.get('strategy')}, {eng.get('mode')}, "
                 f"entries {eng.get('entry_mode')})")
    if eng.get("missed_entries"):
        lines.append(f"Missed limit entries: {eng['missed_entries']}")
    if r["active_learned_rules"]:
        lines.append(f"Learned rules in force: {r['active_learned_rules']}")
    for h in r["lessons_today"][:3]:
        lines.append(f"🧠 {h.get('action')}: {h.get('lesson', '')[:120]}")
    for f in r["watchdog_findings"][:3]:
        lines.append(f"🐕 {f.get('title')}")
    if not r["watchdog_findings"]:
        lines.append("Watchdog: all clear")
    gates = r.get("gates")
    if gates and gates.get("saved_r") is not None:
        line = f"Gates saved {gates['saved_r']:+.1f}R"
        if gates.get("costing"):
            line += f" — under review: {', '.join(gates['costing'][:2])}"
        lines.append(line)
    return "\n".join(lines)


class DailyTasks:
    """Fires the daily report (+ any extra callbacks, e.g. backups) once per
    UTC day at ``hour``. Checks every few minutes; survives restarts by simply
    not re-sending within the same day."""

    def __init__(self, send: Callable[[str], None], build: Callable[[], dict], *,
                 hour: int = 8, extra: Optional[list[Callable[[], None]]] = None,
                 poll_s: float = 300.0):
        self.send = send
        self.build = build
        self.hour = int(hour)
        self.extra = list(extra or [])
        self.poll_s = poll_s
        self.last_sent_day: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def due(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return (self.hour >= 0 and now.hour >= self.hour
                and self.last_sent_day != now.date().isoformat())

    def run_once(self, now: Optional[datetime] = None) -> Optional[dict]:
        """Build + send + run extras; marks the day. Returns the report."""
        now = now or datetime.now(timezone.utc)
        report = self.build()
        try:
            self.send(format_report(report))
        except Exception:  # noqa: BLE001 — reporting must never crash the bot
            pass
        for fn in self.extra:
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        self.last_sent_day = now.date().isoformat()
        return report

    def start(self) -> bool:
        if self.hour < 0 or (self._thread and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="daily-tasks", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self.due():
                    self.run_once()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(self.poll_s)
