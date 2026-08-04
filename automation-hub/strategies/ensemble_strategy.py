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
from tradexa.strategy import Maturity, ParamType, Parameter, StrategyMeta

from strategies.base_strategy import atr_parameters, HubStrategy
from strategies.supertrend_strategy import _supertrend_dirs


class ConfirmationEnsemble(HubStrategy):
    name = "ensemble"
    label = "Confirmation Ensemble"
    supported_regimes = ()

    meta = StrategyMeta(
        key="ensemble", name="Confirmation Ensemble", version="1.0.0",
        description="Trades only when several independent trend reads agree.",
        author="Tradexa", maturity=Maturity.BETA,
        tags=("ensemble", "trend", "confirmation"), asset_classes=("crypto",),
        timeframes=("1h", "4h"),
        changelog=("1.0.0 - declared as a plugin. BETA: no live paper track "
                   "record on this platform yet.",))
    # rr_target 2.5 rather than the shared 2.0: the constructor
    # setdefaults it, and a declared default that disagrees with what
    # is built would be shown in the UI and believed.
    parameters = atr_parameters(rr_target=2.5) + (
        Parameter("fast", ParamType.INT, default=12, minimum=2, maximum=200,
                  unit="bars", description="Fast EMA period for the trend vote."),
        Parameter("slow", ParamType.INT, default=26, minimum=3, maximum=400,
                  unit="bars", description="Slow EMA period for the trend vote."),
        Parameter("st_period", ParamType.INT, default=10, minimum=2, maximum=100,
                  unit="bars", description="Supertrend ATR period."),
        Parameter("st_mult", ParamType.FLOAT, default=3.0, minimum=0.5,
                  maximum=15.0, step=0.5, unit="xATR",
                  description="Supertrend band width."),
        Parameter("channel", ParamType.INT, default=30, minimum=5, maximum=300,
                  unit="bars", description="Donchian channel length."),
        Parameter("min_votes", ParamType.INT, default=2, minimum=1, maximum=3,
                  unit="votes", tunable=True, optimise=(2, 3),
                  description="How many of the three reads must agree."),
        Parameter("max_history", ParamType.INT, default=600, minimum=50,
                  maximum=10_000, unit="bars",
                  description="Bars retained in memory."),
    )

    @classmethod
    def validate(cls, params):
        """min_votes above the number of voters can never be satisfied - the
        strategy would silently never trade, which looks identical to a market
        with no setups."""
        votes = params.get("min_votes")
        if votes is not None and votes > 3:
            return ("min_votes is %s but there are only 3 reads to agree" % votes,)
        fast, slow = params.get("fast"), params.get("slow")
        if fast is not None and slow is not None and fast >= slow:
            return ("fast EMA period (%s) must be below the slow one (%s)" % (fast, slow),)
        return ()

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
