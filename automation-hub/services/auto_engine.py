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
        self._seq = itertools.count(1)

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
                    bars, _ = self._fetcher(sym, self.timeframe, max(self.warmup + 5, 60))
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
        # 1. stop-loss / take-profit exits against this bar's range.
        self._check_exit(sym, bar)
        # 2. strategy decision on the new bar.
        signal: Optional[Signal] = strategy.on_bar(bar)
        if signal is not None:
            self._on_signal(sym, signal)

    def _check_exit(self, sym: str, bar) -> None:
        pos = self.paper.open_position(sym)
        if pos is None:
            return
        stop = pos.get("stop")
        target = self._targets.get(sym)
        exit_price = why = None
        if pos["side"] == "long":
            if stop and bar.low <= stop:
                exit_price, why = stop, "stop-loss"
            elif target and bar.high >= target:
                exit_price, why = target, "take-profit"
        else:  # short
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
            "reason": getattr(signal, "reason", ""),
            "timestamp": signal.timestamp.isoformat(),
        })
        if res is None:
            return
        fill = res.fill or {}
        if res.accepted and fill.get("action") == "opened":
            self.stats["trades"] += 1
            self._targets[sym] = signal.take_profit
        elif res.accepted and fill.get("action") == "closed":
            self.stats["trades"] += 1
            self._targets.pop(sym, None)
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
