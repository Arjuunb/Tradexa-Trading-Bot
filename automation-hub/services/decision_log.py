"""Decision Log service (Phase 2 · Decision Transparency).

A reusable, bus-driven service that turns the engine's event stream into a
queryable record of *why* the bot did (or didn't) trade. It captures one
``DecisionRecord`` per signal, resolving its verdict from the events that follow:

    signal  ->  order        => executed   (passed risk + execution checks)
            ->  risk_block    => rejected   (risk reason)
            ->  decision      => verdict from the execution-safety gate
                                 (rules passed/failed)
            ->  (none)        => skipped    (already in a position / filtered)

It reuses the existing events (no engine changes), so it works for backtests,
paper, and live. Attach it to any ``EventBus``; query via ``recent`` / ``records``
/ ``for_symbol``. The bot never behaves like a black box.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DecisionRecord:
    time: str
    symbol: str
    strategy: str
    signal: str
    verdict: str                       # executed | rejected | blocked | skipped
    reason: str
    confidence: Optional[float] = None
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "time": self.time, "symbol": self.symbol, "strategy": self.strategy,
            "signal": self.signal, "verdict": self.verdict, "reason": self.reason,
            "confidence": self.confidence, "passed": list(self.passed),
            "failed": list(self.failed),
        }


_VERDICT = {"allowed": "executed", "rejected": "rejected", "blocked": "blocked"}


class DecisionLog:
    def __init__(self, strategy: str = "", limit: int = 500):
        self.strategy = strategy
        self._records: deque[DecisionRecord] = deque(maxlen=limit)
        self._pending: dict[str, dict] = {}    # symbol -> {record?, signal info}

    def attach(self, bus) -> None:
        bus.subscribe(self)

    # ------------------------------------------------------------------ events
    def __call__(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "signal":
            self._pending[ev["symbol"]] = {
                "time": ev.get("bar_ts") or ev.get("ts") or "",
                "symbol": ev["symbol"],
                "signal": str(ev.get("side", "")).upper(),
                "confidence": ev.get("confidence"),
                "reason": ev.get("reason", ""),
                "record": None,
            }
        elif t == "order":
            self._resolve(ev.get("symbol"), "executed",
                          "Passed risk + execution checks — order placed.",
                          passed=["risk_per_trade", "daily_loss_limit", "max_open_positions"])
        elif t == "risk_block":
            self._resolve(ev.get("symbol"), "rejected",
                          ev.get("reason", "risk check failed"),
                          failed=[ev.get("reason", "risk check failed")])
        elif t == "decision":  # richest — from the execution-safety gate
            checks = ev.get("checks", [])
            self._resolve(
                ev.get("symbol"), _VERDICT.get(ev.get("verdict", ""), "rejected"),
                ev.get("reason", ""),
                passed=[c["rule"] for c in checks if c.get("passed")],
                failed=[c["rule"] for c in checks if not c.get("passed")],
                overwrite=True,
            )
        elif t == "bar":
            p = self._pending.get(ev.get("symbol"))
            if p is not None and p["record"] is None:
                self._commit(p, "skipped",
                             "Signal not actioned (already in a position or filtered).")
            self._pending.pop(ev.get("symbol"), None)

    # ------------------------------------------------------------------ helpers
    def _resolve(self, symbol, verdict, reason, passed=None, failed=None, overwrite=False):
        p = self._pending.get(symbol)
        if p is None:
            return
        rec = p["record"]
        if rec is None:
            self._commit(p, verdict, reason, passed, failed)
        elif overwrite:
            rec.verdict = verdict
            rec.reason = reason or rec.reason
            if passed:
                rec.passed = passed
            if failed:
                rec.failed = failed

    def _commit(self, p, verdict, reason, passed=None, failed=None):
        rec = DecisionRecord(
            time=p["time"], symbol=p["symbol"], strategy=self.strategy,
            signal=p["signal"], verdict=verdict, reason=reason,
            confidence=p["confidence"],
            passed=list(passed or []), failed=list(failed or []),
        )
        self._records.append(rec)
        p["record"] = rec

    # ------------------------------------------------------------------ query
    def records(self) -> list[DecisionRecord]:
        return list(self._records)

    def recent(self, n: int = 50) -> list[dict]:
        return [r.to_dict() for r in list(self._records)[-n:][::-1]]

    def for_symbol(self, symbol: str) -> list[DecisionRecord]:
        return [r for r in self._records if r.symbol == symbol]
