"""Webhook + ledger API (Kyros Phase 1).

Public, secret-gated endpoint that receives TradingView alerts and runs the
signal pipeline (dedup -> risk -> sizing -> paper execution -> ledger). Plus
emergency controls (Pause/Stop/Resume) and read endpoints the dashboard uses.

Mounted on the existing FastAPI app via ``app.include_router(router)``.
"""
from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from config import settings
from data.ledger import get_ledger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline

# --- Phase 1 singletons (one ledger / paper account / control switch) ---
ledger = get_ledger(settings.ledger_path)
controls = TradingControl()
paper = PaperExecutionEngine(ledger, settings.starting_cash)
pipeline = SignalPipeline(
    ledger, paper, controls,
    equity=settings.starting_cash,
    risk_per_trade_pct=settings.risk_per_trade_pct,
    exposure_limit_pct=settings.exposure_limit_pct,
    dedup_window_s=settings.dedup_window_s,
)

router = APIRouter()


class WebhookPayload(BaseModel):
    alert_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    side: str
    entry: float
    stop: Optional[float] = None
    timestamp: Optional[str] = None


def _check_secret(secret: Optional[str]) -> None:
    if not secret or not hmac.compare_digest(secret, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")


# ------------------------------------------------------------------- webhook
@router.post("/webhook/tradingview")
def tradingview_webhook(payload: WebhookPayload,
                        x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    result = pipeline.process(payload.model_dump())
    return {"status": "ok", **result.to_dict()}


# ------------------------------------------------------- emergency controls
@router.post("/controls/pause-all")
def pause_all(x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    controls.pause_all()
    ledger.log(level="warning", stage="controls", message="PAUSE ALL — entries blocked")
    return {"state": controls.state}


@router.post("/controls/stop-all")
def stop_all(x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    controls.stop_all()
    ledger.log(level="warning", stage="controls", message="STOP ALL — trading halted")
    return {"state": controls.state}


@router.post("/controls/resume")
def resume(x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    controls.resume()
    ledger.log(level="info", stage="controls", message="RESUME — trading active")
    return {"state": controls.state}


# ------------------------------------------------------------- read (dashboard)
@router.get("/controls/state")
def control_state():
    return {"state": controls.state}


@router.get("/paper/account")
def paper_account():
    return {
        "starting_balance": paper.starting_balance,
        "balance": paper.balance(),
        "realized_pnl": paper.realized_pnl(),
        "open_positions": len(paper.positions()),
    }


@router.get("/paper/positions")
def paper_positions():
    return paper.positions()


@router.get("/paper/trades")
def paper_trades():
    return paper.history()


@router.get("/ledger/logs")
def ledger_logs(limit: int = 200):
    return ledger.get_logs(limit)


@router.get("/ledger/alerts")
def ledger_alerts(limit: int = 100):
    return ledger.get_alerts(limit)
