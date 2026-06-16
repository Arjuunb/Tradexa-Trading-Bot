"""Webhook + ledger API (Kyros Phase 1).

Public, secret-gated endpoint that receives TradingView alerts and runs the
signal pipeline (dedup -> risk -> sizing -> paper execution -> ledger). Plus
emergency controls (Pause/Stop/Resume) and read endpoints the dashboard uses.

Mounted on the existing FastAPI app via ``app.include_router(router)``.
"""
from __future__ import annotations

import hmac
import time
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
_BOOT = time.time()
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
    live=settings.use_live_data,
    live_poll_s=settings.live_poll_s,
)

# Apply persisted runtime overrides (risk/exposure/drawdown) on top of env defaults.
from services.runtime_settings import load_overrides, save_overrides  # noqa: E402
for _k, _v in load_overrides(settings.settings_path).items():
    setattr(pipeline, _k, _v)

router = APIRouter()


class SettingsUpdate(BaseModel):
    risk_per_trade_pct: Optional[float] = None
    exposure_limit_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None


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


@router.get("/system/status")
def system_status():
    """Real bot/system health — no fabricated values. Paper-only until a live
    broker is wired (live execution is a future phase)."""
    st = engine.status()
    return {
        "mode": "paper",                     # the engine paper-executes; no live broker
        "broker_connected": False,           # honest: no live venue connected
        "data_source": "live (ccxt)" if engine.live else "synthetic / replay",
        "engine_running": st.get("running", False),
        "engine_mode": st.get("mode"),
        "strategy": engine.strategy_label,
        "symbols": engine.symbols,
        "timeframe": engine.timeframe,
        "bars_processed": st.get("bars", 0),
        "signals": st.get("signals", 0),
        "trades": st.get("trades", 0),
        "started_at": st.get("started_at"),
        "uptime_s": round(time.time() - _BOOT, 0),
        "trading_state": controls.state,
        "auto_halted": pipeline.halted,
        "halt_reason": pipeline.halt_reason,
    }


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


_STRATEGY_CATALOG = [
    {"key": "brain", "label": "Decision Brain",
     "desc": "Multi-factor trend: EMA trend + filter, momentum, RSI, regime; conviction-weighted sizing"},
    {"key": "supertrend", "label": "Supertrend", "desc": "ATR trend-following indicator"},
    {"key": "donchian", "label": "Donchian Breakout", "desc": "Classic Turtle channel breakout"},
    {"key": "ensemble", "label": "Confirmation Ensemble",
     "desc": "Trades only when 2 of 3 agree (EMA + Supertrend + Donchian)"},
    {"key": "ema", "label": "EMA Crossover", "desc": "Simple fast/slow EMA cross"},
]


@router.get("/settings")
def get_settings():
    """Real current configuration. `editable` persists; `readonly` is env-set."""
    return {
        "editable": {
            "risk_per_trade_pct": pipeline.risk_per_trade_pct,
            "exposure_limit_pct": pipeline.exposure_limit_pct,
            "max_drawdown_pct": pipeline.max_drawdown_pct,
        },
        "readonly": {
            "strategy": engine.strategy_label,
            "strategy_key": settings.auto_strategy,
            "timeframe": engine.timeframe,
            "symbols": engine.symbols,
            "starting_cash": paper.starting_balance,
            "max_open_positions": pipeline.max_open_positions,
            "dedup_window_s": settings.dedup_window_s,
            "data_source": "live (ccxt)" if engine.live else "synthetic / replay",
            "mode": "paper",
            "broker_connected": False,
            "webhook_secret_set": bool(settings.webhook_secret),
        },
    }


@router.post("/settings")
def update_settings(body: SettingsUpdate, x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    changed = {}
    if body.risk_per_trade_pct is not None:
        if not (0 < body.risk_per_trade_pct <= 0.5):
            raise HTTPException(400, "risk_per_trade_pct must be in (0, 0.5]")
        pipeline.risk_per_trade_pct = body.risk_per_trade_pct
        changed["risk_per_trade_pct"] = body.risk_per_trade_pct
    if body.exposure_limit_pct is not None:
        if not (0 < body.exposure_limit_pct <= 1):
            raise HTTPException(400, "exposure_limit_pct must be in (0, 1]")
        pipeline.exposure_limit_pct = body.exposure_limit_pct
        changed["exposure_limit_pct"] = body.exposure_limit_pct
    if body.max_drawdown_pct is not None:
        if not (0 < body.max_drawdown_pct <= 1):
            raise HTTPException(400, "max_drawdown_pct must be in (0, 1]")
        pipeline.max_drawdown_pct = body.max_drawdown_pct
        changed["max_drawdown_pct"] = body.max_drawdown_pct

    current = {
        "risk_per_trade_pct": pipeline.risk_per_trade_pct,
        "exposure_limit_pct": pipeline.exposure_limit_pct,
        "max_drawdown_pct": pipeline.max_drawdown_pct,
    }
    save_overrides(settings.settings_path, current)
    ledger.log(level="info", stage="settings", message=f"Settings updated: {changed}")
    return {"saved": True, "editable": current}


@router.get("/strategy/list")
def strategy_list():
    """Real list of selectable engine strategies + which one is active."""
    return {"active": settings.auto_strategy, "timeframe": engine.timeframe,
            "strategies": _STRATEGY_CATALOG}


@router.get("/strategy/performance")
def strategy_performance():
    """The bot's live paper-trading track record (real executed trades)."""
    from services.performance import summarize
    stats = summarize(paper.history(), paper.starting_balance)
    stats["strategy"] = engine.strategy_label
    stats["mode"] = "live" if engine.live else "replay"
    return stats


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
