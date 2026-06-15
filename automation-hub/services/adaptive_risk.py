"""Adaptive Risk Management (Phase 6 · capital protection).

Risk should tighten automatically as the account bleeds or volatility spikes —
the bot defends capital without waiting for a human. Maps the current drawdown
(and optional volatility ratio) to a risk *mode* and a position-size multiplier:

    drawdown < defensive          -> Normal      (1.00x)
    drawdown >= defensive (10%)   -> Defensive   (0.50x)
    drawdown >= reduced   (15%)   -> Reduced     (0.25x)
    drawdown >= pause     (20%)   -> Paused       (0x, auto-pause)
    volatility spike              -> step sizing down further

Pure/dependency-free; ``current_drawdown`` derives the live drawdown from an
equity curve.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass
class AdaptiveConfig:
    defensive_dd: float = 0.10
    reduced_dd: float = 0.15
    pause_dd: float = 0.20
    high_vol_ratio: float = 1.5     # current vol / baseline above which to de-risk


@dataclass
class RiskMode:
    name: str               # Normal | Defensive | Reduced | Paused
    size_multiplier: float
    reason: str
    paused: bool = False


def current_drawdown(equity: Sequence[float]) -> float:
    """Most-recent drawdown from the running peak, as a positive fraction."""
    if not equity:
        return 0.0
    peak = equity[0]
    for v in equity:
        peak = max(peak, v)
    last = equity[-1]
    return abs((last - peak) / peak) if peak > 0 else 0.0


class AdaptiveRiskManager:
    def __init__(self, config: Optional[AdaptiveConfig] = None):
        self.cfg = config or AdaptiveConfig()

    def evaluate(self, drawdown: float, volatility_ratio: Optional[float] = None) -> RiskMode:
        cfg = self.cfg
        dd = abs(drawdown)
        if dd >= cfg.pause_dd:
            return RiskMode("Paused", 0.0,
                            f"Drawdown {dd*100:.1f}% ≥ {cfg.pause_dd*100:.0f}% — auto-paused", True)
        if dd >= cfg.reduced_dd:
            name, mult = "Reduced", 0.25
        elif dd >= cfg.defensive_dd:
            name, mult = "Defensive", 0.5
        else:
            name, mult = "Normal", 1.0

        reason = f"Drawdown {dd*100:.1f}%"
        if volatility_ratio is not None and volatility_ratio > cfg.high_vol_ratio:
            mult *= 0.5
            reason += f"; volatility {volatility_ratio:.1f}× baseline — sizing reduced"
            if name == "Normal":
                name = "Defensive"
        return RiskMode(name, round(mult, 4), reason)

    def for_equity(self, equity: Sequence[float], volatility_ratio: Optional[float] = None) -> RiskMode:
        return self.evaluate(current_drawdown(equity), volatility_ratio)
