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

from bot.data.indicators import atr, ema, rsi
from bot.types import Bar, Signal, SignalType
from services.regime import RegimeDetector
from strategies.base_strategy import HubStrategy

# Regime -> conviction multiplier (capital protection: stand aside in chaos).
# Out-of-sample testing across trend/range/chop regimes showed the brain earns
# in clean trends but bleeds in ranging / high-volatility noise, so those
# regimes are damped hard — the engine would rather skip a trade than take a
# coin-flip in chop.
_REGIME_FACTOR = {
    "Trending": 1.0,
    "Low Volatility": 0.85,
    "Ranging": 0.45,
    "High Volatility": 0.35,
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
                 conviction_threshold: float = 0.56, max_history: int = 600,
                 er_mode: str = "off", volume_conf: bool = False, **params):
        params.setdefault("rr_target", 3.0)  # validated reward:risk (out-of-sample sweep)
        super().__init__(symbol, fast=fast, slow=slow, trend=trend,
                         rsi_period=rsi_period, conviction_threshold=conviction_threshold,
                         **params)
        self.max_history = max_history
        self._regime = RegimeDetector()
        # experimental reads (measured via the eval harness before defaulting):
        # er_mode: "off" | "replace" (ER replaces the slope vote) | "add" (5th vote)
        # volume_conf: volume-surge conviction multiplier in [0.9, 1.1]
        self.er_mode = er_mode
        self.volume_conf = bool(volume_conf)

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

        if self.er_mode != "off" and len(closes) >= 22:
            # Kaufman efficiency ratio: |net move| / path length over 20 bars —
            # a direct trendiness read (1 = clean trend, 0 = pure chop)
            net = closes[-1] - closes[-21]
            path = sum(abs(closes[j] - closes[j - 1]) for j in range(-20, 0))
            v_er = _clip((net / path) * 2.5) if path else 0.0
        else:
            v_er = None

        if v_er is not None and self.er_mode == "replace":
            score = (self.W_TREND * v_trend + self.W_FILTER * v_filter
                     + self.W_SLOPE * v_er + self.W_RSI * v_rsi)
        elif v_er is not None and self.er_mode == "add":
            score = (0.26 * v_trend + 0.22 * v_filter + 0.16 * v_slope
                     + 0.20 * v_rsi + 0.16 * v_er)
        else:
            score = (self.W_TREND * v_trend + self.W_FILTER * v_filter
                     + self.W_SLOPE * v_slope + self.W_RSI * v_rsi)

        factor = _REGIME_FACTOR.get(regime.name, 0.45)
        conviction = abs(score) * factor
        if self.volume_conf and len(self.bars) >= 21:
            vols = [b.volume for b in self.bars[-21:-1]]
            avg = sum(vols) / len(vols) if vols else 0.0
            ratio = (self.bars[-1].volume / avg) if avg > 0 else 1.0
            conviction *= max(0.9, min(1.1, 0.9 + 0.2 * (ratio - 0.5)))

        if factor == 0.0 or conviction < p["conviction_threshold"]:
            return None  # the brain decides NOT to trade

        # Alignment gate: the medium-term trend (fast vs slow EMA) and the
        # long-trend filter (price vs long EMA) must AGREE with the trade
        # direction, and momentum must not be pushing the other way. Testing
        # showed most losers came from counter-trend entries where a hot RSI
        # vote outshouted a disagreeing trend — this removes that failure mode.
        side = 1.0 if score > 0 else -1.0
        if v_trend * side <= 0 or v_filter * side <= 0:
            return None  # never trade against the trend reads
        if v_slope * side < -0.25:
            return None  # momentum actively disagrees — wait

        direction = SignalType.LONG if score > 0 else SignalType.SHORT
        reason = self._explain(direction, ef, es, et, price, r, regime, conviction)
        signal = self._signal(bar, direction, reason)
        if signal is not None:
            signal.confidence = round(_clip(conviction, 0.0, 1.0), 3)
            signal.regime = regime.name   # lets the learning loop study losses per regime
            signal.brain_score = round(score, 3)
            # REAL decision context for the trade journal — the exact reads and
            # market values this decision was made on (never fabricated).
            a = atr(self.bars, 14)
            avg_vol = (sum(b.volume for b in self.bars[-21:-1]) / 20
                       if len(self.bars) >= 21 else 0.0)
            signal.snapshot = {
                "price": round(price, 6), "ema_fast": round(ef, 6), "ema_slow": round(es, 6),
                "ema_trend": round(et, 6), "rsi": round(r, 1), "atr": round(a, 6),
                "atr_pct": round(a / price * 100, 3) if price else 0.0,
                "regime": regime.name, "trend_direction": "up" if price > et else "down",
                "volume": round(self.bars[-1].volume, 2), "avg_volume_20": round(avg_vol, 2),
                "volatility": getattr(regime, "volatility", None),
            }
            sd = 1.0 if score > 0 else -1.0
            def _st(agree, weak=False):
                return "Passed" if agree else ("Neutral" if weak else "Failed")
            signal.checklist = [
                {"name": "HTF trend filter (price vs EMA50)", "status": _st(v_filter * sd > 0),
                 "detail": f"price {'>' if price > et else '<'} EMA50"},
                {"name": "EMA trend (fast vs slow)", "status": _st(v_trend * sd > 0),
                 "detail": f"EMA{p['fast']} {'>' if ef > es else '<'} EMA{p['slow']}"},
                {"name": "Momentum (EMA slope)", "status": _st(v_slope * sd >= 0, v_slope * sd >= -0.25),
                 "detail": f"slope vote {v_slope:+.2f}"},
                {"name": "RSI confirmation", "status": _st(v_rsi * sd > 0, True),
                 "detail": f"RSI {r:.0f}"},
                {"name": "Regime tradeable", "status": _st(factor > 0),
                 "detail": f"{regime.name} (size ×{factor:.2f})"},
                {"name": "Volume confirmation",
                 "status": ("Passed" if (self.volume_conf and self.bars[-1].volume > avg_vol)
                            else "Neutral" if self.volume_conf else "Not checked"),
                 "detail": "vs 20-bar avg" if self.volume_conf else "not part of this config"},
                {"name": "Efficiency ratio",
                 "status": ("Passed" if self.er_mode != "off" else "Not checked"),
                 "detail": "Kaufman ER" if self.er_mode != "off" else "not part of this config"},
            ]
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
