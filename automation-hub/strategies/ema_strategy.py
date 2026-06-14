"""EMA crossover trend strategy.

LONG  when the fast EMA crosses ABOVE the slow EMA.
SHORT when the fast EMA crosses BELOW the slow EMA.
Stops/targets are ATR-based (see HubStrategy).
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import ema
from bot.types import Bar, Signal, SignalType
from strategies.base_strategy import HubStrategy


class EMAStrategy(HubStrategy):
    name = "ema"
    label = "EMA Trend Bot"

    def __init__(self, symbol: str, fast: int = 12, slow: int = 26, **params):
        if fast >= slow:
            raise ValueError("fast EMA period must be < slow EMA period")
        super().__init__(symbol, fast=fast, slow=slow, **params)

    def generate(self, bar: Bar) -> Optional[Signal]:
        slow = self.params["slow"]
        if len(self.bars) < slow + 2:
            return None
        closes = [b.close for b in self.bars]
        ef = ema(closes, self.params["fast"])
        es = ema(closes, slow)
        # Cross detection between the last two bars.
        prev_diff = ef[-2] - es[-2]
        cur_diff = ef[-1] - es[-1]
        if prev_diff <= 0 < cur_diff:
            return self._signal(bar, SignalType.LONG,
                                f"EMA{self.params['fast']} crossed above EMA{slow}")
        if prev_diff >= 0 > cur_diff:
            return self._signal(bar, SignalType.SHORT,
                                f"EMA{self.params['fast']} crossed below EMA{slow}")
        return None
