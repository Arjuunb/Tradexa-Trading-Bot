"""Autonomous strategy engine (real logic, paper execution).

This is the "trading bot brain": it runs a real strategy over real market data
and routes every signal through the SAME Phase 1 pipeline a TradingView webhook
uses (controls -> dedup -> risk -> sizing -> exposure -> paper execution ->
ledger). Nothing here is decorative — positions, P&L, stops/targets and the
decision log are all produced by live strategy + risk logic and persisted to
the ledger (the source of truth the dashboard reads).

Flow per bar (on a background thread, replayed at ``interval`` seconds):
    1. mark open positions -> close on stop-loss / take-profit hit
    2. feed the bar to the strategy -> on a Signal, open via the risk pipeline

Data is local (bundled samples or deterministic synthetic), so it runs with no
exchange keys. Opposite-direction crossovers also flatten via the pipeline's
close path, so the engine and webhooks share identical execution semantics.
"""
from __future__ import annotations

import itertools
import threading
import time
from typing import Callable, Optional

from bot.types import Signal, SignalType
from data.ledger import Ledger
from execution.paper_engine import PaperExecutionEngine
from services.signal_pipeline import SignalPipeline


def _default_strategy_factory(symbol: str):
    # The DecisionBrain is the default: a multi-signal, regime-aware decision
    # engine (imported lazily so the module has no hard strategy dependency).
    from strategies.brain_strategy import DecisionBrain
    return DecisionBrain(symbol)


def _default_fetcher(symbol: str, timeframe: str, limit: int):
    """Return (bars, source). Real candles when HUB_USE_LIVE_DATA=1, else local."""
    from data.market_data import get_bars
    return get_bars(symbol, n=limit, timeframe=timeframe)


