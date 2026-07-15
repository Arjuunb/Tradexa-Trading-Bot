"""Trade-approval queue for SEMI-AUTO and SIGNAL trading modes.

The engine finds setups; in semi-auto the human approves each ENTRY before it
routes through the (unchanged) risk pipeline. In signal mode the engine only
records the idea as an alert and never asks for approval.

Ideas are time-sensitive: a setup is only valid near the price and moment it
fired, so this store is in-memory with a TTL — an idea not approved within
``ttl_s`` expires (and can be graded by the counterfactual tracker like any
other missed entry). Resolved ideas are kept in a bounded recent list for the
audit trail. Never persisted across restarts on purpose: approving a stale
idea from before a restart would place a trade at a price that no longer
exists.
"""
from __future__ import annotations

import itertools
import threading
from typing import Optional


class ApprovalStore:
    def __init__(self, ttl_s: int = 900, keep_recent: int = 100,
                 clock=None) -> None:
        self.ttl_s = int(ttl_s)
        self.keep_recent = int(keep_recent)
        # clock injected for tests; defaults to wall time
        import time as _t
        self._now = clock or _t.time
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._pending: dict[int, dict] = {}
        self._recent: list[dict] = []

    def create(self, payload: dict, *, decision: Optional[dict],
               verdict, mode: str) -> dict:
        """Record a new idea. ``mode`` is 'semi' (approvable) or 'signal'
        (informational only)."""
        with self._lock:
            iid = next(self._seq)
            idea = {
                "id": iid,
                "created_at": self._now(),
                "symbol": payload.get("symbol"),
                "side": payload.get("side"),
                "entry": payload.get("entry"),
                "stop": payload.get("stop"),
                "target": payload.get("target"),
                "confidence": payload.get("confidence"),
                "timeframe": payload.get("timeframe"),
                "strategy": payload.get("strategy"),
                "reason": payload.get("reason"),
                "brain_score": (decision or {}).get("score")
                if isinstance(decision, dict) else None,
                "mode": mode,
                "status": "pending" if mode == "semi" else "signal",
                "expires_at": self._now() + self.ttl_s,
                "_payload": payload,      # private: the exact pipeline payload
                "_decision_id": None,
            }
            # planned reward:risk for the approval card
            e, s, t = idea["entry"], idea["stop"], idea["target"]
            try:
                risk = abs(float(e) - float(s))
                idea["planned_rr"] = round(abs(float(t) - float(e)) / risk, 2) if risk > 0 else None
            except (TypeError, ValueError, ZeroDivisionError):
                idea["planned_rr"] = None
            if mode == "signal":
                # informational — never sits in the approvable queue
                self._push_recent({**idea, "status": "signal"})
            else:
                self._pending[iid] = idea
            return self._public(idea)

    def _public(self, idea: dict) -> dict:
        return {k: v for k, v in idea.items() if not k.startswith("_")}

    def _push_recent(self, idea: dict) -> None:
        self._recent.insert(0, self._public(idea))
        del self._recent[self.keep_recent:]

    def has_pending(self, symbol: str, side: str) -> bool:
        """True if a same-symbol, same-side idea is already awaiting approval —
        so consecutive bars of one ongoing setup don't spam the queue."""
        with self._lock:
            return any(v["symbol"] == symbol and v["side"] == side
                       for v in self._pending.values())

    def get(self, iid: int) -> Optional[dict]:
        with self._lock:
            idea = self._pending.get(iid)
            return dict(idea) if idea else None   # includes _payload for the engine

    def approve(self, iid: int) -> Optional[dict]:
        """Remove from pending and return the FULL idea (with _payload) so the
        caller routes it through the pipeline. None if unknown/expired."""
        with self._lock:
            idea = self._pending.pop(iid, None)
            if idea is None:
                return None
            idea["status"] = "approved"
            idea["resolved_at"] = self._now()
            self._push_recent(idea)
            return idea

    def reject(self, iid: int, reason: str = "") -> Optional[dict]:
        with self._lock:
            idea = self._pending.pop(iid, None)
            if idea is None:
                return None
            idea["status"] = "rejected"
            idea["reject_reason"] = reason or "manual"
            idea["resolved_at"] = self._now()
            self._push_recent(idea)
            return self._public(idea)

    def expire(self) -> list[dict]:
        """Move timed-out ideas to recent; return them so the caller can grade
        them as missed entries. Called each engine bar."""
        now = self._now()
        out: list[dict] = []
        with self._lock:
            for iid in [i for i, v in self._pending.items() if v["expires_at"] <= now]:
                idea = self._pending.pop(iid)
                idea["status"] = "expired"
                idea["resolved_at"] = now
                self._push_recent(idea)
                out.append(dict(idea))
        return out

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [self._public(v) for v in
                    sorted(self._pending.values(), key=lambda x: x["id"], reverse=True)]

    def list_recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return self._recent[:limit]

    def counts(self) -> dict:
        with self._lock:
            return {"pending": len(self._pending), "recent": len(self._recent)}
