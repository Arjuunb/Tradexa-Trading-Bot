"""Live-trading readiness gate — the enforced checklist that stands between
paper mode and any future live execution.

Every requirement is computed from REAL state (never faked). ``live_allowed`` is
only ever True when *all* requirements pass AND the build's hard lock is off.
In this build the hard lock is always on (no broker executes live), so
``live_allowed`` stays False by design — but the checklist still shows exactly
what would be required, so the path to live is explicit and auditable.

Rules honoured here:
- Live trading is locked by default; paper stays the default mode.
- Nothing about live status is faked — a requirement passes only on real state.
- The Risk Manager / Safety Center are the gate; this never bypasses them.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# A live account should never be the first place a strategy is tried. Require a
# real paper track record first. 30 = the same "early-signal" boundary the
# decision journal uses, so a strategy has cleared its earliest noise.
MIN_PAPER_TRADES = 30


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_live_readiness(
    *,
    hard_locked: bool,
    closed_paper_trades: int,
    max_daily_loss_pct: float,
    max_drawdown_pct: float,
    broker_connected: bool,
    decision_logging: bool,
    emergency_stop_tested_at: Optional[str],
    min_paper_trades: int = MIN_PAPER_TRADES,
) -> dict:
    """Deterministically grade live-readiness from real state.

    Returns a checklist plus ``live_allowed`` — True only if every requirement
    passes and the build is not hard-locked.
    """
    estop_ok = bool(emergency_stop_tested_at)
    reqs = [
        {
            "key": "paper_record",
            "label": "Paper trading track record",
            "passed": closed_paper_trades >= min_paper_trades,
            "detail": f"{closed_paper_trades} closed paper trades "
                      f"(need ≥ {min_paper_trades})",
        },
        {
            "key": "emergency_stop_tested",
            "label": "Emergency stop tested",
            "passed": estop_ok,
            "detail": (f"last verified {emergency_stop_tested_at}" if estop_ok
                       else "never run — use “Test Emergency Stop”"),
        },
        {
            "key": "max_daily_loss",
            "label": "Max daily loss configured",
            "passed": max_daily_loss_pct > 0,
            "detail": (f"{max_daily_loss_pct * 100:.2f}% of equity" if max_daily_loss_pct > 0
                       else "disabled — set HUB_MAX_DAILY_LOSS"),
        },
        {
            "key": "max_drawdown",
            "label": "Max drawdown configured",
            "passed": max_drawdown_pct > 0,
            "detail": (f"{max_drawdown_pct * 100:.2f}% circuit breaker" if max_drawdown_pct > 0
                       else "disabled — set HUB_MAX_DRAWDOWN"),
        },
        {
            "key": "broker_connected",
            "label": "Live broker connection verified",
            "passed": broker_connected,
            "detail": ("a live venue is connected" if broker_connected
                       else "no live broker connected (paper only)"),
        },
        {
            "key": "decision_logging",
            "label": "Decision logging enabled",
            "passed": decision_logging,
            "detail": ("every trade is journaled" if decision_logging
                       else "decision journal not wired"),
        },
    ]
    all_pass = all(r["passed"] for r in reqs)
    live_allowed = all_pass and not hard_locked
    passed = sum(1 for r in reqs if r["passed"])
    if hard_locked:
        locked_reason = ("Live execution is locked by design in this build — no "
                         "broker places live orders. Paper mode only.")
    elif not all_pass:
        locked_reason = "One or more readiness requirements are not met."
    else:
        locked_reason = "All requirements met — live may be enabled with human approval."
    return {
        "live_allowed": live_allowed,
        "hard_locked": hard_locked,
        "locked_reason": locked_reason,
        "default_mode": "paper",
        "passed": passed,
        "total": len(reqs),
        "requirements": reqs,
    }


class SafetyState:
    """Tiny JSON-backed store for safety facts that must survive restarts —
    currently just when the emergency-stop kill switch was last verified."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data = {"emergency_stop_tested_at": None}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data.update(json.loads(self._path.read_text()))
        except Exception:  # noqa: BLE001 - corrupt file falls back to defaults
            pass

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def emergency_stop_tested_at(self) -> Optional[str]:
        return self._data.get("emergency_stop_tested_at")

    def mark_emergency_stop_tested(self) -> str:
        with self._lock:
            ts = _utcnow()
            self._data["emergency_stop_tested_at"] = ts
            self._save()
            return ts
