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
    def __init__(self, store=None) -> None:
        self._bots: dict[str, Bot] = {}
        self._runners: dict[str, "object"] = {}   # bot_id -> LiveBotRunner
        self._store = store                        # Phase 6: optional SqliteStore
        if store is not None:
            for bot in store.load_all():
                self._bots[bot.id] = bot

    def _persist(self, bot: Bot) -> None:
        if self._store is not None:
            self._store.save(bot)

    # -------------------------------------------------------------- CRUD
    def create(self, config: BotConfig) -> Bot:
        bot = Bot(config=config, runtime=BotRuntime())
        self._bots[bot.id] = bot
        self._persist(bot)
        return bot

    def get(self, bot_id: str) -> Optional[Bot]:
        return self._bots.get(bot_id)

    def list(self) -> list[Bot]:
        return list(self._bots.values())

    def delete(self, bot_id: str) -> None:
        self._stop_runner(bot_id)
        self._bots.pop(bot_id, None)
        if self._store is not None:
            self._store.delete(bot_id)

    def update(self, bot_id: str, **fields) -> Bot:
        """Edit an existing bot's config in place (Phase 9). Persists the change.

        Accepts: name, symbol, timeframe, strategy, exchange, starting_cash,
        and a RiskRules instance under ``risk``. Unknown keys are ignored.
        """
        bot = self._require(bot_id)
        cfg = bot.config
        for key in ("name", "symbol", "timeframe", "strategy", "exchange",
                    "starting_cash", "risk", "mode"):
            if key in fields and fields[key] is not None:
                setattr(cfg, key, fields[key])
        self._persist(bot)
        return bot

    def backtest(self, bot_id: str):
        """Run an ad-hoc backtest of a bot's config WITHOUT touching its runtime
        or state. Returns a paper_trading.simulator.PaperResult."""
        bot = self._require(bot_id)
        return run_paper(bot.config)

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
        # Informational: would a live circuit breaker have tripped on this run?
        import risk.guards as guards
        trip = guards.evaluate(
            equity_curve=rt.equity_curve, trades=rt.trades, pnl_today=rt.pnl_today,
            starting_equity=bot.config.starting_cash, rules=bot.config.risk,
        )
        rt.halt_reason = trip.reason if trip else None
        self._persist(bot)
        return bot

    def start_live(self, bot_id: str, feed=None, real_broker=None,
                   alerts: bool = False, dry_run: bool = True, event_sink=None) -> Bot:
        """Stream bars through the live runner on a background thread.

        With no ``feed`` supplied, replays recent market data as if live — a
        zero-config demo of the real-time path (the runner code is identical to
        a genuine ``BrokerFeed``). Pass ``real_broker`` to mirror orders to a
        live venue (Phase 5), ``alerts=True`` to fire notifications, and
        ``event_sink`` to stream events to the live dashboard (Phase 8). Returns
        immediately; the runner updates the bot's runtime as bars arrive.
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
        runner = LiveBotRunner(bot, feed, real_broker=real_broker,
                               alerts=alerts, dry_run=dry_run, event_sink=event_sink)
        self._runners[bot_id] = runner
        runner.start()
        self._persist(bot)
        return bot

    def live_bots(self) -> list[Bot]:
        """Bots that currently have an active live runner (multi-bot supervision)."""
        return [b for bid, b in self._bots.items() if bid in self._runners]

    # --------------------------------------------------- portfolio risk (P5)
    def portfolio_snapshot(self, equity: float):
        """Account-wide exposure across all active bots."""
        from services.portfolio_risk import PortfolioRiskEngine, positions_from_bots
        eng = getattr(self, "_portfolio", None) or PortfolioRiskEngine()
        self._portfolio = eng
        return eng.snapshot(equity, positions_from_bots(self.list(), equity))

    def check_portfolio(self, equity: float, candidate):
        """Would opening ``candidate`` breach a portfolio-level limit?"""
        from services.portfolio_risk import PortfolioRiskEngine, positions_from_bots
        eng = getattr(self, "_portfolio", None) or PortfolioRiskEngine()
        self._portfolio = eng
        return eng.check_new(equity, positions_from_bots(self.list(), equity), candidate)

    def pause(self, bot_id: str) -> Bot:
        bot = self._require(bot_id)
        assert_transition(bot.runtime.state, BotState.PAUSED)
        bot.runtime.state = BotState.PAUSED
        self._persist(bot)
        return bot

    def resume(self, bot_id: str) -> Bot:
        bot = self._require(bot_id)
        target = BotState.RUNNING if bot.config.mode == BotMode.LIVE else BotState.PAPER
        assert_transition(bot.runtime.state, target)
        bot.runtime.state = target
        self._persist(bot)
        return bot

    def stop(self, bot_id: str) -> Bot:
        bot = self._require(bot_id)
        self._stop_runner(bot_id)   # joins the live thread, which may self-stop
        if bot.runtime.state != BotState.STOPPED:
            assert_transition(bot.runtime.state, BotState.STOPPED)
            bot.runtime.state = BotState.STOPPED
        self._persist(bot)
        return bot

    def emergency_stop_all(self) -> int:
        n = 0
        for bot in self._bots.values():
            if bot.runtime.state in (BotState.RUNNING, BotState.PAPER, BotState.PAUSED):
                self._stop_runner(bot.id)
                bot.runtime.state = BotState.STOPPED
                self._persist(bot)
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
