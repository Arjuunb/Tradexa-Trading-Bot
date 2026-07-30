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
from tradexa.strategy import Maturity, ParamType, Parameter, StrategyMeta

from strategies.base_strategy import atr_parameters, HubStrategy


class DonchianStrategy(HubStrategy):
    name = "donchian"
    label = "Donchian Breakout"
    supported_regimes = ()

    meta = StrategyMeta(
        key="donchian", name="Donchian Breakout", version="1.0.0",
        description="Turtle-style channel breakout with an ATR stop.",
        author="Tradexa", maturity=Maturity.BETA,
        tags=("trend", "breakout"), asset_classes=("crypto",),
        timeframes=("4h", "1d"),
        changelog=("1.0.0 - declared as a plugin. BETA rather than STABLE: "
                   "walk-forward validated on BTC/ETH 4h, but it has no live "
                   "paper track record on this platform yet.",))
    # rr_target 2.5 rather than the shared 2.0: the constructor
    # setdefaults it, and a declared default that disagrees with what
    # is built would be shown in the UI and believed.
    parameters = atr_parameters(rr_target=2.5) + (
        Parameter("channel", ParamType.INT, default=30, minimum=5, maximum=300,
                  unit="bars", tunable=True, optimise=(20, 30, 55),
                  description="Breakout lookback - the Turtle channel length."),
        Parameter("max_history", ParamType.INT, default=600, minimum=50,
                  maximum=10_000, unit="bars",
                  description="Bars retained in memory."),
    )

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