class AutoStrategyEngine:
    def __init__(
        self,
        pipeline: SignalPipeline,
        paper: PaperExecutionEngine,
        ledger: Ledger,
        *,
        symbols: Optional[list[str]] = None,
        timeframe: str = "1h",
        interval: float = 2.0,
        warmup: int = 150,
        live_bars: int = 250,
        strategy_factory: Callable[[str], object] = _default_strategy_factory,
        live: bool = False,
        live_poll_s: float = 60.0,
        fetcher: Optional[Callable[[str, str, int], tuple]] = None,
        trade_manager=None,
    ):
        self.pipeline = pipeline
        self.paper = paper
        self.ledger = ledger
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        self.timeframe = timeframe
        self.interval = interval
        self.warmup = warmup
        self.live_bars = live_bars
        self.strategy_factory = strategy_factory
        # Live forward mode: poll for NEW closed candles and trade only those
        # (vs. replaying a historical batch). Real forward paper-trading.
        self.live = live
        self.live_poll_s = live_poll_s
        self._fetcher = fetcher or _default_fetcher
        # Human-readable label for the active strategy (shown on the Bots page).
        try:
            probe = strategy_factory(self.symbols[0]) if self.symbols else None
            self.strategy_label = getattr(probe, "label", None) or "Strategy"
        except Exception:  # noqa: BLE001 — never let label probing break construction
            self.strategy_label = "Strategy"

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.running = False
        self.started_at: Optional[str] = None
        self.stats = {"bars": 0, "signals": 0, "trades": 0, "rejections": 0}
        self._targets: dict[str, float] = {}
        # Mid-trade management (break-even / scale-out / trailing). The default
        # TradeManager has everything DISABLED — see services/trade_manager.py
        # for the out-of-sample evidence — so behavior is identical to plain
        # stop/target exits until a config is explicitly enabled.
        from services.trade_manager import TradeManager
        self.trade_manager = trade_manager or TradeManager()
        self._managed: dict[str, object] = {}   # symbol -> ManagedTrade
        self._seq = itertools.count(1)
        # Activity tracking — used to explain *why* no trades are happening
        # (e.g. a stalled live feed that never delivers a new candle).
        self.last_bar_ts: Optional[str] = None      # timestamp of the last bar acted on
        self.last_activity: Optional[str] = None    # wall-clock of the last processed bar
        self.last_source: Optional[str] = None       # data source ("live (ccxt)" / "bundled sample" / …)

    # ----------------------------------------------------------- lifecycle
    def start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self.running = True
            from data.ledger import _now
            self.started_at = _now()
            self._thread = threading.Thread(target=self._run, name="auto-engine", daemon=True)
            self._thread.start()
            self.ledger.log(level="info", stage="engine",
                            message=f"Autonomous engine started — {', '.join(self.symbols)} ({self.timeframe})")
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self.running:
                return False
            self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=5)
        self.running = False
        self.ledger.log(level="info", stage="engine", message="Autonomous engine stopped")
        return True

    def reconfigure(self, *, symbols, timeframe, strategy_factory, label) -> dict:
        """Swap the running strategy / symbols / timeframe and restart (paper).
        Used to deploy a user-built custom strategy from the Strategy Builder."""
        self.stop()
        self.symbols = list(symbols)
        self.timeframe = timeframe
        self.strategy_factory = strategy_factory
        self.strategy_label = label
        self._targets.clear()
        self._managed.clear()
        self.stats = {"bars": 0, "signals": 0, "trades": 0, "rejections": 0}
        self.start()
        return self.status()

    def status(self) -> dict:
        return {
            "running": self.running,
            "symbols": self.symbols,
            "timeframe": self.timeframe,
            "interval": self.interval,
            "mode": "live" if self.live else "replay",
            "strategy": self.strategy_label,
            "started_at": self.started_at,
            "last_bar_ts": self.last_bar_ts,
            "last_activity": self.last_activity,
            "data_source": self.last_source,
            **self.stats,
        }

    # ----------------------------------------------------------- worker
    def _run(self) -> None:
        try:
            if self.live:
                self._run_live()
            else:
                self._run_replay()
        except Exception as e:  # noqa: BLE001 — never let the engine thread crash silently
            self.ledger.log(level="error", stage="engine", message=f"Engine error: {e}")
        finally:
            self.running = False

    def _run_replay(self) -> None:
        from data.market_data import get_bars

        strategies: dict[str, object] = {}
        live: dict[str, list] = {}
        seeds: dict[str, int] = {}

        for sym in self.symbols:
            seeds[sym] = 1
            self._load_batch(sym, strategies, live, seeds, get_bars)

        while not self._stop.is_set():
            advanced = False
            for sym in self.symbols:
                if self._stop.is_set():
                    break
                if not live[sym]:
                    self._load_batch(sym, strategies, live, seeds, get_bars)
                if not live[sym]:
                    continue
                bar = live[sym].pop(0)
                self._process_bar(sym, bar, strategies[sym])
                self.stats["bars"] += 1
                advanced = True
            if not advanced:
                break
            self._stop.wait(self.interval)

    # ------------------------------------------------------ live forward mode
    def _run_live(self) -> None:
        """Warm up on history WITHOUT trading, then act only on NEW closed
        candles as they arrive — genuine forward paper-trading."""
        strategies: dict[str, object] = {}
        last_ts: dict[str, object] = {}

        for sym in self.symbols:
            bars, src = self._fetcher(sym, self.timeframe, self.warmup + self.live_bars)
            self.last_source = src
            strat = self.strategy_factory(sym)
            closed = bars[:-1]                     # last candle may be in-progress
            for b in closed:                       # warm indicators, do NOT trade history
                strat.bars.append(b)
            strategies[sym] = strat
            last_ts[sym] = closed[-1].timestamp if closed else None
            self.ledger.log(level="info", stage="engine", symbol=sym,
                            message=f"{sym}: {src} — warmed {len(closed)} bars; "
                                    f"watching for new {self.timeframe} candles")

        while not self._stop.is_set():
            for sym in self.symbols:
                if self._stop.is_set():
                    break
                try:
                    bars, src = self._fetcher(sym, self.timeframe, max(self.warmup + 5, 60))
                    self.last_source = src
                    # Live mode but the feed isn't actually live -> it will never
                    # deliver a NEW candle, so warn loudly instead of going quiet.
                    if self.live and not (src or "").startswith("live"):
                        self.ledger.log(level="warning", stage="engine", symbol=sym,
                                        message=(f"{sym}: live feed unavailable — using '{src}'. "
                                                 f"No new {self.timeframe} candles will arrive; "
                                                 f"no trades will fire. Use replay mode or a reachable feed."))
                except Exception as e:  # noqa: BLE001 — a fetch hiccup shouldn't stop the engine
                    self.ledger.log(level="warning", stage="engine", symbol=sym,
                                    message=f"{sym}: live fetch failed ({e})")
                    continue
                last_ts[sym] = self._ingest(sym, strategies[sym], bars, last_ts[sym])
            self._stop.wait(self.live_poll_s)

    def _ingest(self, sym, strat, bars, last_ts):
        """Process only CLOSED bars newer than ``last_ts``; return updated last_ts."""
        closed = bars[:-1] if len(bars) > 1 else []   # drop in-progress last candle
        for b in closed:
            if last_ts is None or b.timestamp > last_ts:
                self._process_bar(sym, b, strat)
                self.stats["bars"] += 1
                last_ts = b.timestamp
        return last_ts

    def _load_batch(self, sym, strategies, live, seeds, get_bars) -> None:
        bars, src = get_bars(sym, n=self.warmup + self.live_bars,
                             timeframe=self.timeframe, seed=seeds[sym])
        self.last_source = src
        seeds[sym] += 1
        if sym not in strategies:
            strategies[sym] = self.strategy_factory(sym)
            # Warm up indicators with history WITHOUT trading it.
            for b in bars[:self.warmup]:
                strategies[sym].bars.append(b)
            live[sym] = list(bars[self.warmup:])
            self.ledger.log(level="info", stage="engine", symbol=sym,
                            message=f"{sym}: {src} data — warmed {self.warmup}, replaying {len(live[sym])} bars")
        else:
            live[sym] = list(bars)

    def _process_bar(self, sym: str, bar, strategy) -> None:
        from datetime import datetime, timezone
        # record activity so diagnostics can tell a live trade from a stalled feed
        try:
            self.last_bar_ts = bar.timestamp.isoformat()
        except Exception:  # noqa: BLE001
            self.last_bar_ts = str(getattr(bar, "timestamp", ""))
        self.last_activity = datetime.now(timezone.utc).isoformat()
        # 1. stop-loss / take-profit exits against this bar's range.
        self._check_exit(sym, bar)
        # 2. strategy decision on the new bar.
        signal: Optional[Signal] = strategy.on_bar(bar)
        if signal is not None:
            self._on_signal(sym, signal)

    def _check_exit(self, sym: str, bar) -> None:
        pos = self.paper.open_position(sym)
        if pos is None:
            self._managed.pop(sym, None)
            return
        mt = self._managed.get(sym)
        if mt is None:
            mt = self._adopt(sym, pos)
        exit_price = why = None
        if mt is not None:
            # shared TradeManager: stop/target exits + break-even / scale-out /
            # trailing when enabled (identical to the plain checks when not).
            act = self.trade_manager.on_bar(mt, bar.high, bar.low)
            if act.partial_price is not None:
                fill = self.paper.reduce(symbol=sym, exit_price=act.partial_price,
                                         fraction=self.trade_manager.scale_frac)
                if fill.action == "reduced":
                    self.ledger.log(level="info", stage="execution", symbol=sym,
                                    message=f"{sym} scale-out {fill.size:.6f} @ {fill.price}"
                                            f" (PnL {fill.pnl:+.2f})")
            if act.exit_price is not None:
                exit_price = act.exit_price
                why = "stop-loss" if act.exit_reason == "stop" else "take-profit"
        else:  # no stop on record (e.g. external webhook trade) — legacy checks
            stop, target = pos.get("stop"), self._targets.get(sym)
            if pos["side"] == "long":
                if stop and bar.low <= stop:
                    exit_price, why = stop, "stop-loss"
                elif target and bar.high >= target:
                    exit_price, why = target, "take-profit"
            else:
                if stop and bar.high >= stop:
                    exit_price, why = stop, "stop-loss"
                elif target and bar.low <= target:
                    exit_price, why = target, "take-profit"
        if exit_price is not None:
            res = self._route({
                "alert_id": f"auto-{sym}-x{next(self._seq)}", "symbol": sym,
                "side": "CLOSE", "entry": exit_price, "stop": None,
                "timestamp": bar.timestamp.isoformat(),
            })
            if res is not None and res.accepted:
                self.stats["trades"] += 1
                self._targets.pop(sym, None)
                self._managed.pop(sym, None)

    def _adopt(self, sym: str, pos: dict):
        """Rebuild management state for a position opened before a restart (or
        by a webhook). Needs a stop to define R; returns None without one."""
        from services.trade_manager import ManagedTrade
        stop = pos.get("stop")
        entry = pos.get("entry")
        if not stop or not entry or stop == entry:
            return None
        risk = abs(entry - stop)
        sign = 1.0 if pos["side"] == "long" else -1.0
        target = self._targets.get(sym) or entry + sign * 3.0 * risk
        mt = ManagedTrade(side=pos["side"], entry=entry, stop=stop,
                          target=target, risk=risk)
        self._managed[sym] = mt
        return mt

    def _on_signal(self, sym: str, signal: Signal) -> None:
        # The brain re-asserts its view every bar; only act when it CHANGES the
        # position (open from flat, or flip/close an opposite). Holding the same
        # direction is a no-op, so the decision log stays signal — not spam.
        desired = "long" if signal.type == SignalType.LONG else "short"
        pos = self.paper.open_position(sym)
        if pos is not None and pos["side"] == desired:
            return
        self.stats["signals"] += 1
        side = "BUY" if signal.type == SignalType.LONG else "SELL"
        res = self._route({
            "alert_id": f"auto-{sym}-{next(self._seq)}", "symbol": sym, "side": side,
            "entry": signal.entry, "stop": signal.stop_loss,
            "confidence": getattr(signal, "confidence", 1.0),
            "regime": getattr(signal, "regime", ""),
            "reason": getattr(signal, "reason", ""),
            "timestamp": signal.timestamp.isoformat(),
        })
        if res is None:
            return
        fill = res.fill or {}
        if res.accepted and fill.get("action") == "opened":
            self.stats["trades"] += 1
            self._targets[sym] = signal.take_profit
            entry, stop = fill.get("price") or signal.entry, signal.stop_loss
            if stop and entry and stop != entry:
                from services.trade_manager import ManagedTrade
                self._managed[sym] = ManagedTrade(
                    side="long" if signal.type == SignalType.LONG else "short",
                    entry=entry, stop=stop, target=signal.take_profit,
                    risk=abs(entry - stop))
        elif res.accepted and fill.get("action") == "closed":
            self.stats["trades"] += 1
            self._targets.pop(sym, None)
            self._managed.pop(sym, None)
        elif not res.accepted:
            self.stats["rejections"] += 1

    def _route(self, payload: dict):
        try:
            return self.pipeline.process(payload)
        except Exception as e:  # noqa: BLE001 — a bad bar shouldn't stop the engine
            self.ledger.log(level="error", stage="engine",
                            message=f"Pipeline error on {payload.get('symbol')}: {e}",
                            symbol=payload.get("symbol", ""))
            return None


