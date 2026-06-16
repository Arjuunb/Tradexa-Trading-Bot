"""Signal Pipeline (Phase 1) — the brain that turns a TradingView alert into a
paper trade, safely and transparently.

    alert -> [controls] -> [dedup] -> [risk + sizing] -> [paper execution]
          -> ledger (webhook_events, positions, paper_trades, bot_logs, alerts)

Every stage records a decision step (passed/failed + reason) so the Logs page
shows exactly why a trade executed or was rejected. No real broker is touched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from database.models import RiskRules
from data.ledger import Ledger
from execution.paper_engine import PaperExecutionEngine, _dir
from risk.position_sizing import size_position
from services.controls import TradingControl
from services.dedup import DuplicateGuard


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
    ):
        self.ledger = ledger
        self.paper = paper
        self.controls = controls
        self.equity = equity
        self.risk_per_trade_pct = risk_per_trade_pct
        self.exposure_limit_pct = exposure_limit_pct
        self.dedup = DuplicateGuard(ledger, dedup_window_s)

    def process(self, payload: dict) -> PipelineResult:
        symbol = payload["symbol"]
        side = str(payload["side"]).upper()
        entry = float(payload["entry"])
        stop = payload.get("stop")
        stop = float(stop) if stop is not None else None
        alert_id = payload.get("alert_id", "")
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
            steps.append(Step("execution", True, f"closed PnL {fill.pnl:+.2f}"))
            return PipelineResult(True, "execution", "position closed", steps, fill.__dict__)

        # 3b. OPEN — no pyramiding in Phase 1
        if existing is not None:
            return reject("execution", f"Position already open on {symbol} (no pyramiding)")

        # 4. risk: position sizing from stop distance
        if stop is None or stop == entry:
            return reject("risk", "Invalid stop (missing or equal to entry)")
        size = size_position(self.equity, entry, stop, RiskRules(risk_per_trade_pct=self.risk_per_trade_pct))
        if size <= 0:
            return reject("sizing", "Computed position size is zero")
        steps.append(Step("risk", True, f"risk {self.risk_per_trade_pct*100:.2f}% sized {size:.6f}"))

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
        self.ledger.log(level="info", stage="execution",
                        message=f"{symbol} {side} opened {size:.6f} @ {entry}", symbol=symbol)
        self.ledger.add_alert(severity="info", category="trade",
                              title=f"Paper trade opened — {symbol}", detail=f"{side} {size:.6f} @ {entry}")
        steps.append(Step("execution", True, f"opened {size:.6f} @ {entry}"))
        return PipelineResult(True, "execution", "paper trade opened", steps, fill.__dict__)
