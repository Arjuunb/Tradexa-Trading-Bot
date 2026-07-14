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
        entry_mode: Optional[str] = None,
        limit_ttl_bars: int = 3,
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
        # Maker entries (measured better on all validation suites): a signal
        # parks a resting limit at its price; it fills only when price trades
        # through it (no spread/slippage) and expires unfilled after
        # ``limit_ttl_bars`` bars. HUB_ENTRY_MODE=market restores taker entries.
        import os as _os
        self.entry_mode = (entry_mode or _os.environ.get("HUB_ENTRY_MODE", "limit")).lower()
        self.limit_ttl_bars = max(1, int(limit_ttl_bars))
        # PARITY: every backtest/simulation filters entries through the
        # TradeBrain quality scorer (min score 60) — the live engine must
        # apply the IDENTICAL gate or live results run worse than the promise.
        # 0 disables; the gate stands down below 60 bars of history (warmup).
        self.min_quality_score = int(_os.environ.get("HUB_MIN_SCORE", "60"))
        from strategies.brain import TradeBrain
        self._quality_brain = TradeBrain()
        # Context-aware modifiers (cross-asset gate / funding / sentiment) —
        # ALL OFF by default; enable validated ones via HUB_CONTEXT after
        # POST /research/validate-context proves them on real candles.
        from services.context_brain import ContextModifiers
        self.context = ContextModifiers(
            leader_bars_fn=lambda: self._fetcher("BTCUSDT", self.timeframe, 80)[0])
        self._pending: dict[str, dict] = {}     # symbol -> resting limit order
        self.stats_missed_entries = 0
        # Shadow A/B: an optional services.shadow.ShadowRun fed the SAME bars
        # the live strategy trades — a candidate audition with zero capital.
        self.shadow = None
        # Counterfactual tracker (shared with the pipeline): resolves vetoed
        # and missed entries against the same bars the engine trades.
        self.counterfactual = None
        # Unified decision store: EVERY evaluated signal is persisted as a
        # decision object (accepted or rejected) BEFORE any trade is placed.
        self.decisions = None
        # Explainable Trading: per-cycle Decision Report store (data.cycle_store)
        self.reports = None
        self._seq = itertools.count(1)
        # Activity tracking — used to explain *why* no trades are happening
        # (e.g. a stalled live feed that never delivers a new candle).
        self.last_bar_ts: Optional[str] = None      # timestamp of the last bar acted on
        self.last_activity: Optional[str] = None    # wall-clock of the last processed bar
        self.last_source: Optional[str] = None       # data source ("live (ccxt)" / "bundled sample" / …)
        self._warned_fallback: set = set()           # symbols already warned (no per-poll spam)

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
        self._pending.clear()
        self.stats = {"bars": 0, "signals": 0, "trades": 0, "rejections": 0}
        self.start()
        return self.status()

    def feed_status(self) -> tuple[str, Optional[str]]:
        """(status, error) describing the data feed honestly:
        connected | waiting-for-candle | fallback | failed | replay."""
        err = None
        try:
            from data.live_data import last_error
            err = last_error()
        except Exception:  # noqa: BLE001
            pass
        if not self.live:
            return "replay", err
        src = self.last_source or ""
        if src.startswith("live"):
            return ("connected" if self.stats["bars"] > 0 else "waiting-for-candle"), None
        if src:
            return "fallback", err          # live wanted, static source delivered
        return ("failed" if err else "waiting-for-candle"), err

    def status(self) -> dict:
        feed, feed_err = self.feed_status()
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
            "feed_status": feed,             # connected | waiting-for-candle | fallback | failed | replay
            "feed_error": feed_err,          # last real fetch error, if any
            "entry_mode": self.entry_mode,
            "pending_orders": len(self._pending),
            "missed_entries": self.stats_missed_entries,
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
                    # deliver a NEW candle, so warn loudly (once per symbol, with
                    # the REAL fetch error) instead of going quiet or spamming.
                    if self.live and not (src or "").startswith("live"):
                        if sym not in self._warned_fallback:
                            self._warned_fallback.add(sym)
                            err = None
                            try:
                                from data.live_data import last_error
                                err = last_error(sym)
                            except Exception:  # noqa: BLE001
                                pass
                            why = f" Live fetch error: {err}." if err else ""
                            self.ledger.log(level="warning", stage="engine", symbol=sym,
                                            message=(f"{sym}: live feed unavailable — using '{src}'.{why} "
                                                     f"No new {self.timeframe} candles will arrive; "
                                                     f"no trades will fire. Fix the feed (try HUB_EXCHANGE="
                                                     f"kraken/coinbase — Binance blocks many cloud IPs) or "
                                                     f"unset HUB_USE_LIVE_DATA for replay mode."))
                    elif (src or "").startswith("live") and sym in self._warned_fallback:
                        self._warned_fallback.discard(sym)
                        self.ledger.log(level="info", stage="engine", symbol=sym,
                                        message=f"{sym}: live feed recovered ({src}).")
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
        # 0. shadow candidate sees the same bar (virtual, zero capital).
        if self.shadow is not None:
            try:
                self.shadow.on_bar(sym, bar)
            except Exception:  # noqa: BLE001 — the shadow must never affect live
                pass
        # 0b. resolve counterfactual (vetoed/missed) virtual trades.
        if self.counterfactual is not None:
            try:
                self.counterfactual.on_bar(sym, bar)
            except Exception:  # noqa: BLE001 — grading must never affect live
                pass
        # 1. resting limit entry: fill if this bar traded through it.
        self._check_pending(sym, bar)
        # 2. stop-loss / take-profit exits against this bar's range.
        self._check_exit(sym, bar)
        # 3. strategy decision on the new bar.
        signal: Optional[Signal] = strategy.on_bar(bar)
        outcome: Optional[dict] = None
        if signal is not None:
            outcome = self._on_signal(sym, signal, strategy)
        # 4. Explainable Trading: one complete Decision Report per cycle —
        #    including WAIT candles — so the bot never acts (or holds back)
        #    silently. Reporting must never affect trading.
        if self.reports is not None:
            try:
                from services.explain import build_cycle_report
                report = build_cycle_report(
                    symbol=sym, timeframe=self.timeframe,
                    bars=list(getattr(strategy, "bars", []) or []),
                    signal=signal, outcome=outcome,
                    position=self.paper.open_position(sym),
                    session=(self.pipeline.session_start, self.pipeline.session_end,
                             self.pipeline.trading_days_mask))
                self.reports.record(report)
            except Exception as e:  # noqa: BLE001 — never block the engine
                print(f"[explain] cycle report failed for {sym}: {type(e).__name__}: {e}")

    def _check_pending(self, sym: str, bar) -> None:
        po = self._pending.get(sym)
        if po is None:
            return
        if self.paper.open_position(sym) is not None:
            self._pending.pop(sym, None)
            return
        long = po["side"] == "BUY"
        fill = None
        if long and bar.open <= po["price"]:
            fill = bar.open                       # gapped through: better fill
        elif long and bar.low <= po["price"]:
            fill = po["price"]
        elif not long and bar.open >= po["price"]:
            fill = bar.open
        elif not long and bar.high >= po["price"]:
            fill = po["price"]
        if fill is None:
            po["ttl"] -= 1
            if po["ttl"] <= 0:
                self._pending.pop(sym, None)
                self.stats_missed_entries += 1
                self.ledger.log(level="info", stage="engine", symbol=sym,
                                message=f"{sym}: limit entry expired unfilled @ {po['price']}")
                # grade the miss: did the trade we refused to chase work out?
                if self.counterfactual is not None:
                    try:
                        self.counterfactual.record_veto(
                            symbol=sym, side="long" if long else "short",
                            entry=po["price"], stop=po["payload"].get("stop"),
                            target=po.get("target"), rule="limit-ttl",
                            detail="limit entry expired unfilled",
                            time=bar.timestamp.isoformat())
                    except Exception:  # noqa: BLE001
                        pass
            return
        self._pending.pop(sym, None)
        res = self._route({**po["payload"], "entry": fill, "maker": True,
                           "timestamp": bar.timestamp.isoformat()})
        if res is None:
            return
        f = res.fill or {}
        if res.accepted and f.get("action") == "opened":
            if po.get("decision_id") is not None and self.decisions is not None:
                try:
                    self.decisions.mark_executed(po["decision_id"])
                except Exception:  # noqa: BLE001
                    pass
            self.stats["trades"] += 1
            self._targets[sym] = po["target"]
            entry, stop = f.get("price") or fill, po["payload"].get("stop")
            if stop and entry and stop != entry:
                from services.trade_manager import ManagedTrade
                self._managed[sym] = ManagedTrade(
                    side="long" if long else "short", entry=entry, stop=stop,
                    target=po["target"], risk=abs(entry - stop))
        elif not res.accepted:
            self.stats["rejections"] += 1

    @staticmethod
    def _mfe_mae_r(mt) -> tuple:
        """Lifecycle telemetry in R for a managed trade (None when untracked)."""
        if mt is None or not getattr(mt, "risk", 0):
            return None, None
        sign = 1.0 if mt.side == "long" else -1.0
        mfe_r = round((mt.mfe - mt.entry) * sign / mt.risk, 3)
        mae_r = round((mt.entry - mt.mae) * sign / mt.risk, 3)
        return mfe_r, mae_r

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
            act = self.trade_manager.on_bar(mt, bar.high, bar.low, bar.close)
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
            mfe_r, mae_r = self._mfe_mae_r(mt)
            res = self._route({
                "alert_id": f"auto-{sym}-x{next(self._seq)}", "symbol": sym,
                "side": "CLOSE", "entry": exit_price, "stop": None,
                "exit_reason": why,          # real exit cause for the journal
                "mfe_r": mfe_r, "mae_r": mae_r,   # lifecycle telemetry
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

    def _on_signal(self, sym: str, signal: Signal, strategy=None) -> Optional[dict]:
        # The brain re-asserts its view every bar; only act when it CHANGES the
        # position (open from flat, or flip/close an opposite). Holding the same
        # direction is a no-op, so the decision log stays signal — not spam.
        desired = "long" if signal.type == SignalType.LONG else "short"
        pos = self.paper.open_position(sym)
        if pos is not None and pos["side"] == desired:
            return {"kind": "hold"}
        self.stats["signals"] += 1
        side = "BUY" if signal.type == SignalType.LONG else "SELL"
        # Decision Brain gate (parity with every backtest): score the setup with
        # the same TradeBrain the simulators use, build the unified decision
        # object, and persist it — accepted OR rejected — BEFORE any trade.
        bars = list(getattr(strategy, "bars", []) or [])
        v = None
        if (self.min_quality_score > 0 and signal.stop_loss and pos is None
                and len(bars) >= 60):
            v = self._quality_brain.evaluate(
                bars, len(bars) - 1,
                side="long" if signal.type == SignalType.LONG else "short",
                entry=signal.entry, stop=signal.stop_loss,
                target=signal.take_profit)
        decision = None
        decision_id = None
        if pos is None:                      # entries only; flips/closes pass through
            from services.decision_gate import build_decision
            decision = build_decision(
                symbol=sym, timeframe=self.timeframe, strategy=self.strategy_label,
                side="long" if signal.type == SignalType.LONG else "short",
                confidence=getattr(signal, "confidence", None), verdict=v,
                min_score=self.min_quality_score,
                regime_hint=getattr(signal, "regime", ""))
            if self.decisions is not None:
                try:
                    decision_id = self.decisions.record(decision)
                except Exception:  # noqa: BLE001 — persistence must never block trading
                    pass
        if decision is not None and decision["decision"] == "rejected":
            self.stats["rejections"] += 1
            why = decision["reason"]
            self.ledger.log(level="info", stage="brain", symbol=sym,
                            message=f"{sym} {side} blocked by decision gate: {why}")
            if self.counterfactual is not None:
                try:
                    self.counterfactual.record_veto(
                        symbol=sym,
                        side="long" if signal.type == SignalType.LONG else "short",
                        entry=signal.entry, stop=signal.stop_loss,
                        target=signal.take_profit, rule="quality-score",
                        detail=why, time=signal.timestamp.isoformat())
                except Exception:  # noqa: BLE001
                    pass
            return {"kind": "rejected", "stage": "brain", "reason": why,
                    "decision": decision, "verdict": v}
        # context gate: never long an altcoin against BTC's own trend
        # (cross-asset modifier; OFF unless validated + enabled)
        ctx_why = self.context.gate(sym, "long" if signal.type == SignalType.LONG else "short")
        if ctx_why and pos is None:
            self.stats["rejections"] += 1
            self.ledger.log(level="info", stage="context", symbol=sym,
                            message=f"{sym} {side} blocked: {ctx_why}")
            if self.counterfactual is not None:
                try:
                    self.counterfactual.record_veto(
                        symbol=sym,
                        side="long" if signal.type == SignalType.LONG else "short",
                        entry=signal.entry, stop=signal.stop_loss,
                        target=signal.take_profit, rule="context:btc-trend",
                        detail=ctx_why, time=signal.timestamp.isoformat())
                except Exception:  # noqa: BLE001
                    pass
            return {"kind": "rejected", "stage": "context", "reason": ctx_why,
                    "decision": decision, "verdict": v}
        payload = {
            "alert_id": f"auto-{sym}-{next(self._seq)}", "symbol": sym, "side": side,
            "entry": signal.entry, "stop": signal.stop_loss,
            "target": signal.take_profit,
            "confidence": getattr(signal, "confidence", 1.0),
            "regime": getattr(signal, "regime", ""),
            "reason": getattr(signal, "reason", ""),
            "context_size_factor": self.context.size_factor(
                sym, "long" if signal.type == SignalType.LONG else "short"),
            # real decision context for the trade journal
            "brain_score": getattr(signal, "brain_score", None),
            "snapshot": getattr(signal, "snapshot", None),
            "brain_checklist": getattr(signal, "checklist", None),
            "strategy": self.strategy_label,
            "timeframe": self.timeframe,
            "mode": "live" if self.live else "paper",
            "open_trades": len(self.paper.positions()),
            "timestamp": signal.timestamp.isoformat(),
        }
        # Maker entry: when FLAT, park a resting limit instead of paying the
        # spread. Flips/closes (opposite side of an open position) stay
        # immediate — exits are never left resting.
        if pos is not None:   # opposite side of an open position -> this routes as a close
            _mfe, _mae = self._mfe_mae_r(self._managed.get(sym))
            payload["mfe_r"], payload["mae_r"] = _mfe, _mae
        if self.entry_mode == "limit" and pos is None and signal.stop_loss:
            self._pending[sym] = {"side": side, "price": signal.entry,
                                  "target": signal.take_profit,
                                  "ttl": self.limit_ttl_bars, "payload": payload,
                                  "decision_id": decision_id}
            return {"kind": "pending", "decision": decision, "verdict": v}
        res = self._route(payload)
        if res is None:
            return {"kind": "error", "reason": "pipeline error (see engine log)"}
        fill = res.fill or {}
        if res.accepted and fill.get("action") == "opened":
            if decision_id is not None and self.decisions is not None:
                try:
                    self.decisions.mark_executed(decision_id)
                except Exception:  # noqa: BLE001
                    pass
            self.stats["trades"] += 1
            self._targets[sym] = signal.take_profit
            entry, stop = fill.get("price") or signal.entry, signal.stop_loss
            if stop and entry and stop != entry:
                from services.trade_manager import ManagedTrade
                self._managed[sym] = ManagedTrade(
                    side="long" if signal.type == SignalType.LONG else "short",
                    entry=entry, stop=stop, target=signal.take_profit,
                    risk=abs(entry - stop))
            return {"kind": "opened", "decision": decision, "verdict": v, "fill": fill}
        elif res.accepted and fill.get("action") == "closed":
            self.stats["trades"] += 1
            self._targets.pop(sym, None)
            self._managed.pop(sym, None)
            return {"kind": "closed", "fill": fill}
        elif not res.accepted:
            self.stats["rejections"] += 1
            return {"kind": "rejected", "stage": res.stage, "reason": res.reason,
                    "decision": decision, "verdict": v}
        return {"kind": "noop", "decision": decision, "verdict": v}

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
                       data_source: Optional[str], last_activity_age_s: Optional[float],
                       feed_error: Optional[str] = None) -> dict:
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

    tf_s = _TF_SECONDS.get(timeframe, 3600)
    # The precise feed diagnosis must come BEFORE the generic bars==0 message —
    # a fallen-back live feed keeps bars at 0 forever, and hiding that behind
    # "just started warming up" is exactly how it goes unnoticed.
    if mode == "live" and data_source and not str(data_source).startswith("live"):
        err = f" Last fetch error: {feed_error}." if feed_error else ""
        return out("stale_feed", "Running — data feed FAILED (static fallback active).",
                   (f"Live data is enabled but every fetch failed, so it fell back to "
                    f"'{data_source}' (static historical data).{err} Exchanges like Binance "
                    f"block many cloud/datacenter IPs (HTTP 451), so no NEW {timeframe} candle "
                    f"will ever arrive — bars stay 0 and no trades can fire. Fix: set "
                    f"HUB_EXCHANGE=kraken (or coinbase) and redeploy, or unset "
                    f"HUB_USE_LIVE_DATA to run replay mode instead."), "critical")
    if bars == 0:
        if mode == "live" and str(data_source or "").startswith("live"):
            hrs = tf_s / 3600
            wait = (f"up to {hrs:.0f} hours" if tf_s >= 3600
                    else f"up to {tf_s // 60} minutes")
            return out("waiting_first_candle", "Running — data feed connected, waiting for the first candle.",
                       (f"The live feed is healthy; the engine acts only when a {timeframe} candle "
                        f"CLOSES, which can take {wait} from now. For faster activity during "
                        f"testing, set HUB_AUTO_TIMEFRAME=5m or 15m and redeploy."), "info")
        return out("no_data", "No market data has been processed yet.",
                   "The data feed may be unavailable, or the engine just started warming up.", "warning")
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
