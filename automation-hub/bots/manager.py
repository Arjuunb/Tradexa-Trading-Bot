"""BotManager — create, run, pause, and aggregate bots.

Phase 1 is single-process and in-memory (optionally persisted to a JSON file
via ``data.storage``). "Starting" a bot runs a paper simulation and stores the
resulting trades / equity / events on the bot's runtime, which the dashboard
and analytics read. Live execution (a background scheduler driving real orders)
is Phase 2/5 — the lifecycle and interfaces here are already shaped for it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from bots.lifecycle import assert_transition
from bots.registry import STRATEGIES
from database.models import Bot, BotConfig, BotMode, BotRuntime, BotState
from paper_trading.simulator import run_paper


class BotManager:
    def __init__(self) -> None:
        self._bots: dict[str, Bot] = {}
        self._runners: dict[str, "object"] = {}   # bot_id -> LiveBotRunner

    # -------------------------------------------------------------- CRUD
    def create(self, config: BotConfig) -> Bot:
        bot = Bot(config=config, runtime=BotRuntime())
        self._bots[bot.id] = bot
        return bot

    def get(self, bot_id: str) -> Optional[Bot]:
        return self._bots.get(bot_id)

    def list(self) -> list[Bot]:
        return list(self._bots.values())

    def delete(self, bot_id: str) -> None:
        self._bots.pop(bot_id, None)

    # ---------------------------------------------------------- lifecycle
    def start(self, bot_id: str) -> Bot:
        bot = self._require(bot_id)
        target = BotState.RUNNING if bot.config.mode == BotMode.LIVE else BotState.PAPER
        assert_transition(bot.runtime.state, target)
        try:
            res = run_paper(bot.config)
        except Exception as e:  # noqa: BLE001 — surface as bot error, don't crash hub
            bot.runtime.state = BotState.ERROR
            bot.runtime.last_error = str(e)
            return bot
        rt = bot.runtime
        rt.state = target
        rt.started_at = datetime.now(timezone.utc)
        rt.metrics = res.metrics
        rt.trades = res.trades
        rt.equity_curve = res.equity_curve
        rt.events = res.events
        rt.pnl_today = _today_pnl(res.trades)
        rt.last_error = None
        return bot

    def start_live(self, bot_id: str, feed=None) -> Bot:
        """Phase 2: stream bars through the live runner on a background thread.

        With no ``feed`` supplied, replays recent market data as if live — a
        zero-config demo of the real-time path (the runner code is identical to
        a genuine ``BrokerFeed``). Returns immediately; the runner updates the
        bot's runtime as bars arrive.
        """
        from bots.live_runner import LiveBotRunner
        from data.market_data import get_bars
        from data.websocket import ReplayFeed

        bot = self._require(bot_id)
        assert_transition(bot.runtime.state, BotState.RUNNING)
        self._stop_runner(bot_id)
        if feed is None:
            bars, _src = get_bars(bot.config.symbol, n=600, timeframe=bot.config.timeframe)
            feed = ReplayFeed(bars)
        runner = LiveBotRunner(bot, feed)
        self._runners[bot_id] = runner
        runner.start()
        return bot

    def pause(self, bot_id: str) -> Bot:
        bot = self._require(bot_id)
        assert_transition(bot.runtime.state, BotState.PAUSED)
        bot.runtime.state = BotState.PAUSED
        return bot

    def resume(self, bot_id: str) -> Bot:
        bot = self._require(bot_id)
        target = BotState.RUNNING if bot.config.mode == BotMode.LIVE else BotState.PAPER
        assert_transition(bot.runtime.state, target)
        bot.runtime.state = target
        return bot

    def stop(self, bot_id: str) -> Bot:
        bot = self._require(bot_id)
        self._stop_runner(bot_id)   # joins the live thread, which may self-stop
        if bot.runtime.state != BotState.STOPPED:
            assert_transition(bot.runtime.state, BotState.STOPPED)
            bot.runtime.state = BotState.STOPPED
        return bot

    def emergency_stop_all(self) -> int:
        n = 0
        for bot in self._bots.values():
            if bot.runtime.state in (BotState.RUNNING, BotState.PAPER, BotState.PAUSED):
                self._stop_runner(bot.id)
                bot.runtime.state = BotState.STOPPED
                n += 1
        return n

    def runner(self, bot_id: str):
        """Return the live runner for a bot (if any) — used by tests/monitoring."""
        return self._runners.get(bot_id)

    def _stop_runner(self, bot_id: str) -> None:
        runner = self._runners.pop(bot_id, None)
        if runner is not None:
            runner.stop()

    # ----------------------------------------------------------- aggregate
    def summary(self) -> dict:
        bots = self.list()
        running = [b for b in bots if b.runtime.state == BotState.RUNNING]
        paper = [b for b in bots if b.runtime.state == BotState.PAPER]
        pnl_today = sum(b.runtime.pnl_today for b in bots)
        alerts = sum(1 for b in bots if b.runtime.state == BotState.ERROR)
        return {
            "total": len(bots),
            "running": len(running),
            "paper": len(paper),
            "pnl_today": pnl_today,
            "alerts": alerts,
        }

    # ------------------------------------------------------------- helpers
    def _require(self, bot_id: str) -> Bot:
        bot = self._bots.get(bot_id)
        if bot is None:
            raise KeyError(f"no bot {bot_id!r}")
        return bot


def _today_pnl(trades: list) -> float:
    if not trades:
        return 0.0
    by_day: dict[str, float] = {}
    for t in trades:
        xt = t.get("exit_time")
        if isinstance(xt, datetime):
            by_day.setdefault(xt.date().isoformat(), 0.0)
            by_day[xt.date().isoformat()] += t.get("pnl", 0.0)
    if not by_day:
        return 0.0
    return by_day[sorted(by_day)[-1]]


def is_ready_strategy(key: str) -> bool:
    return STRATEGIES.get(key, (None, None, False))[2]
