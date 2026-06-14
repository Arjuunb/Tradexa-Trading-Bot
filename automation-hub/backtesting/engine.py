"""Backtesting engine adapter.

Thin wrapper over the existing, tested ``bot.backtester.Backtester`` so the Hub
has a single entry point and the engine internals stay in one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bot.backtester import Backtester
from bot.events import EventBus
from bot.risk import RiskConfig, RiskManager
from bot.strategies.base import Strategy
from bot.types import Bar

from database.models import RiskRules


@dataclass
class RunOutput:
    result: object            # bot.backtester.BacktestResult
    events: list
    risk: RiskManager


def _risk_manager(rules: RiskRules) -> RiskManager:
    return RiskManager(RiskConfig(
        risk_per_trade_pct=rules.risk_per_trade_pct,
        max_daily_loss_pct=rules.max_daily_loss_pct,
        max_open_positions=rules.max_open_positions,
    ))


def run(strategy: Strategy, bars: Sequence[Bar], *, rules: RiskRules,
        starting_cash: float = 10_000.0, timeframe: str = "1h") -> RunOutput:
    bus = EventBus()
    risk = _risk_manager(rules)
    bt = Backtester(strategy, list(bars), starting_cash=starting_cash,
                    risk=risk, timeframe=timeframe, bus=bus)
    result = bt.run()
    return RunOutput(result=result, events=bus.replay(), risk=risk)
