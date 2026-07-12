"""Signal Pipeline (Phase 1) — the brain that turns a TradingView alert into a
paper trade, safely and transparently.

    alert -> [controls] -> [dedup] -> [risk + sizing] -> [paper execution]
          -> ledger (webhook_events, positions, paper_trades, bot_logs, alerts)

Every stage records a decision step (passed/failed + reason) so the Logs page
shows exactly why a trade executed or was rejected. No real broker is touched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from database.models import RiskRules
from data.ledger import Ledger
from execution.paper_engine import PaperExecutionEngine, _dir
from risk.position_sizing import size_position
from services.controls import TradingControl
from services.dedup import DuplicateGuard
from services.market_quality import MarketQualityGate


@dataclass
class Step:
    rule: str
    passed: bool
    detail: str = ""


@dataclass
class PipelineResult:
    accepted: bool
    stage: str
    reason: str
    steps: list[Step] = field(default_factory=list)
    fill: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted, "stage": self.stage, "reason": self.reason,
            "steps": [s.__dict__ for s in self.steps],
            "fill": self.fill,
        }


_CLOSE_SIDES = {"CLOSE", "EXIT", "FLAT"}

# Correlation clusters: assets that move together. Crypto majors are treated as
# ONE cluster — three simultaneous longs on BTC/ETH/SOL are not diversification,
# they are one 3x-sized bet on the same market. Extend the map as new asset
# classes are added.
_CRYPTO_QUOTES = ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH")


def _cluster(symbol: str) -> str:
    s = (symbol or "").upper().replace("/", "").replace("-", "")
    if s.endswith(_CRYPTO_QUOTES):
        return "crypto"
    return "other"


class SignalPipeline:
    def __init__(
        self,
        ledger: Ledger,
        paper: PaperExecutionEngine,
        controls: TradingControl,
        *,
        equity: float = 10_000.0,
        risk_per_trade_pct: float = 0.01,
        exposure_limit_pct: float = 0.05,
        dedup_window_s: int = 300,
        quality: Optional[MarketQualityGate] = None,
        max_drawdown_pct: float = 0.20,
        max_open_positions: int = 3,
        max_daily_loss_pct: float = 0.0,
        session_start: int = 0,
        session_end: int = 24,
        max_weekly_loss_pct: float = 0.0,
        max_trades_per_day: int = 0,
        max_consecutive_losses: int = 0,
        cooldown_after_loss_min: int = 0,
        trading_days_mask: int = 127,
        adaptive_risk: bool = True,
        max_correlated_positions: int = 2,
        max_total_exposure_pct: float = 0.10,
        equity_throttle: bool = True,
    ):
        self.ledger = ledger
        self.paper = paper
        self.controls = controls
        self.equity = equity
        self.risk_per_trade_pct = risk_per_trade_pct
        self.exposure_limit_pct = exposure_limit_pct
        self.dedup = DuplicateGuard(ledger, dedup_window_s)
        # Fail-closed pre-trade safety gate (default = strong defaults).
        self.quality = quality or MarketQualityGate()
        # Automatic capital protection: a drawdown circuit breaker (halts new
        # entries, never exits) + a cap on concurrent positions.
        self.max_drawdown_pct = max_drawdown_pct
        self.max_open_positions = max_open_positions
        # Daily-loss kill switch (resets each UTC day) + trading-session window.
        self.max_daily_loss_pct = max_daily_loss_pct
        self.session_start = session_start
        self.session_end = session_end
        self.max_weekly_loss_pct = max_weekly_loss_pct
        self.max_trades_per_day = max_trades_per_day
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_after_loss_min = cooldown_after_loss_min
        self.trading_days_mask = trading_days_mask
        # Kelly-capped adaptive sizing: risk less when the recent record is weak.
        self.adaptive_risk = adaptive_risk
        # Portfolio-level risk: correlated same-direction positions look like
        # diversification but are one oversized bet; total notional is capped
        # across ALL open positions; the equity-curve throttle halves risk while
        # the bot trades below its own recent equity average.
        self.max_correlated_positions = max_correlated_positions
        self.max_total_exposure_pct = max_total_exposure_pct
        self.equity_throttle = equity_throttle
        # Optional notification hook: callable(kind, title, detail). Best-effort.
        self.notifier = None
        # Self-learning loop (services/learning.LearningBook). When attached,
        # learned corrections gate entries + scale risk, and every close
        # triggers a re-learn from the bot's own record.
        self.learning = None
        self._alert_info: dict[str, dict] = {}   # alert_id -> confidence/regime
        self._alert_info_hydrated = False        # rebuilt from the ledger once
        # Event-risk gate: callable returning upcoming econ events. Blackout
        # halts new entries; caution halves size (exits are never blocked).
        self.econ_events = None
        # Allocator tilt: callable(symbol) -> size multiplier from the live
        # per-symbol record (evidence-only, capped — see services/allocator.py).
        self.allocator = None
        # Counterfactual tracker: every meaningful veto is followed as a
        # virtual trade so each rule gets graded by what it actually blocked.
        self.counterfactual = None
        # Decision journal: the full explainable record of every trade.
        self.journal = None
        # Skipped-trade log: every rejected setup with its failed gate + snapshot.
        self.skipped = None
        # Permanent trade memory: composes the closed trade into a forever record.
        self.trade_memory = None
        self._halted = False
        self._halt_reason = ""
        # Drawdown is measured from this baseline; a manual Resume rebaselines to
        # the current equity so the same loss doesn't immediately re-halt.
        self._dd_base_balance = paper.starting_balance
        self._dd_base_count = 0

    def process(self, payload: dict) -> PipelineResult:
        symbol = payload["symbol"]
        side = str(payload["side"]).upper()
        entry = float(payload["entry"])
        stop = payload.get("stop")
        stop = float(stop) if stop is not None else None
        alert_id = payload.get("alert_id", "")
        # Optional brain inputs: conviction (scales risk) + human-readable rationale.
        confidence = float(payload.get("confidence", 1.0) or 1.0)
        confidence = max(0.0, min(1.0, confidence))
        brain_reason = str(payload.get("reason", "") or "")
        steps: list[Step] = []

        # Vetoes from these stages are judgment calls worth grading — the
        # counterfactual tracker follows what the blocked trade would have done.
        _GRADED_STAGES = ("learning", "event_risk", "correlation", "risk_guard",
                          "daily_loss", "weekly_loss", "session", "trading_day",
                          "cooldown", "max_trades", "portfolio_exposure")

        def reject(stage: str, reason: str, status: str = "rejected") -> PipelineResult:
            steps.append(Step(stage, False, reason))
            self.ledger.insert_webhook_event(alert_id=alert_id, symbol=symbol, side=side,
                                              entry=entry, stop=stop, payload=payload,
                                              status=status, reason=reason)
            self.ledger.log(level="warning", stage=stage, message=f"{symbol} {side} rejected: {reason}", symbol=symbol)
            self.ledger.add_alert(severity="warning", category="trade",
                                  title=f"Trade rejected — {symbol}", detail=reason)
            # First-class skipped-trade record: the gate that failed + the real
            # market snapshot, so every "no" is explainable and searchable.
            if self.skipped is not None:
                try:
                    self.skipped.record(
                        symbol=symbol, side=side, stage=stage, reason=reason,
                        status=status, entry=entry, stop=stop, target=payload.get("target"),
                        strategy=payload.get("strategy", ""), timeframe=payload.get("timeframe", ""),
                        snapshot=payload.get("snapshot") or {})
                except Exception:  # noqa: BLE001 — logging must never block trading
                    pass
            if (self.counterfactual is not None and stage in _GRADED_STAGES
                    and stop and entry and side not in _CLOSE_SIDES):
                rule = stage
                if stage == "learning" and getattr(self.learning, "last_gate_key", None):
                    rule = f"learning:{self.learning.last_gate_key}"
                try:
                    self.counterfactual.record_veto(
                        symbol=symbol, side=_dir(side), entry=entry, stop=stop,
                        target=payload.get("target"), rule=rule, detail=reason,
                        time=payload.get("timestamp") or "")
                except Exception:  # noqa: BLE001 — grading must never block trading
                    pass
            return PipelineResult(False, stage, reason, steps)

        # 1. emergency controls
        if not self.controls.trading_allowed():
            return reject("controls", f"Trading {self.controls.state.lower()} — entry blocked")
        steps.append(Step("controls", True, "trading active"))

        # 1.5 market-quality gate (fail-closed: bad data / untradeable market -> veto)
        q = self.quality.check(
            entry=entry, stop=stop, timestamp=payload.get("timestamp"),
            bid=payload.get("bid"), ask=payload.get("ask"),
            spread_bps=payload.get("spread_bps"),
        )
        if not q.ok:
            return reject("market_quality", q.reason)
        steps.append(Step("market_quality", True, "data + microstructure ok"))

        # 2. duplicate protection
        if self.dedup.is_duplicate(alert_id):
            return reject("dedup", f"Duplicate alert_id within {self.dedup.window_seconds}s", status="duplicate")
        steps.append(Step("dedup", True, "no duplicate"))

        existing = self.paper.open_position(symbol)

        # 3a. CLOSE signal (explicit, or opposite side of an open position)
        if side in _CLOSE_SIDES or (existing and _dir(side) != existing["side"]):
            if existing is None:
                return reject("execution", "Close signal with no open position")
            # link the closing trade to its open journal before the ledger row closes
            _open_tid = next((t["id"] for t in self.ledger.get_paper_trades()
                              if t["symbol"] == symbol and t["status"] == "open"), None)
            fill = self.paper.close(symbol=symbol, exit_price=entry)
            if self.journal is not None and _open_tid:
                try:
                    self.journal.record_exit(
                        trade_id=_open_tid, exit_price=entry, pnl=fill.pnl,
                        exit_reason=payload.get("exit_reason")
                        or ("opposite-signal" if side not in _CLOSE_SIDES else "manual-close"))
                except Exception:  # noqa: BLE001 — journaling must never block trading
                    pass
                # commit the now-closed trade to permanent memory (never blocks)
                if self.trade_memory is not None:
                    try:
                        self.trade_memory.remember(_open_tid)
                    except Exception:  # noqa: BLE001 — memory must never block trading
                        pass
            self.ledger.insert_webhook_event(alert_id=alert_id, symbol=symbol, side=side,
                                              entry=entry, stop=stop, payload=payload, status="accepted")
            self.ledger.log(level="info", stage="execution",
                            message=f"{symbol} closed @ {entry} (PnL {fill.pnl:+.2f})", symbol=symbol)
            self.ledger.add_alert(severity="info", category="trade",
                                  title=f"Position closed — {symbol}", detail=f"PnL {fill.pnl:+.2f}")
            self._notify("trade", f"📉 {symbol} closed", f"PnL {fill.pnl:+.2f}")
            steps.append(Step("execution", True, f"closed PnL {fill.pnl:+.2f}"))
            # A losing close may breach drawdown -> halt future entries (not exits).
            if not self._halted:
                dd = self._drawdown_trip()
                if dd is not None:
                    self._engage_halt(dd)
            # every closed trade is a datapoint: re-learn from the full record,
            # with counterfactual evidence falsifying rules that block winners
            if self.learning is not None:
                try:
                    costing = (self.counterfactual.costing_rules()
                               if self.counterfactual is not None else None)
                    self.learning.update(self.paper.history(), self.alert_context(),
                                         costing_rules=costing)
                except Exception:  # noqa: BLE001 — learning must never block trading
                    pass
            return PipelineResult(True, "execution", "position closed", steps, fill.__dict__)

        # 3b. OPEN — no pyramiding in Phase 1
        if existing is not None:
            return reject("execution", f"Position already open on {symbol} (no pyramiding)")

        # 3c. portfolio cap — limit concurrent open positions
        if len(self.paper.positions()) >= self.max_open_positions:
            return reject("risk_guard", f"Max open positions ({self.max_open_positions}) reached")

        # 3c2. correlation guard — same-direction positions in the same asset
        # cluster compound into one oversized bet (crypto majors move together)
        if self.max_correlated_positions > 0:
            cluster, direction = _cluster(symbol), _dir(side)
            same = sum(1 for p in self.paper.positions()
                       if p["side"] == direction and _cluster(p["symbol"]) == cluster)
            if same >= self.max_correlated_positions:
                return reject("correlation",
                              f"{same} open {direction} positions in the {cluster} cluster "
                              f"(max {self.max_correlated_positions}) — correlated exposure")
            steps.append(Step("correlation", True,
                              f"{same}/{self.max_correlated_positions} {direction} in {cluster}"))

        # 3c2b. event-risk gate — high-impact macro events (CPI/FOMC/NFP) spike
        # volatility and gap stops; inside the blackout window no NEW entries.
        econ_risk = 1.0
        if self.econ_events is not None:
            from services.econ_guard import evaluate as _econ_eval
            ev = _econ_eval(self.econ_events())
            if ev["halt_new_entries"]:
                return reject("event_risk",
                              f"Event blackout: {ev['next_event']['name']} in "
                              f"{ev['minutes_to_event']:.0f}m — no new entries")
            econ_risk = ev.get("risk_multiplier", 1.0) or 1.0
            if econ_risk < 1.0:
                steps.append(Step("event_risk", True,
                                  f"caution: {ev['next_event']['name']} in "
                                  f"{ev['minutes_to_event']:.0f}m → risk ×{econ_risk:.2f}"))

        # 3c3. learned blocks — corrections the bot taught itself from its own
        # losing trades (bad regime, low conviction, post-loss cooldown)
        if self.learning is not None:
            secs = self._since_last_loss()
            why = self.learning.gate(symbol=symbol, regime=payload.get("regime", ""),
                                     confidence=confidence,
                                     minutes_since_loss=None if secs is None else secs / 60)
            if why:
                return reject("learning", why)
            steps.append(Step("learning", True, "no learned blocks"))

        # 3d. drawdown circuit breaker — auto-halt NEW ENTRIES until manual resume
        #     (exits are never blocked, so open positions can always stop out).
        if not self._halted:
            dd = self._drawdown_trip()
            if dd is not None:
                self._engage_halt(dd)
        if self._halted:
            return reject("risk_guard", f"Auto-halt: {self._halt_reason}")
        steps.append(Step("risk_guard", True, "within risk limits"))

        # 3d2. allowed trading days (UTC weekday) — blocks entries on disabled days
        if self.trading_days_mask != 127:
            wd = self._entry_weekday(payload.get("timestamp"))
            if not (self.trading_days_mask >> wd) & 1:
                return reject("trading_day", "Today is not an allowed trading day")
            steps.append(Step("trading_day", True, "allowed day"))

        # 3e. trading-session window (UTC hours) — blocks entries outside hours
        if self.session_start != 0 or self.session_end != 24:
            hour = self._entry_hour(payload.get("timestamp"))
            if not (self.session_start <= hour < self.session_end):
                return reject("session", f"Outside session {self.session_start:02d}:00–{self.session_end:02d}:00 UTC")
            steps.append(Step("session", True, "within trading hours"))

        # 3f. daily-loss kill switch — blocks NEW entries once today's loss exceeds
        #     the limit; resets automatically at the next UTC day.
        if self.max_daily_loss_pct > 0:
            today = self._today_pnl()
            limit = self.max_daily_loss_pct * self.paper.starting_balance
            if today <= -limit:
                return reject("daily_loss", f"Daily loss limit hit ({today:+.2f} ≤ -{limit:.2f})")
            steps.append(Step("daily_loss", True, f"today {today:+.2f} / -{limit:.2f}"))

        # 3g. weekly-loss limit (resets each ISO week)
        if self.max_weekly_loss_pct > 0:
            wk = self._week_pnl()
            wlimit = self.max_weekly_loss_pct * self.paper.starting_balance
            if wk <= -wlimit:
                return reject("weekly_loss", f"Weekly loss limit hit ({wk:+.2f} ≤ -{wlimit:.2f})")
            steps.append(Step("weekly_loss", True, f"week {wk:+.2f} / -{wlimit:.2f}"))

        # 3h. stop after N consecutive losses -> auto-halt new entries until Resume
        if self.max_consecutive_losses > 0 and not self._halted:
            streak = self._consecutive_losses()
            if streak >= self.max_consecutive_losses:
                self._engage_halt(f"{streak} consecutive losses (limit {self.max_consecutive_losses})")
                return reject("risk_guard", f"Auto-halt: {self._halt_reason}")

        # 3i. cooldown after a losing trade
        if self.cooldown_after_loss_min > 0:
            secs = self._since_last_loss()
            if secs is not None and secs < self.cooldown_after_loss_min * 60:
                left = int((self.cooldown_after_loss_min * 60 - secs) / 60) + 1
                return reject("cooldown", f"Cooldown after loss — ~{left}m left")

        # 3j. max trades per UTC day
        if self.max_trades_per_day > 0 and self._opens_today() >= self.max_trades_per_day:
            return reject("max_trades", f"Max {self.max_trades_per_day} trades/day reached")

        # 4. risk: position sizing from stop distance, scaled by conviction
        #    (confidence 1.0 -> full risk; 0.5 -> 75% risk; floors at 50%),
        #    then by the Kelly guard (risk less while the recent record is weak).
        if stop is None or stop == entry:
            return reject("risk", "Invalid stop (missing or equal to entry)")
        eff_risk = self.risk_per_trade_pct * (0.5 + 0.5 * confidence)
        kf = self._kelly_factor() if self.adaptive_risk else 1.0
        ef = self._equity_curve_factor() if self.equity_throttle else 1.0
        lf = self.learning.risk_multiplier(symbol) if self.learning is not None else 1.0
        af = float(self.allocator(symbol)) if self.allocator is not None else 1.0
        # context sizing (funding/sentiment modifiers) — bounded [0.5, 1.0]
        xf = max(0.5, min(1.0, float(payload.get("context_size_factor", 1.0) or 1.0)))
        sfm = (self.learning.side_multiplier(_dir(side))
               if self.learning is not None else 1.0)
        # edge boost: size up ONLY a proven winning pattern, and never while any
        # other factor is throttling down — defense always outranks offense.
        bf = 1.0
        if self.learning is not None and min(kf, ef, lf, econ_risk) >= 1.0:
            bf = self.learning.boost_multiplier(regime=payload.get("regime", ""),
                                                confidence=confidence)
        eff_risk *= kf * ef * lf * af * econ_risk * bf * xf * sfm
        size = size_position(self.equity, entry, stop, RiskRules(risk_per_trade_pct=eff_risk))
        if size <= 0:
            return reject("sizing", "Computed position size is zero")
        kelly_note = f" × kelly {kf:.2f}" if kf < 1.0 else ""
        curve_note = f" × curve {ef:.2f}" if ef < 1.0 else ""
        learned_note = f" × learned {lf:.2f}" if lf < 1.0 else ""
        alloc_note = f" × alloc {af:.2f}" if af != 1.0 else ""
        event_note = f" × event {econ_risk:.2f}" if econ_risk < 1.0 else ""
        edge_note = f" × edge {bf:.2f}" if bf > 1.0 else ""
        ctx_note = f" × context {xf:.2f}" if xf < 1.0 else ""
        side_note = f" × side {sfm:.2f}" if sfm < 1.0 else ""
        steps.append(Step("risk", True,
                          f"conf {confidence:.2f}{kelly_note}{curve_note}{learned_note}"
                          f"{alloc_note}{event_note}{edge_note}{ctx_note}{side_note}"
                          f" → risk {eff_risk*100:.2f}% sized {size:.6f}"))

        # 5. exposure limit (cap notional to the per-trade limit)
        max_size = (self.exposure_limit_pct * self.equity) / entry if entry > 0 else 0.0
        if size > max_size:
            size = max_size
            steps.append(Step("exposure", True, f"capped to {self.exposure_limit_pct*100:.0f}% exposure"))
        else:
            steps.append(Step("exposure", True, f"within {self.exposure_limit_pct*100:.0f}% exposure"))
        if size <= 0:
            return reject("exposure", "Exposure limit leaves zero size")

        # 5b. portfolio exposure cap — TOTAL open notional across all positions.
        # Per-trade limits alone still allow the book to stack up; this is the
        # portfolio-level ceiling every production bot enforces.
        if self.max_total_exposure_pct > 0:
            open_notional = sum(p["size"] * p["entry"] for p in self.paper.positions())
            budget = self.max_total_exposure_pct * self.equity - open_notional
            if budget <= 0:
                return reject("portfolio_exposure",
                              f"Portfolio exposure {open_notional:.0f} already at the "
                              f"{self.max_total_exposure_pct*100:.0f}% cap")
            if size * entry > budget:
                size = budget / entry
                steps.append(Step("portfolio_exposure", True,
                                  f"capped to remaining {budget:.0f} notional budget"))
            else:
                steps.append(Step("portfolio_exposure", True,
                                  f"total within {self.max_total_exposure_pct*100:.0f}%"))

        # 6. paper execution (routed through the fill model)
        fill = self.paper.open(symbol=symbol, side=side, size=size, entry=entry, stop=stop,
                               alert_id=alert_id, maker=bool(payload.get("maker")))
        if fill.action == "rejected":
            return reject("execution", "Order rejected at fill (execution model)")
        entry, size = fill.price, fill.size          # actual filled price / size
        self.ledger.insert_webhook_event(alert_id=alert_id, symbol=symbol, side=side,
                                          entry=entry, stop=stop, payload=payload, status="accepted")
        open_msg = f"{symbol} {side} opened {size:.6f} @ {entry}"
        if brain_reason:
            open_msg += f" | {brain_reason}"
        self.ledger.log(level="info", stage="execution", message=open_msg, symbol=symbol)
        self.ledger.add_alert(severity="info", category="trade",
                              title=f"Paper trade opened — {symbol}",
                              detail=(brain_reason or f"{side} {size:.6f} @ {entry}"))
        self._notify("trade", f"📈 {symbol} {side} opened", f"{size:.6f} @ {entry}")
        steps.append(Step("execution", True, f"opened {size:.6f} @ {entry}"))
        # full explainable decision journal for this trade (real data only)
        if self.journal is not None and fill.trade_id:
            try:
                self.journal.record_entry(
                    trade_id=fill.trade_id, mode=payload.get("mode", "paper"),
                    symbol=symbol, side=_dir(side),
                    strategy=payload.get("strategy", brain_reason.split(" ")[0] or "Strategy"),
                    timeframe=payload.get("timeframe", ""), entry=entry, stop=stop,
                    target=payload.get("target"), size=size, equity=self.equity,
                    confidence=confidence, brain_score=payload.get("brain_score"),
                    regime=payload.get("regime", ""), steps=steps, payload=payload)
            except Exception:  # noqa: BLE001 — journaling must never block trading
                pass
        # remember entry context so the learning loop can study this trade later
        if alert_id:
            self._alert_info[alert_id] = {"confidence": confidence,
                                          "regime": payload.get("regime", "")}
            if len(self._alert_info) > 500:
                self._alert_info.pop(next(iter(self._alert_info)))
        return PipelineResult(True, "execution", "paper trade opened", steps, fill.__dict__)

    # ----------------------------------------------------- auto risk guard
    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def resume(self) -> None:
        """Clear an auto-halt and rebaseline drawdown to the current equity
        (called by the manual Resume control)."""
        self._halted = False
        self._halt_reason = ""
        self._dd_base_balance = self.paper.balance()
        self._dd_base_count = len(self.paper.history())

    @staticmethod
    def _entry_hour(ts: Optional[str]) -> int:
        try:
            if ts:
                return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc).hour
        except Exception:  # noqa: BLE001 — unparseable -> use now
            pass
        return datetime.now(timezone.utc).hour

    @staticmethod
    def _entry_weekday(ts: Optional[str]) -> int:
        try:
            if ts:
                return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc).weekday()
        except Exception:  # noqa: BLE001
            pass
        return datetime.now(timezone.utc).weekday()

    @staticmethod
    def _pnl_on_day(trades, day: str) -> float:
        return sum((t.get("pnl") or 0.0) for t in trades if (t.get("closed_at") or "")[:10] == day)

    def _today_pnl(self) -> float:
        """Net realized P&L for the current UTC day (resets at the day boundary)."""
        day = datetime.now(timezone.utc).date().isoformat()
        return self._pnl_on_day(self.paper.history(), day)

    def _week_pnl(self) -> float:
        """Net realized P&L for the current ISO week (resets each week)."""
        y, w, _ = datetime.now(timezone.utc).isocalendar()
        total = 0.0
        for t in self.paper.history():
            try:
                d = datetime.fromisoformat((t.get("closed_at") or "").replace("Z", "+00:00"))
                ty, tw, _ = d.isocalendar()
                if ty == y and tw == w:
                    total += t.get("pnl") or 0.0
            except Exception:  # noqa: BLE001
                continue
        return total

    def _consecutive_losses(self) -> int:
        n = 0
        for t in sorted(self.paper.history(), key=lambda x: x.get("closed_at") or "", reverse=True):
            if (t.get("pnl") or 0.0) < 0:
                n += 1
            else:
                break
        return n

    def _since_last_loss(self) -> Optional[float]:
        """Seconds since the most recent losing trade closed, or None."""
        losses = [t for t in self.paper.history() if (t.get("pnl") or 0.0) < 0 and t.get("closed_at")]
        if not losses:
            return None
        last = max(losses, key=lambda t: t["closed_at"])
        try:
            d = datetime.fromisoformat(last["closed_at"].replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - d).total_seconds()
        except Exception:  # noqa: BLE001
            return None

    def _opens_today(self) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        return sum(1 for t in self.ledger.get_paper_trades()
                   if (t.get("opened_at") or "")[:10] == day)

    def _drawdown_trip(self) -> Optional[str]:
        """Return a reason if realized-equity drawdown (since the last baseline)
        breaches the limit."""
        ordered = sorted(self.paper.history(), key=lambda t: t.get("closed_at") or "")
        ordered = ordered[self._dd_base_count:]
        if not ordered:
            return None
        base = self._dd_base_balance
        eq = [base]
        run = base
        for t in ordered:
            run += (t.get("pnl") or 0.0)
            eq.append(run)
        from bot.metrics import max_drawdown
        from risk.drawdown_guard import breached
        if breached(eq, self.max_drawdown_pct):
            return (f"Max drawdown breached "
                    f"({max_drawdown(eq) * 100:.1f}% > {self.max_drawdown_pct * 100:.0f}%)")
        return None

    def alert_context(self) -> dict:
        """alert_id -> {confidence, regime} for the learning loop. Restarts
        used to wipe this (it was memory-only), starving the regime and
        conviction lessons; it now rehydrates once from the ledger's webhook
        events, where every accepted entry's payload is already persisted."""
        if not self._alert_info_hydrated:
            self._alert_info_hydrated = True
            try:
                for ev in self.ledger.get_webhook_events(limit=500):
                    if ev.get("status") != "accepted":
                        continue
                    p = ev.get("payload") or {}
                    aid = ev.get("alert_id") or ""
                    if aid and aid not in self._alert_info and (
                            "confidence" in p or "regime" in p):
                        self._alert_info[aid] = {
                            "confidence": float(p.get("confidence", 1.0) or 1.0),
                            "regime": p.get("regime", "")}
            except Exception:  # noqa: BLE001 — hydration is best-effort
                pass
        return self._alert_info

    def _kelly_factor(self, min_trades: int = 20, lookback: int = 40) -> float:
        """Kelly-capped risk multiplier from the bot's own recent closed trades.

        Professional sizing: the per-trade risk should never exceed a fraction
        of the Kelly optimum implied by the recent win rate and payoff ratio.
        With a healthy record the factor is 1.0 (no change). As the recent edge
        deteriorates it scales risk down smoothly, floored at 0.25 — the bot
        digs shallower holes when it is trading badly, exactly when equity
        needs protecting. With fewer than ``min_trades`` closed trades there is
        no evidence either way, so sizing is untouched.
        """
        # history() is newest-first — the first `lookback` entries are the recent ones
        closed = [t for t in self.paper.history() if t.get("rr") is not None]
        recent = [float(t["rr"]) for t in closed[:lookback]]
        if len(recent) < min_trades:
            return 1.0
        wins = [r for r in recent if r > 0]
        losses = [-r for r in recent if r < 0]
        if not losses:
            return 1.0
        if not wins:
            return 0.25
        w = len(wins) / len(recent)
        payoff = (sum(wins) / len(wins)) / (sum(losses) / len(losses))
        kelly = w - (1.0 - w) / payoff if payoff > 0 else 0.0
        if kelly <= 0:          # negative edge lately — trade at quarter risk
            return 0.25
        # quarter-Kelly cap: full risk only when 0.25*kelly covers the base risk
        return max(0.25, min(1.0, 0.25 * kelly / self.risk_per_trade_pct))

    def _equity_curve_factor(self, lookback: int = 10) -> float:
        """Equity-curve throttle: trade half size while the bot's own equity
        curve is below its recent average (prop-desk practice — the system's
        equity curve is itself a signal about whether the edge is working in
        current conditions). Full size resumes as soon as the curve recovers.
        """
        closed = self.paper.history()   # newest-first
        if len(closed) < lookback:
            return 1.0
        balance = self.paper.starting_balance
        curve = []
        for t in reversed(closed):      # chronological equity curve
            balance += t.get("pnl") or 0.0
            curve.append(balance)
        sma = sum(curve[-lookback:]) / lookback
        return 0.5 if curve[-1] < sma else 1.0

    def _notify(self, kind: str, title: str, detail: str = "") -> None:
        if self.notifier:
            try:
                self.notifier(kind, title, detail)
            except Exception:  # noqa: BLE001 — notifications never break trading
                pass

    def _engage_halt(self, reason: str) -> None:
        self._halted = True
        self._halt_reason = reason
        self.ledger.log(level="error", stage="risk_guard",
                        message=f"AUTO-HALT — {reason}; new entries blocked until Resume")
        self.ledger.add_alert(severity="critical", category="risk",
                              title="Auto-halt — drawdown circuit breaker", detail=reason)
        self._notify("risk", "🛑 Auto-halt", reason)
