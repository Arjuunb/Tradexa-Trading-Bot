"""Live broker execution — STUB (future phase, do NOT implement in Phase 1).

Phase 1 is paper-only. This interface marks the seam where a real exchange
adapter plugs in later, behind the same shape as ``PaperExecutionEngine`` so the
signal pipeline can swap implementations without changes.

Other deferred capabilities already exist elsewhere in the repo as services
(regime, adaptive risk, portfolio risk, strategy health) or in the engine
(walk-forward). The genuinely not-yet-built piece is live order routing below.
"""
from __future__ import annotations

from typing import Optional, Protocol


class ExecutionBackend(Protocol):
    """Shared shape of paper and (future) live execution."""
    def open(self, *, symbol: str, side: str, size: float, entry: float,
             stop: Optional[float], alert_id: str = ""): ...
    def close(self, *, symbol: str, exit_price: float): ...


class LiveExecutionEngine:
    """Placeholder for real-broker routing — Phase 2+."""

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            "Live execution is a future phase. Phase 1 is paper-only — use "
            "execution.paper_engine.PaperExecutionEngine.")
