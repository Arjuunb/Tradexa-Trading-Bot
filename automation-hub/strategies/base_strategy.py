"""Base class for Automation Hub strategies.

Sits between ``tradexa.strategy.BaseStrategy`` — the plugin contract: metadata,
versioning, declared parameters, validation, optimisation, generated docs — and
the concrete strategies. Adds what every hub strategy shares:

- display metadata (``label``) for the UI,
- an ATR-based stop/target helper so every strategy sizes risk consistently,
- the three ATR parameters, declared once here instead of in each subclass.

``BaseStrategy`` itself subclasses ``bot.strategies.base.Strategy``, so the
bar-feeding contract this has always relied on (``on_bar`` -> ``generate``) is
the same class reached through one more link. Every existing strategy therefore
inherits the plugin contract without being rewritten, and the backtester keeps
receiving exactly the object it always has.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from bot.data.indicators import atr
from bot.types import Bar, Signal, SignalType

from tradexa.strategy import (
    BaseStrategy, Maturity, ParamType, Parameter, StrategyMeta,
)

#: The ATR bracket knobs, shared by every hub strategy. Declared once: a
#: subclass appends its own to these rather than restating them, so changing a
#: risk default happens in one place instead of eight.
ATR_PARAMETERS: tuple[Parameter, ...] = (
    Parameter("atr_period", ParamType.INT, default=14, minimum=2, maximum=200,
              unit="bars",
              description="Lookback for the ATR that places the stop."),
    Parameter("atr_mult", ParamType.FLOAT, default=1.5, minimum=0.1, maximum=10.0,
              step=0.1, unit="×ATR", tunable=True, optimise=(1.0, 1.5, 2.0, 2.5),
              description="Stop distance as a multiple of ATR."),
    Parameter("rr_target", ParamType.FLOAT, default=2.0, minimum=0.1, maximum=20.0,
              step=0.1, unit="R", tunable=True, optimise=(1.5, 2.0, 3.0),
              description="Take-profit distance as a multiple of the risk taken."),
)


def atr_parameters(*, rr_target: float = 2.0, atr_mult: float = 1.5,
                   atr_period: int = 14) -> tuple[Parameter, ...]:
    """``ATR_PARAMETERS`` with the risk defaults a given strategy actually uses.

    Several strategies call ``params.setdefault("rr_target", 2.5)`` in their
    constructor. Inheriting the shared declaration unchanged would then have the
    UI show 2.0 while the bot ran 2.5 — a declaration that disagrees with the
    constructor is worse than no declaration, because it is believed. Found by
    `test_the_declared_defaults_match_what_construction_produces`, which exists
    for exactly this.
    """
    overrides = {"rr_target": rr_target, "atr_mult": atr_mult,
                 "atr_period": atr_period}
    return tuple(replace(p, default=overrides[p.name]) for p in ATR_PARAMETERS)


class HubStrategy(BaseStrategy):
    label: str = "Base Strategy"
    supported_regimes: tuple[str, ...] = ()   # P4: empty = trade in any regime

    #: Replaced by every concrete strategy. Present so an incomplete plugin
    #: fails the registry's explicit check with a readable reason rather than an
    #: AttributeError somewhere inside a UI template.
    meta = StrategyMeta(key="hub-base", name="Hub Base Strategy",
                        maturity=Maturity.EXPERIMENTAL)
    parameters = ATR_PARAMETERS

    def __init__(self, symbol: str, atr_period: int = 14, atr_mult: float = 1.5,
                 rr_target: float = 2.0, **params):
        super().__init__(symbol, atr_period=atr_period, atr_mult=atr_mult,
                         rr_target=rr_target, **params)

    def _bracket(self, entry: float, direction: SignalType) -> Optional[tuple[float, float, float]]:
        """Return (stop, take_profit, risk) using ATR, or None if not enough data."""
        a = atr(self.bars, self.params["atr_period"])
        if a <= 0:
            return None
        risk = self.params["atr_mult"] * a
        rr = self.params["rr_target"]
        if direction == SignalType.LONG:
            return entry - risk, entry + rr * risk, risk
        return entry + risk, entry - rr * risk, risk

    def _signal(self, bar: Bar, direction: SignalType, reason: str) -> Optional[Signal]:
        br = self._bracket(bar.close, direction)
        if br is None:
            return None
        stop, tp, _ = br
        return Signal(
            timestamp=bar.timestamp, symbol=self.symbol, type=direction,
            entry=bar.close, stop_loss=stop, take_profit=tp, reason=reason,
        )
