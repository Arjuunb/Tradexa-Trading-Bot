"""Market Regime Detection (Phase 4).

Classify the current market into one regime so strategies only trade where they
have an edge. A strategy declares ``supported_regimes``; if the live regime is
not supported, the trade is rejected.

Regimes: Trending, Ranging, High Volatility, Low Volatility, Extreme Volatility.

Detection (stdlib + engine indicators):
- trend strength = Kaufman efficiency ratio over the window (net move / path).
- volatility = ATR as a fraction of price.
Priority: extreme vol > trending > high vol > low vol > ranging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bot.data.indicators import atr
from bot.types import Bar


@dataclass
class RegimeConfig:
    window: int = 30
    atr_period: int = 14
    er_trending: float = 0.45
    atr_low: float = 0.004
    atr_high: float = 0.02
    atr_extreme: float = 0.04


@dataclass
class Regime:
    name: str
    trend_strength: float     # efficiency ratio 0..1
    atr_pct: float
    detail: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _efficiency_ratio(closes: Sequence[float], window: int) -> float:
    if len(closes) < window + 1:
        return 0.0
    seg = closes[-(window + 1):]
    net = abs(seg[-1] - seg[0])
    path = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
    return net / path if path > 0 else 0.0


class RegimeDetector:
    def __init__(self, config: RegimeConfig | None = None):
        self.cfg = config or RegimeConfig()

    def detect(self, bars: Sequence[Bar]) -> Regime:
        cfg = self.cfg
        closes = [b.close for b in bars]
        if len(bars) < cfg.window + 1:
            return Regime("Ranging", 0.0, 0.0, "insufficient data")
        er = _efficiency_ratio(closes, cfg.window)
        a = atr(list(bars), cfg.atr_period)
        atr_pct = a / closes[-1] if closes[-1] else 0.0

        if atr_pct >= cfg.atr_extreme:
            name = "Extreme Volatility"
        elif er >= cfg.er_trending:
            name = "Trending"
        elif atr_pct >= cfg.atr_high:
            name = "High Volatility"
        elif atr_pct <= cfg.atr_low:
            name = "Low Volatility"
        else:
            name = "Ranging"
        return Regime(name, round(er, 3), round(atr_pct, 4),
                      f"trend {er:.2f} · ATR {atr_pct*100:.2f}%")


def regime_allows(supported: Sequence[str], regime_name: str) -> bool:
    """A strategy with no declared regimes trades anywhere; otherwise the live
    regime must be in its supported set."""
    return not supported or regime_name in supported


def supported_for(strategy_key: str) -> tuple[str, ...]:
    """Look up a strategy's supported_regimes via the registry (empty = all)."""
    from bots.registry import STRATEGIES
    entry = STRATEGIES.get(strategy_key)
    if not entry:
        return ()
    return tuple(getattr(entry[0], "supported_regimes", ()) or ())


@dataclass
class RegimeVerdict:
    allowed: bool
    regime: Regime
    reason: str


class RegimeGate:
    """Reject a strategy's trade when the current regime is unsupported."""

    def __init__(self, config: RegimeConfig | None = None):
        self.detector = RegimeDetector(config)

    def check(self, strategy_key: str, bars: Sequence[Bar]) -> RegimeVerdict:
        regime = self.detector.detect(bars)
        supported = supported_for(strategy_key)
        if regime_allows(supported, regime.name):
            return RegimeVerdict(True, regime, f"{regime.name} supported")
        return RegimeVerdict(
            False, regime,
            f"{regime.name} regime not supported by {strategy_key} "
            f"(supports {', '.join(supported)})")
