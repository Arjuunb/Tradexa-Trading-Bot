"""Smart Money Concepts (SMC) strategy — Phase 2 stub.

Planned logic: detect market-structure breaks (BOS/CHoCH), order blocks, and
fair-value gaps, then enter on mitigation. The interface is wired now so the
bot registry, UI, and execution path can already reference it; ``generate``
returns ``None`` until the detection logic lands.
"""
from __future__ import annotations

from typing import Optional

from bot.types import Bar, Signal
from strategies.base_strategy import HubStrategy


class SMCStrategy(HubStrategy):
    name = "smc"
    label = "SMC Bot"

    def generate(self, bar: Bar) -> Optional[Signal]:
        # TODO(phase-2): BOS/CHoCH + order-block + FVG detection.
        return None