# Approx seconds per candle, to judge whether a live feed has stalled.
_TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
               "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def explain_inactivity(*, running: bool, trading_state: str, mode: str, timeframe: str,
                       bars: int, signals: int, trades: int, rejections: int,
                       data_source: Optional[str], last_activity_age_s: Optional[float]) -> dict:
    """Plain-English answer to 'why isn't the bot trading?'. Pure + testable.

    Returns {status, headline, detail, severity}. ``status`` is a stable code the
    UI can switch on; ``severity`` is info|warning|critical.
    """
    def out(status, headline, detail, severity="info"):
        return {"status": status, "headline": headline, "detail": detail, "severity": severity}

    if not running:
        return out("stopped", "The engine is not running.",
                   "Start it from the Paper Trading page to begin scanning the market.", "warning")
    if trading_state and trading_state.lower() != "active":
        return out("halted", f"Trading is {trading_state}.",
                   "New entries are blocked. Resume from Risk Manager / Safety Center.", "warning")
    if bars == 0:
        return out("no_data", "No market data has been processed yet.",
                   "The data feed may be unavailable, or the engine just started warming up.", "warning")

    tf_s = _TF_SECONDS.get(timeframe, 3600)
    if mode == "live" and data_source and data_source != "live (ccxt)":
        return out("stale_feed", "Live mode is on, but the live feed is unavailable on this host.",
                   (f"It fell back to '{data_source}' (static historical data). Exchanges like "
                    f"Binance often block cloud/datacenter IPs, so no NEW {timeframe} candle ever "
                    f"arrives — which is why no trades fire and the balance never changes. "
                    f"Switch to replay mode (unset HUB_USE_LIVE_DATA) for a live demo, or point at a "
                    f"reachable data source."), "critical")
    if mode == "live" and last_activity_age_s is not None and last_activity_age_s > 1.5 * tf_s:
        hrs = last_activity_age_s / 3600
        return out("waiting_candles", f"Waiting for the next {timeframe} candle.",
                   (f"The last new candle was ~{hrs:.1f}h ago. On {timeframe} there are only a few "
                    f"candles per day, so trades are infrequent by design. Use a lower timeframe "
                    f"(e.g. 15m/1h) for more activity."), "info")
    if signals == 0 and bars > 0:
        return out("no_setup", f"Scanned {bars} bars — no valid setup yet.",
                   "The strategy and quality filter are waiting for a high-quality entry. Fewer, "
                   "better trades is the intended behaviour.", "info")
    if trades == 0 and rejections > 0:
        return out("all_blocked", f"Found setups, but all {rejections} were blocked.",
                   "Risk/quality filters rejected every candidate. Check the Logs page for the exact "
                   "reasons (e.g. against higher-timeframe trend, choppy regime, weak reward:risk).", "warning")
    if trades == 0:
        return out("warming_up", "Engine active — no trades yet.",
                   "Still warming up or waiting for the first qualifying setup.", "info")
    return out("active", f"Engine healthy — {trades} trades taken.",
               f"{signals} signals, {rejections} blocked by filters.", "info")
