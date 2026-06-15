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
    def __init__(self, bot: Bot, feed: LiveFeed, on_update: Optional[UpdateHook] = None,
                 real_broker=None, alerts: bool = False, dry_run: bool = True,
                 event_sink=None, connected_fn=None, quote_fn=None, data_age_fn=None):
        self.bot = bot
        self.feed = feed
        self.on_update = on_update
        self.bus = EventBus()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # P4 health telemetry.
        self._started_at: Optional[datetime] = None
        self._bars = 0
        self._errors = 0
        self._last_bar_ts: Optional[datetime] = None
        self._last_scan: Optional[datetime] = None
        self._last_trade_ts: Optional[datetime] = None
        self._connected_fn = connected_fn
        self._data_age_fn = data_age_fn
        cfg = bot.config
        # Phase 8: subscribe the live-dashboard sink BEFORE the engine runs, so
        # no events are missed if the worker thread races ahead of start().
        if event_sink is not None:
            self.bus.subscribe(event_sink)
        self.engine = Backtester(
            strategy=build_strategy(cfg.strategy, cfg.symbol),
            bars=[], starting_cash=cfg.starting_cash, risk=_risk(cfg.risk),
            timeframe=cfg.timeframe, bus=self.bus,
        )
        self.engine.run_kind = "live"

        # Phase 2: decision log — captures why each signal did/didn't trade.
        from services.decision_log import DecisionLog
        self.decision_log = DecisionLog(strategy=cfg.strategy)
        self.decision_log.attach(self.bus)

        # Phase 6: adaptive risk — tighten sizing as drawdown grows.
        from services.adaptive_risk import AdaptiveRiskManager
        self._adaptive = AdaptiveRiskManager()

        # Phase 3: rolling strategy-health monitor.
        from services.strategy_health import StrategyHealthMonitor
        self._health_monitor = StrategyHealthMonitor()

        # Phase 5: real order routing + alerts (event-driven, opt-in).
        self.router = None
        if real_broker is not None:
            from execution.execution_engine import ExecutionEngine
            from execution.live_bridge import RealOrderRouter
            self.router = RealOrderRouter(
                ExecutionEngine(real_broker, dry_run=dry_run),
                connected_fn=connected_fn, quote_fn=quote_fn, data_age_fn=data_age_fn,
            )
            self.router.attach(self.bus)
        if alerts:
            from notifications import AlertDispatcher
            AlertDispatcher(cfg.name).attach(self.bus)

    # ---------------------------------------------------------------- control
    def start(self) -> None:
        self._started_at = datetime.now(timezone.utc)
        self.bot.runtime.state = BotState.RUNNING
        self.bot.runtime.started_at = self._started_at
        self.bot.runtime.last_error = None
        self.bot.runtime.halt_reason = None
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
                # P4 health telemetry.
                self._bars += 1
                self._last_bar_ts = bar.timestamp
                self._last_scan = datetime.now(timezone.utc)
                if self.engine.trades:
                    self._last_trade_ts = self.engine.trades[-1].get("exit_time")
                self._sync(self.engine.current_metrics())
                if self._bars % 20 == 0:
                    self.bus.publish(self._health_snapshot())
                trip = self._check_guards()
                if trip is not None:
                    self._halt(trip)
                    return
            result = self.engine.finalize()
            self._sync(result.metrics, state=BotState.STOPPED)
        except Exception as e:  # noqa: BLE001 - surface as bot error, keep hub alive
            self._errors += 1
            self.bot.runtime.last_error = str(e)
            self._sync(self.engine.current_metrics(), state=BotState.ERROR)

    # --------------------------------------------------------- circuit breaker
    def _check_guards(self):
        import risk.guards as guards
        return guards.evaluate(
            equity_curve=self.engine.equity_curve,
            trades=self.engine.trades,
            pnl_today=self.bot.runtime.pnl_today,
            starting_equity=self.engine.starting_cash,
            rules=self.bot.config.risk,
        )

    def _halt(self, trip) -> None:
        """A risk breaker tripped: close out, mark STOPPED, alert."""
        result = self.engine.finalize()
        self.bot.runtime.halt_reason = trip.reason
        self._sync(result.metrics, state=BotState.STOPPED)
        try:
            from notifications import notify
            notify(f"🛑 {self.bot.config.name} HALTED — {trip.reason}",
                   subject="Automation Hub risk halt")
        except Exception:  # noqa: BLE001 - alerting must never crash the runner
            pass

    def _sync(self, metrics: dict, state: Optional[BotState] = None) -> None:
        rt = self.bot.runtime
        rt.metrics = metrics
        rt.trades = list(self.engine.trades)
        rt.equity_curve = list(self.engine.equity_curve)
        rt.events = self.bus.replay()
        rt.pnl_today = _today_pnl(rt.trades)
        if state is not None:
            rt.state = state
        rt.health = self._health_snapshot(state)
        rt.decisions = self.decision_log.recent(50)
        mode = self._adaptive.for_equity([v for _, v in self.engine.equity_curve])
        rt.risk_mode = {"name": mode.name, "size_multiplier": mode.size_multiplier,
                        "reason": mode.reason, "paused": mode.paused}
        rt.strategy_health = self._health_monitor.evaluate(self.engine.trades).to_dict()
        if self.on_update:
            self.on_update(self.bot)

    # ----------------------------------------------------------- P4 health
    def _health_snapshot(self, state: Optional[BotState] = None) -> dict:
        now = datetime.now(timezone.utc)
        uptime = (now - self._started_at).total_seconds() if self._started_at else 0.0
        connected = self._connected_fn() if self._connected_fn else None
        data_age = self._data_age_fn() if self._data_age_fn else None
        return {
            "type": "health",
            "status": (state or self.bot.runtime.state).value,
            "bars": self._bars,
            "errors": self._errors,
            "uptime_s": round(uptime, 1),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "last_bar_ts": self._last_bar_ts.isoformat() if self._last_bar_ts else None,
            "last_trade_ts": self._last_trade_ts.isoformat() if isinstance(self._last_trade_ts, datetime) else None,
            "connected": connected,
            "exchange": "Connected" if connected else ("Disconnected" if connected is False else "Unknown"),
            "data_feed": ("Live" if (data_age is not None and data_age <= 30) else
                          "Delayed" if data_age is not None else "Unknown"),
        }


def _today_pnl(trades: list) -> float:
    by_day: dict[str, float] = {}
    for t in trades:
        xt = t.get("exit_time")
        if isinstance(xt, datetime):
            by_day[xt.date().isoformat()] = by_day.get(xt.date().isoformat(), 0.0) + t.get("pnl", 0.0)
    return by_day[sorted(by_day)[-1]] if by_day else 0.0
