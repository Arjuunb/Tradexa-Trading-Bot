"""Emergency trading controls (Phase 1, paper-mode) — Pause / Stop / Resume.

A process-wide switch the signal pipeline consults before executing. ``paused``
blocks new entries (a soft halt); ``stopped`` is a hard halt. ``resume`` clears
both. Kept tiny and explicit so a human is always one call away from halting.
"""
from __future__ import annotations


class TradingControl:
    def __init__(self) -> None:
        self.paused = False
        self.stopped = False

    @property
    def state(self) -> str:
        if self.stopped:
            return "Stopped"
        if self.paused:
            return "Paused"
        return "Active"

    def trading_allowed(self) -> bool:
        return not (self.paused or self.stopped)

    def pause_all(self) -> None:
        self.paused = True

    def stop_all(self) -> None:
        self.stopped = True

    def resume(self) -> None:
        self.paused = False
        self.stopped = False
