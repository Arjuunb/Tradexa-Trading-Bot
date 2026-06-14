"""Live bot runner.

Drives a bot in real time: pulls closed bars from a feed and steps the SAME
engine the backtester uses (``bot.backtester.Backtester.step``), so a strategy
behaves identically live and in backtest. Runs on a background thread; each
step syncs the bot's runtime (trades / equity / events / P&L) so the dashboard
reflects progress on refresh.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from bot.backtester import Backtester
from bot.events import EventBus
from bot.risk import RiskConfig, RiskManager

from bots.registry import build_strategy
from data.websocket import LiveFeed
from database.models import Bot, BotState

UpdateHook = Callable[[Bot], None]


def _risk(rules) -> RiskManager:
    return RiskManager(RiskConfig(
        risk_per_trade_pct=rules.risk_per_trade_pct,
        max_daily_loss_pct=rules.max_daily_loss_pct,
        max_open_positions=rules.max_open_positions,
    ))


class LiveBotRunner:
    def __init__(self, bot: Bot, feed: LiveFeed, on_update: Optional[UpdateHook] = None):
        self.bot = bot
        self.feed = feed
        self.on_update = on_update
        self.bus = EventBus()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        cfg = bot.config
        self.engine = Backtester(
            strategy=build_strategy(cfg.strategy, cfg.symbol),
            bars=[], starting_cash=cfg.starting_cash, risk=_risk(cfg.risk),
            timeframe=cfg.timeframe, bus=self.bus,
        )
        self.engine.run_kind = "live"

    # ---------------------------------------------------------------- control
    def start(self) -> None:
        self.bot.runtime.state = BotState.RUNNING
        self.bot.runtime.started_at = datetime.now(timezone.utc)
        self.bot.runtime.last_error = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def wait(self, timeout: Optional[float] = None) -> None:
        """Block until the feed is exhausted (used by finite replay feeds/tests)."""
        if self._thread:
            self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------- loop
    def _loop(self) -> None:
        try:
            for bar in self.feed.stream(self._stop):
                if self._stop.is_set():
                    break
                self.engine.bars.append(bar)
                self.engine.step(bar)
                self._sync(self.engine.current_metrics())
            result = self.engine.finalize()
            self._sync(result.metrics, state=BotState.STOPPED)
        except Exception as e:  # noqa: BLE001 - surface as bot error, keep hub alive
            self.bot.runtime.last_error = str(e)
            self._sync(self.engine.current_metrics(), state=BotState.ERROR)

    def _sync(self, metrics: dict, state: Optional[BotState] = None) -> None:
        rt = self.bot.runtime
        rt.metrics = metrics
        rt.trades = list(self.engine.trades)
        rt.equity_curve = list(self.engine.equity_curve)
        rt.events = self.bus.replay()
        rt.pnl_today = _today_pnl(rt.trades)
        if state is not None:
            rt.state = state
        if self.on_update:
            self.on_update(self.bot)


def _today_pnl(trades: list) -> float:
    by_day: dict[str, float] = {}
    for t in trades:
        xt = t.get("exit_time")
        if isinstance(xt, datetime):
            by_day[xt.date().isoformat()] = by_day.get(xt.date().isoformat(), 0.0) + t.get("pnl", 0.0)
    return by_day[sorted(by_day)[-1]] if by_day else 0.0
