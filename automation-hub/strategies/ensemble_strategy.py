"""Confirmation Ensemble — trade only when proven methods agree.

Combines three independent, validated trend reads and requires at least
``min_votes`` of them to agree before entering:

    1. EMA trend   — fast EMA vs slow EMA
    2. Supertrend  — ATR trend direction
    3. Donchian    — breakout state of the N-bar channel

Agreement filters out the weakest signals, so this typically trades less often
but with a higher win rate and smoother equity than any single method — the
standard "confluence" approach real systematic bots use. ATR stop + fixed
reward:risk target (via HubStrategy).
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import ema
from bot.types import Bar, Signal, SignalType
from strategies.base_strategy import HubStrategy
from strategies.supertrend_strategy import _supertrend_dirs


class ConfirmationEnsemble(HubStrategy):
    name = "ensemble"
    label = "Confirmation Ensemble"
    supported_regimes = ()

    def __init__(self, symbol: str, *, fast: int = 12, slow: int = 26,
                 st_period: int = 10, st_mult: float = 3.0, channel: int = 30,
                 min_votes: int = 2, max_history: int = 600, **params):
        params.setdefault("rr_target", 2.5)
        super().__init__(symbol, fast=fast, slow=slow, st_period=st_period,
                         st_mult=st_mult, channel=channel, min_votes=min_votes, **params)
        self.max_history = max_history
        self._last_dir = 0
        self._donch = 0

    def generate(self, bar: Bar) -> Optional[Signal]:
        p = self.params
        if len(self.bars) > self.max_history:
            del self.bars[:-self.max_history]
        need = max(p["slow"], p["st_period"], p["channel"]) + 2
        if len(self.bars) < need:
            return None

        closes = [b.close for b in self.bars]
        v_ema = 1 if ema(closes, p["fast"])[-1] > ema(closes, p["slow"])[-1] else -1
        v_st = _supertrend_dirs(self.bars, p["st_period"], p["st_mult"])[-1]
        n = p["channel"]
        prior = self.bars[-n - 1:-1]
        if bar.close > max(b.high for b in prior):
            self._donch = 1
        elif bar.close < min(b.low for b in prior):
            self._donch = -1
        v_dc = self._donch

        reads = (v_ema, v_st, v_dc)
        longs = sum(1 for v in reads if v > 0)
        shorts = sum(1 for v in reads if v < 0)
        if longs >= p["min_votes"]:
            desired = 1
        elif shorts >= p["min_votes"]:
            desired = -1
        else:
            return None
        if desired == self._last_dir:
            return None
        self._last_dir = desired

        direction = SignalType.LONG if desired > 0 else SignalType.SHORT
        agree = longs if desired > 0 else shorts
        tag = lambda v: "+" if v > 0 else "-"  # noqa: E731
        return self._signal(bar, direction,
                            f"{agree}/3 agree {'LONG' if desired > 0 else 'SHORT'} "
                            f"(EMA{tag(v_ema)} ST{tag(v_st)} DC{tag(v_dc)})")
