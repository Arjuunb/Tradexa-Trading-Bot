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
        # Optional notification hook: callable(kind, title, detail). Best-effort.
        self.notifier = None
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

        def reject(stage: str, reason: str, status: str = "rejected") -> PipelineResult:
            steps.append(Step(stage, False, reason))
            self.ledger.insert_webhook_event(alert_id=alert_id, symbol=symbol, side=side,
                                              entry=entry, stop=stop, payload=payload,
                                              status=status, reason=reason)
            self.ledger.log(level="warning", stage=stage, message=f"{symbol} {side} rejected: {reason}", symbol=symbol)
            self.ledger.add_alert(severity="warning", category="trade",
                                  title=f"Trade rejected — {symbol}", detail=reason)
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
            fill = self.paper.close(symbol=symbol, exit_price=entry)
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
            return PipelineResult(True, "execution", "position closed", steps, fill.__dict__)

        # 3b. OPEN — no pyramiding in Phase 1
        if existing is not None:
            return reject("execution", f"Position already open on {symbol} (no pyramiding)")

        # 3c. portfolio cap — limit concurrent open positions
        if len(self.paper.positions()) >= self.max_open_positions:
            return reject("risk_guard", f"Max open positions ({self.max_open_positions}) reached")

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
        #    (confidence 1.0 -> full risk; 0.5 -> 75% risk; floors at 50%).
        if stop is None or stop == entry:
            return reject("risk", "Invalid stop (missing or equal to entry)")
        eff_risk = self.risk_per_trade_pct * (0.5 + 0.5 * confidence)
        size = size_position(self.equity, entry, stop, RiskRules(risk_per_trade_pct=eff_risk))
        if size <= 0:
            return reject("sizing", "Computed position size is zero")
        steps.append(Step("risk", True,
                          f"conf {confidence:.2f} → risk {eff_risk*100:.2f}% sized {size:.6f}"))

        # 5. exposure limit (cap notional to the per-trade limit)
        max_size = (self.exposure_limit_pct * self.equity) / entry if entry > 0 else 0.0
        if size > max_size:
            size = max_size
            steps.append(Step("exposure", True, f"capped to {self.exposure_limit_pct*100:.0f}% exposure"))
        else:
            steps.append(Step("exposure", True, f"within {self.exposure_limit_pct*100:.0f}% exposure"))
        if size <= 0:
            return reject("exposure", "Exposure limit leaves zero size")

        # 6. paper execution
        fill = self.paper.open(symbol=symbol, side=side, size=size, entry=entry, stop=stop, alert_id=alert_id)
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
