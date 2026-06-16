"""DecisionBrain — a multi-signal decision engine (not a single indicator).

Instead of one crossover, the brain weighs several independent reads of the same
data and only acts when they agree enough to clear a conviction threshold:

    trend      — fast vs slow EMA (direction of the medium-term trend)
    trend filter — price vs a long EMA (don't fight the bigger trend)
    momentum   — slope of the fast EMA (is the move accelerating?)
    RSI        — momentum oscillator (confirm strength, fade extremes)
    regime     — Trending / Ranging / Volatile (size down or stand aside)

Each produces a vote in [-1, +1]; a weighted sum gives a score in [-1, +1].
``confidence = |score|`` (after regime adjustment). Below the threshold the brain
returns ``None`` — i.e. it *decides not to trade*. Above it, it emits a Signal
whose ``confidence`` scales the risk taken and whose ``reason`` lists exactly
which reads agreed, so every decision is explainable.
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import ema, rsi
from bot.types import Bar, Signal, SignalType
from services.regime import RegimeDetector
from strategies.base_strategy import HubStrategy

# Regime -> conviction multiplier (capital protection: stand aside in chaos).
_REGIME_FACTOR = {
    "Trending": 1.0,
    "Low Volatility": 0.9,
    "Ranging": 0.8,
    "High Volatility": 0.6,
    "Extreme Volatility": 0.0,   # do not trade
}


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class DecisionBrain(HubStrategy):
    name = "brain"
    label = "Decision Brain"
    supported_regimes = ()  # handles regime internally

    # weights for the four reads (sum to 1.0)
    W_TREND, W_FILTER, W_SLOPE, W_RSI = 0.30, 0.25, 0.20, 0.25

    def __init__(self, symbol: str, *, fast: int = 12, slow: int = 26,
                 trend: int = 50, rsi_period: int = 14,
                 conviction_threshold: float = 0.35, max_history: int = 600, **params):
        super().__init__(symbol, fast=fast, slow=slow, trend=trend,
                         rsi_period=rsi_period, conviction_threshold=conviction_threshold,
                         **params)
        self.max_history = max_history
        self._regime = RegimeDetector()

    def generate(self, bar: Bar) -> Optional[Signal]:
        p = self.params
        # Keep memory bounded for a 24/7 engine (rolling window of bars).
        if len(self.bars) > self.max_history:
            del self.bars[:-self.max_history]

        closes = [b.close for b in self.bars]
        need = max(p["slow"], p["trend"], p["rsi_period"]) + 4
        if len(closes) < need:
            return None

        ef_series = ema(closes, p["fast"])
        es = ema(closes, p["slow"])[-1]
        et = ema(closes, p["trend"])[-1]
        ef = ef_series[-1]
        ef_prev = ef_series[-4]
        r = rsi(closes, p["rsi_period"])
        price = closes[-1]
        regime = self._regime.detect(self.bars)

        # --- four independent reads, each a vote in [-1, +1] ---
        v_trend = _clip((ef - es) / (es * 0.004)) if es else 0.0
        v_filter = 1.0 if price > et else -1.0
        v_slope = _clip((ef - ef_prev) / (ef_prev * 0.003)) if ef_prev else 0.0
        v_rsi = _clip((r - 50.0) / 20.0)
        # fade overbought/oversold extremes (mean-reversion guard)
        if r > 78:
            v_rsi = min(v_rsi, 0.2)
        elif r < 22:
            v_rsi = max(v_rsi, -0.2)

        score = (self.W_TREND * v_trend + self.W_FILTER * v_filter
                 + self.W_SLOPE * v_slope + self.W_RSI * v_rsi)

        factor = _REGIME_FACTOR.get(regime.name, 0.8)
        conviction = abs(score) * factor

        if factor == 0.0 or conviction < p["conviction_threshold"]:
            return None  # the brain decides NOT to trade

        direction = SignalType.LONG if score > 0 else SignalType.SHORT
        reason = self._explain(direction, ef, es, et, price, r, regime, conviction)
        signal = self._signal(bar, direction, reason)
        if signal is not None:
            signal.confidence = round(_clip(conviction, 0.0, 1.0), 3)
        return signal

    def _explain(self, direction, ef, es, et, price, r, regime, conviction) -> str:
        d = "LONG" if direction == SignalType.LONG else "SHORT"
        reads = [
            f"EMA{self.params['fast']}{'>' if ef > es else '<'}EMA{self.params['slow']}",
            f"price{'>' if price > et else '<'}EMA{self.params['trend']}",
            f"RSI {r:.0f}",
            f"regime {regime.name}",
        ]
        return f"{d} conviction {conviction:.0%} — " + "; ".join(reads)
