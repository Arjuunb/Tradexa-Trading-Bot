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
    max_daily_loss_pct=settings.max_daily_loss_pct,
    session_start=settings.session_start,
    session_end=settings.session_end,
    max_weekly_loss_pct=settings.max_weekly_loss_pct,
    max_trades_per_day=settings.max_trades_per_day,
    max_consecutive_losses=settings.max_consecutive_losses,
    cooldown_after_loss_min=settings.cooldown_after_loss_min,
    trading_days_mask=settings.trading_days_mask,
)
# Telegram notifications (best-effort) -> routed from pipeline events.
from services.notifier import Notifier  # noqa: E402
notifier = Notifier(settings.telegram_token, settings.telegram_chat_id)
pipeline.notifier = notifier.dispatch

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

# Apply persisted runtime overrides on top of env defaults.
from services.runtime_settings import load_overrides, save_overrides  # noqa: E402


def _apply_setting(key: str, value) -> None:
    if key in ("notify_trades", "notify_risk"):
        setattr(notifier, key, bool(int(value)))
    elif key == "dedup_window_s":
        pipeline.dedup.window_seconds = int(value)
    elif key in ("max_open_positions", "session_start", "session_end",
                 "max_trades_per_day", "max_consecutive_losses", "cooldown_after_loss_min",
                 "trading_days_mask"):
        setattr(pipeline, key, int(value))
    else:  # *_pct float settings
        setattr(pipeline, key, float(value))


def _settings_snapshot() -> dict:
    return {
        "risk_per_trade_pct": pipeline.risk_per_trade_pct,
        "exposure_limit_pct": pipeline.exposure_limit_pct,
        "max_drawdown_pct": pipeline.max_drawdown_pct,
        "max_open_positions": pipeline.max_open_positions,
        "dedup_window_s": pipeline.dedup.window_seconds,
        "max_daily_loss_pct": pipeline.max_daily_loss_pct,
        "session_start": pipeline.session_start,
        "session_end": pipeline.session_end,
        "max_weekly_loss_pct": pipeline.max_weekly_loss_pct,
        "max_trades_per_day": pipeline.max_trades_per_day,
        "max_consecutive_losses": pipeline.max_consecutive_losses,
        "cooldown_after_loss_min": pipeline.cooldown_after_loss_min,
        "trading_days_mask": pipeline.trading_days_mask,
        "notify_trades": 1 if notifier.notify_trades else 0,
        "notify_risk": 1 if notifier.notify_risk else 0,
    }


for _k, _v in load_overrides(settings.settings_path).items():
    _apply_setting(_k, _v)

router = APIRouter()


class SettingsUpdate(BaseModel):
    risk_per_trade_pct: Optional[float] = None
    exposure_limit_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    dedup_window_s: Optional[int] = None
    max_daily_loss_pct: Optional[float] = None
    session_start: Optional[int] = None
    session_end: Optional[int] = None
    max_weekly_loss_pct: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    max_consecutive_losses: Optional[int] = None
    cooldown_after_loss_min: Optional[int] = None
    trading_days_mask: Optional[int] = None


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


def _export(rows: list, fields: list, fmt: str, name: str):
    import csv as _csv
    import io
    import json as _json
    from fastapi.responses import Response
    if fmt == "json":
        return Response(_json.dumps(rows, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename={name}.json"})
    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fields})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}.csv"})


@router.get("/ledger/logs/export")
def export_logs(fmt: str = "csv", limit: int = 2000):
    return _export(ledger.get_logs(limit), ["ts", "level", "stage", "symbol", "message"], fmt, "decision_logs")


@router.get("/ledger/alerts/export")
def export_alerts(fmt: str = "csv", limit: int = 1000):
    return _export(ledger.get_alerts(limit), ["ts", "severity", "category", "title", "detail"], fmt, "alerts")


