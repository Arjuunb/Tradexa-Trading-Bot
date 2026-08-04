"""EMA crossover trend strategy.

LONG  when the fast EMA crosses ABOVE the slow EMA.
SHORT when the fast EMA crosses BELOW the slow EMA.
Stops/targets are ATR-based (see HubStrategy).
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import ema
from bot.types import Bar, Signal, SignalType
from tradexa.strategy import Maturity, ParamType, Parameter, StrategyMeta

from strategies.base_strategy import ATR_PARAMETERS, HubStrategy


class EMAStrategy(HubStrategy):
    name = "ema"
    label = "EMA Trend Bot"
    supported_regimes = ("Trending",)

    meta = StrategyMeta(
        key="ema", name="EMA Trend Bot", version="1.0.0",
        description="Fast/slow EMA crossover with an ATR bracket.",
        author="Tradexa", maturity=Maturity.STABLE,
        tags=("trend", "crossover"), asset_classes=("crypto", "stocks"),
        timeframes=("15m", "1h", "4h"), regimes=("Trending",),
        changelog=("1.0.0 - first version declared as a plugin; logic unchanged "
                   "since it was a hand-maintained registry entry.",))
    parameters = ATR_PARAMETERS + (
        Parameter("fast", ParamType.INT, default=12, minimum=2, maximum=200,
                  unit="bars", tunable=True, optimise=(8, 12, 21),
                  description="Fast EMA period. Must be below `slow`."),
        Parameter("slow", ParamType.INT, default=26, minimum=3, maximum=400,
                  unit="bars", tunable=True, optimise=(26, 50, 100),
                  description="Slow EMA period."),
    )

    @classmethod
    def validate(cls, params):
        """The rule the constructor has always enforced, declared where the API,
        the UI and the optimiser can all see it. An optimiser sweeping fast and
        slow independently would otherwise spend a third of its candidates on
        combinations that raise."""
        fast, slow = params.get("fast"), params.get("slow")
        if fast is not None and slow is not None and fast >= slow:
            return (f"fast EMA period ({fast}) must be below the slow one ({slow})",)
        return ()

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
