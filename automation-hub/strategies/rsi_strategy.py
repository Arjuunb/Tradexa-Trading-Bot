"""RSI mean-reversion scalper.

LONG  when RSI crosses up through ``oversold``.
SHORT when RSI crosses down through ``overbought``.
Stops/targets are ATR-based (see HubStrategy).
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import rsi
from bot.types import Bar, Signal, SignalType
from tradexa.strategy import Maturity, ParamType, Parameter, StrategyMeta

from strategies.base_strategy import ATR_PARAMETERS, HubStrategy


class RSIStrategy(HubStrategy):
    name = "rsi"
    label = "RSI Scalper"
    supported_regimes = ("Ranging", "Low Volatility")

    meta = StrategyMeta(
        key="rsi", name="RSI Scalper", version="1.0.0",
        description="Mean reversion: buys oversold crosses, sells overbought ones.",
        author="Tradexa", maturity=Maturity.STABLE,
        tags=("mean-reversion", "oscillator"),
        asset_classes=("crypto", "stocks"), timeframes=("5m", "15m", "1h"),
        regimes=("Ranging", "Low Volatility"),
        changelog=("1.0.0 - first version declared as a plugin; logic unchanged.",))
    parameters = ATR_PARAMETERS + (
        Parameter("period", ParamType.INT, default=14, minimum=2, maximum=100,
                  unit="bars", tunable=True, optimise=(7, 14, 21),
                  description="RSI lookback."),
        Parameter("oversold", ParamType.FLOAT, default=30.0, minimum=1.0,
                  maximum=99.0, unit="RSI", tunable=True, optimise=(20.0, 30.0),
                  description="Long when RSI crosses up through this level."),
        Parameter("overbought", ParamType.FLOAT, default=70.0, minimum=1.0,
                  maximum=99.0, unit="RSI", tunable=True, optimise=(70.0, 80.0),
                  description="Short when RSI crosses down through this level."),
    )

    @classmethod
    def validate(cls, params):
        """The same ordering rule the constructor has always raised on."""
        lo, hi = params.get("oversold"), params.get("overbought")
        if lo is not None and hi is not None and not 0 < lo < hi < 100:
            return (f"require 0 < oversold ({lo}) < overbought ({hi}) < 100",)
        return ()

    def __init__(self, symbol: str, period: int = 14, oversold: float = 30.0,
                 overbought: float = 70.0, **params):
        if not 0 < oversold < overbought < 100:
            raise ValueError("require 0 < oversold < overbought < 100")
        super().__init__(symbol, period=period, oversold=oversold,
                         overbought=overbought, **params)

    def generate(self, bar: Bar) -> Optional[Signal]:
        period = self.params["period"]
        if len(self.bars) < period + 2:
            return None
        closes = [b.close for b in self.bars]
        prev = rsi(closes[:-1], period)
        cur = rsi(closes, period)
        os_, ob = self.params["oversold"], self.params["overbought"]
        if prev <= os_ < cur:
            return self._signal(bar, SignalType.LONG,
                                f"RSI({period}) crossed up through {os_:.0f}")
        if prev >= ob > cur:
            return self._signal(bar, SignalType.SHORT,
                                f"RSI({period}) crossed down through {ob:.0f}")
        return None
