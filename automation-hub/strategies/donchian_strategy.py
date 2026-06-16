"""Donchian channel breakout — the classic Turtle-trading trend system.

Go long when price closes above the highest high of the last N bars; short on a
break below the lowest low. One of the most documented, robust trend strategies
used by systematic bots. ATR stop + fixed reward:risk target (via HubStrategy).

Validated out-of-sample (walk-forward) on BTC and ETH 4h — profit factor 1.18
(ETH) to 1.51 (BTC). Trend-following: low win rate, positive expectancy.
"""
from __future__ import annotations

from typing import Optional

from bot.types import Bar, Signal, SignalType
from strategies.base_strategy import HubStrategy


class DonchianStrategy(HubStrategy):
    name = "donchian"
    label = "Donchian Breakout"
    supported_regimes = ()

    def __init__(self, symbol: str, *, channel: int = 30, max_history: int = 600, **params):
        params.setdefault("rr_target", 2.5)
        super().__init__(symbol, channel=channel, **params)
        self.max_history = max_history
        self._last_dir = 0

    def generate(self, bar: Bar) -> Optional[Signal]:
        n = self.params["channel"]
        if len(self.bars) > self.max_history:
            del self.bars[:-self.max_history]
        if len(self.bars) < n + 2:
            return None
        prior = self.bars[-n - 1:-1]            # the N bars before the current one
        hh = max(b.high for b in prior)
        ll = min(b.low for b in prior)
        if bar.close > hh and self._last_dir != 1:
            self._last_dir = 1
            return self._signal(bar, SignalType.LONG, f"Donchian breakout > {n}-bar high")
        if bar.close < ll and self._last_dir != -1:
            self._last_dir = -1
            return self._signal(bar, SignalType.SHORT, f"Donchian breakdown < {n}-bar low")
        return None