@router.get("/paper/trades/export")
def export_trades(fmt: str = "csv"):
    return _export(paper.history(), ["symbol", "side", "size", "entry", "exit", "pnl", "rr",
                                     "opened_at", "closed_at"], fmt, "paper_trades")


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
            "max_open_positions": pipeline.max_open_positions,
            "dedup_window_s": pipeline.dedup.window_seconds,
            "max_daily_loss_pct": pipeline.max_daily_loss_pct,
            "session_start": pipeline.session_start,
            "session_end": pipeline.session_end,
            "max_weekly_loss_pct": pipeline.max_weekly_loss_pct,
            "max_trades_per_day": pipeline.max_trades_per_day,
            "max_consecutive_losses": pipeline.max_consecutive_losses,
            "cooldown_after_loss_min": pipeline.cooldown_after_loss_min,
            "trading_days_mask": pipeline.trading_days_mask,
        },
        "readonly": {
            "strategy": engine.strategy_label,
            "strategy_key": settings.auto_strategy,
            "timeframe": engine.timeframe,
            "symbols": engine.symbols,
            "starting_cash": paper.starting_balance,
            "data_source": "live (ccxt)" if engine.live else "synthetic / replay",
            "poll_seconds": engine.live_poll_s if engine.live else None,
            "mode": "paper",
            "broker_connected": False,
            "webhook_secret_set": bool(settings.webhook_secret),
            "telegram_configured": bool(settings.telegram_token),
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
    if body.max_open_positions is not None:
        if not (1 <= body.max_open_positions <= 50):
            raise HTTPException(400, "max_open_positions must be in [1, 50]")
        pipeline.max_open_positions = int(body.max_open_positions)
        changed["max_open_positions"] = int(body.max_open_positions)
    if body.dedup_window_s is not None:
        if not (0 <= body.dedup_window_s <= 86400):
            raise HTTPException(400, "dedup_window_s must be in [0, 86400]")
        pipeline.dedup.window_seconds = int(body.dedup_window_s)
        changed["dedup_window_s"] = int(body.dedup_window_s)
    if body.max_daily_loss_pct is not None:
        if not (0 <= body.max_daily_loss_pct <= 1):
            raise HTTPException(400, "max_daily_loss_pct must be in [0, 1]")
        pipeline.max_daily_loss_pct = float(body.max_daily_loss_pct)
        changed["max_daily_loss_pct"] = float(body.max_daily_loss_pct)
    if body.session_start is not None:
        if not (0 <= body.session_start <= 24):
            raise HTTPException(400, "session_start must be in [0, 24]")
        pipeline.session_start = int(body.session_start)
        changed["session_start"] = int(body.session_start)
    if body.session_end is not None:
        if not (0 <= body.session_end <= 24):
            raise HTTPException(400, "session_end must be in [0, 24]")
        pipeline.session_end = int(body.session_end)
        changed["session_end"] = int(body.session_end)
    if body.max_weekly_loss_pct is not None:
        if not (0 <= body.max_weekly_loss_pct <= 1):
            raise HTTPException(400, "max_weekly_loss_pct must be in [0, 1]")
        pipeline.max_weekly_loss_pct = float(body.max_weekly_loss_pct)
        changed["max_weekly_loss_pct"] = float(body.max_weekly_loss_pct)
    for k in ("max_trades_per_day", "max_consecutive_losses", "cooldown_after_loss_min"):
        v = getattr(body, k)
        if v is not None:
            if not (0 <= v <= 1000):
                raise HTTPException(400, f"{k} must be in [0, 1000]")
            setattr(pipeline, k, int(v))
            changed[k] = int(v)
    if body.trading_days_mask is not None:
        if not (0 <= body.trading_days_mask <= 127):
            raise HTTPException(400, "trading_days_mask must be in [0, 127]")
        pipeline.trading_days_mask = int(body.trading_days_mask)
        changed["trading_days_mask"] = int(body.trading_days_mask)

    snap = _settings_snapshot()
    save_overrides(settings.settings_path, snap)
    ledger.log(level="info", stage="audit", message=f"Settings updated: {changed}")
    return {"saved": True, "editable": snap}


class NotifUpdate(BaseModel):
    notify_trades: Optional[bool] = None
    notify_risk: Optional[bool] = None


@router.get("/notifications/status")
def notifications_status():
    return {
        "telegram_configured": notifier.configured,
        "notify_trades": notifier.notify_trades,
        "notify_risk": notifier.notify_risk,
        "email": "not configured", "discord": "not configured",
    }


@router.post("/notifications/test")
def notifications_test(x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    sent = notifier.send("✅ Automation Hub — test notification")
    return {"sent": sent, "configured": notifier.configured}


@router.post("/notifications")
def notifications_update(body: NotifUpdate, x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    if body.notify_trades is not None:
        notifier.notify_trades = bool(body.notify_trades)
    if body.notify_risk is not None:
        notifier.notify_risk = bool(body.notify_risk)
    save_overrides(settings.settings_path, _settings_snapshot())
    return {"notify_trades": notifier.notify_trades, "notify_risk": notifier.notify_risk}


# ------------------------------------------------- custom strategy builder
from services.custom_store import CustomStore  # noqa: E402
custom_store = CustomStore(settings.custom_path)


class SimRequest(BaseModel):
    spec: dict
    bars: int = 3000


@router.post("/strategy/custom/simulate")
def custom_simulate(body: SimRequest):
    """Run a user-built strategy spec over REAL historical data (simulation only).

    The TradeBrain quality filter is ON by default so weak setups are blocked
    and reported. Pass ``spec["quality_filter"] = false`` to see raw, unfiltered
    results, or set ``spec["min_score"]`` to tune the threshold (default 60).
    """
    from strategies.custom import simulate, validate, describe, _stop_distance
    from strategies.brain import TradeBrain
    from strategies.diagnosis import diagnose
    from data.market_data import get_bars
    spec = body.spec
    symbol = spec.get("symbol", "BTCUSDT")
    timeframe = spec.get("timeframe", "4h")
    n = max(300, min(int(body.bars or 3000), 10000))
    rows, source = get_bars(symbol, n=n, timeframe=timeframe)

    use_brain = spec.get("quality_filter", True)
    min_score = int(spec.get("min_score", 60))
    brain = TradeBrain() if use_brain else None
    # Default to safer exits (break-even after +1R) unless the spec overrides.
    if use_brain and "exit" not in spec:
        spec = {**spec, "exit": {"breakeven_at_r": 1.0}}
    results = simulate(spec, rows, brain=brain, min_score=min_score if use_brain else 0)
    results["diagnosis"] = diagnose(results, results.get("blocked"))

    # Pre-trade position-sizing calculation on the latest bar (real numbers).
    equity = settings.starting_cash
    risk_pct = float(spec.get("risk_per_trade_pct", 0.01))
    entry = rows[-1].close
    stop_dist = _stop_distance(spec.get("stop") or {}, entry, rows, len(rows) - 1)
    risk_dollars = equity * risk_pct
    size = (risk_dollars / stop_dist) if stop_dist > 0 else 0.0
    notional = size * entry
    sizing = {
        "model": "percent_risk", "equity": equity, "risk_pct": risk_pct,
        "entry": round(entry, 6), "stop_distance": round(stop_dist, 6),
        "risk_dollars": round(risk_dollars, 2), "position_size": round(size, 6),
        "notional": round(notional, 2), "leverage_x": round(notional / equity, 2) if equity else 0,
    }
    return {
        "results": results,
        "warnings": validate(spec, results),
        "description": describe(spec),
        "sizing": sizing,
        "data_source": source,
        "symbol": symbol, "timeframe": timeframe,
        "label": "Simulation Result",
        "brain": {"quality_filter": bool(use_brain), "min_score": min_score,
                  "blocked_count": results.get("blocked_count", 0)},
    }


@router.post("/strategy/custom/optimize")
def custom_optimize(body: SimRequest):
    """Train/test optimisation. Honest: flags results overfit unless the unseen
    validation period also improves. Optimises min score / RR / ATR stop only."""
    from strategies.optimize import walk_forward
    from data.market_data import get_bars
    spec = body.spec
    symbol = spec.get("symbol", "BTCUSDT")
    timeframe = spec.get("timeframe", "4h")
    n = max(600, min(int(body.bars or 4000), 10000))
    rows, source = get_bars(symbol, n=n, timeframe=timeframe)
    report = walk_forward(spec, rows)
    report["data_source"] = source
    report["symbol"] = symbol
    report["timeframe"] = timeframe
    return report


@router.get("/strategy/custom")
def custom_list():
    return custom_store.list()


@router.post("/strategy/custom")
def custom_save(spec: dict, x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    saved = custom_store.save(spec)
    ledger.log(level="info", stage="audit", message=f"Custom strategy saved: {saved.get('name', saved['id'])}")
    return saved


@router.delete("/strategy/custom/{sid}")
def custom_delete(sid: str, x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    ok = custom_store.delete(sid)
    if ok:
        ledger.log(level="info", stage="audit", message=f"Custom strategy deleted: {sid}")
    return {"deleted": ok}


@router.post("/strategy/custom/{sid}/duplicate")
def custom_duplicate(sid: str, x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    dup = custom_store.duplicate(sid)
    if dup is None:
        raise HTTPException(404, "Strategy not found")
    return dup


@router.post("/strategy/custom/{sid}/deploy")
def custom_deploy(sid: str, x_webhook_secret: Optional[str] = Header(default=None)):
    """Deploy a saved custom strategy to PAPER trading (never live)."""
    _check_secret(x_webhook_secret)
    spec = custom_store.get(sid)
    if not spec:
        raise HTTPException(404, "Strategy not found")
    from strategies.custom_adapter import CustomStrategyAdapter
    name = spec.get("name", "Strategy")
    engine.reconfigure(
        symbols=[spec.get("symbol", "BTCUSDT")],
        timeframe=spec.get("timeframe", "4h"),
        strategy_factory=lambda sym, _s=spec: CustomStrategyAdapter(sym, _s),
        label=f"Custom: {name}",
    )
    ledger.log(level="info", stage="engine", message=f"Deployed custom strategy '{name}' to paper trading")
    ledger.add_alert(severity="info", category="system", title="Custom strategy deployed",
                     detail=f"{name} — paper mode (simulation only, no live broker)")
    return {"deployed": True, "status": engine.status()}


@router.get("/strategy/compare")
def strategy_compare(symbol: str = "BTCUSDT", timeframe: str = "4h",
                     strategy: str = "brain", bars: int = 3000):
    """Backtest a pre-built strategy on the same data, to compare vs a custom one."""
    from data.market_data import get_bars
    from backtest import run as _run, _metrics
    rows, source = get_bars(symbol, n=max(300, min(int(bars), 10000)), timeframe=timeframe)
    m = _metrics(_run(rows, strategy=strategy))
    return {
        "strategy": strategy, "data_source": source, "symbol": symbol, "timeframe": timeframe,
        "metrics": {
            "total_trades": m.trades, "win_rate": round(m.win_rate, 1),
            "profit_factor": round(m.profit_factor, 2), "net_r": round(m.net_r, 2),
            "max_drawdown_r": round(m.max_dd_r, 1), "avg_r": round(m.avg_r, 3),
        },
    }


class SymbolsUpdate(BaseModel):
    symbols: list[str]


@router.post("/market/symbols")
def set_symbols(body: SymbolsUpdate, x_webhook_secret: Optional[str] = Header(default=None)):
    """Set the engine's traded symbols (the active watchlist) and restart it."""
    _check_secret(x_webhook_secret)
    syms = [s.strip().upper() for s in body.symbols if s.strip()]
    if not syms:
        raise HTTPException(400, "At least one symbol is required")
    engine.reconfigure(symbols=syms, timeframe=engine.timeframe,
                       strategy_factory=engine.strategy_factory, label=engine.strategy_label)
    ledger.log(level="info", stage="audit", message=f"Watchlist applied: {', '.join(syms)}")
    return {"applied": True, "symbols": engine.symbols}


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
