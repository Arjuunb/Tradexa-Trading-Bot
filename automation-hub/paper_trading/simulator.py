"""Paper-trading simulator.

Phase 1: a paper run == an event-driven backtest of the bot's strategy over
recent market data, using the bot's own risk rules. It produces the same
artifacts a live run would (trades, equity curve, event log), so the dashboard
and analytics work identically for paper and (later) live bots.
"""
from __future__ import annotations

from dataclasses import dataclass

import backtesting.engine as engine
from bots.registry import build_strategy
from data.market_data import get_bars
from database.models import BotConfig


@dataclass
class PaperResult:
    metrics: dict
    trades: list
    equity_curve: list
    events: list
    source: str


def run_paper(config: BotConfig, bars_n: int = 1500) -> PaperResult:
    bars, source = get_bars(config.symbol, n=bars_n, timeframe=config.timeframe)
    strategy = build_strategy(config.strategy, symbol=config.symbol)
    out = engine.run(strategy, bars, rules=config.risk,
                     starting_cash=config.starting_cash, timeframe=config.timeframe)
    r = out.result
    return PaperResult(
        metrics=r.metrics, trades=r.trades, equity_curve=r.equity_curve,
        events=out.events, source=source,
    )
