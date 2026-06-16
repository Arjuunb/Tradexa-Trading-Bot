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
from services.auto_engine import AutoStrategyEngine
from services.controls import TradingControl
from services.market_quality import MarketQualityConfig, MarketQualityGate
from services.signal_pipeline import SignalPipeline

# --- Phase 1 singletons (one ledger / paper account / control switch) ---
ledger = get_ledger(settings.ledger_path)
controls = TradingControl()
paper = PaperExecutionEngine(ledger, settings.starting_cash)
quality = MarketQualityGate(MarketQualityConfig(
    min_stop_distance_pct=settings.quality_min_stop_pct,
    max_stop_distance_pct=settings.quality_max_stop_pct,
    max_signal_age_s=settings.quality_max_signal_age_s,
    max_spread_bps=settings.quality_max_spread_bps,
))
pipeline = SignalPipeline(
    ledger, paper, controls,
    equity=settings.starting_cash,
    risk_per_trade_pct=settings.risk_per_trade_pct,
    exposure_limit_pct=settings.exposure_limit_pct,
    dedup_window_s=settings.dedup_window_s,
    quality=quality,
    max_drawdown_pct=settings.max_drawdown_pct,
    max_open_positions=settings.max_open_positions,
)
# Autonomous engine: real strategy signals -> the same pipeline (paper-only).
# Default brain is the multi-signal DecisionBrain; HUB_AUTO_STRATEGY=ema selects
# the simple EMA crossover instead.
def _make_strategy(symbol: str):
    s = settings.auto_strategy
    if s == "ema":
        from strategies.ema_strategy import EMAStrategy
        return EMAStrategy(symbol)
    if s == "supertrend":
        from strategies.supertrend_strategy import SupertrendStrategy
        return SupertrendStrategy(symbol)
    if s == "donchian":
        from strategies.donchian_strategy import DonchianStrategy
        return DonchianStrategy(symbol)
    if s == "ensemble":
        from strategies.ensemble_strategy import ConfirmationEnsemble
        return ConfirmationEnsemble(symbol)
    from strategies.brain_strategy import DecisionBrain
    return DecisionBrain(symbol)


engine = AutoStrategyEngine(
    pipeline, paper, ledger,
    symbols=list(settings.auto_symbols),
    timeframe=settings.auto_timeframe,
    interval=settings.auto_interval,
    strategy_factory=_make_strategy,
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
    pipeline.resume()          # also clear any auto-halt (drawdown breaker)
    ledger.log(level="info", stage="controls", message="RESUME — trading active")
    return {"state": controls.state, "auto_halted": pipeline.halted}


# ---------------------------------------------------- autonomous engine
@router.post("/engine/start")
def engine_start(x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    started = engine.start()
    return {"started": started, "status": engine.status()}


@router.post("/engine/stop")
def engine_stop(x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    stopped = engine.stop()
    return {"stopped": stopped, "status": engine.status()}


@router.get("/engine/status")
def engine_status():
    return engine.status()


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


@router.get("/paper/equity-curve")
def paper_equity_curve():
    """Realized-equity curve: starting balance + cumulative closed-trade P&L."""
    trades = sorted((t for t in paper.history() if t.get("closed_at")),
                    key=lambda t: t["closed_at"])
    eq = paper.starting_balance
    points = [{"t": None, "equity": round(eq, 2)}]
    for t in trades:
        eq += (t.get("pnl") or 0.0)
        points.append({"t": t.get("closed_at"), "equity": round(eq, 2)})
    return {"starting_balance": paper.starting_balance, "points": points}


@router.get("/risk/summary")
def risk_summary():
    """Live risk usage: exposure vs limit, open trades vs max, rejections."""
    positions = paper.positions()
    equity = paper.balance()
    notional = sum((p["size"] * p["entry"]) for p in positions)
    st = engine.status()
    return {
        "equity": equity,
        "realized_pnl": paper.realized_pnl(),
        "open_positions": len(positions),
        "max_open_positions": settings.max_open_positions,
        "exposure_notional": notional,
        "exposure_pct": (notional / equity) if equity > 0 else 0.0,
        "exposure_limit_pct": settings.exposure_limit_pct,
        "risk_per_trade_pct": settings.risk_per_trade_pct,
        "rejections": st.get("rejections", 0),
        "signals": st.get("signals", 0),
        "trading_state": controls.state,
        "engine_running": st.get("running", False),
        "max_drawdown_pct": settings.max_drawdown_pct,
        "auto_halted": pipeline.halted,
        "halt_reason": pipeline.halt_reason,
    }


@router.get("/bots/live")
def bots_live():
    """Each engine symbol as a live 'bot' with real per-symbol stats."""
    history = paper.history()
    st = engine.status()
    running = st.get("running", False)
    out = []
    for sym in engine.symbols:
        sym_trades = [t for t in history if t["symbol"] == sym]
        wins = sum(1 for t in sym_trades if (t.get("pnl") or 0) > 0)
        realized = sum((t.get("pnl") or 0.0) for t in sym_trades)
        pos = paper.open_position(sym)
        if not controls.trading_allowed():
            status = controls.state            # Paused / Stopped
        else:
            status = "Running" if running else "Stopped"
        out.append({
            "id": sym, "symbol": sym, "name": f"{sym} · {engine.strategy_label}",
            "strategy": engine.strategy_label, "timeframe": engine.timeframe, "status": status,
            "open": pos is not None,
            "side": pos["side"] if pos else None,
            "size": pos["size"] if pos else 0.0,
            "entry": pos["entry"] if pos else 0.0,
            "num_trades": len(sym_trades),
            "win_rate": (wins / len(sym_trades)) if sym_trades else 0.0,
            "realized_pnl": round(realized, 2),
        })
    return out
