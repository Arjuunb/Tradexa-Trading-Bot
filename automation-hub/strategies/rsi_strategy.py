"""RSI mean-reversion scalper.

LONG  when RSI crosses up through ``oversold``.
SHORT when RSI crosses down through ``overbought``.
Stops/targets are ATR-based (see HubStrategy).
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import rsi
from bot.types import Bar, Signal, SignalType
from strategies.base_strategy import HubStrategy


class RSIStrategy(HubStrategy):
    name = "rsi"
    label = "RSI Scalper"
    supported_regimes = ("Ranging", "Low Volatility")

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
