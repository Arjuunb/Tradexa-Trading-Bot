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
    if key == "auto_strategy":
        settings.auto_strategy = str(value)
    elif key in ("notify_trades", "notify_risk"):
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
        "auto_strategy": settings.auto_strategy,
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


@router.get("/engine/diagnostics")
def engine_diagnostics():
    """Plain-English answer to 'why isn't the bot trading?' — built from real
    engine activity (running state, data feed, bars/signals/rejections, and how
    long since the last new candle)."""
    from datetime import datetime, timezone
    from services.auto_engine import explain_inactivity
    st = engine.status()
    age = None
    if st.get("last_activity"):
        try:
            la = datetime.fromisoformat(str(st["last_activity"]).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - la).total_seconds()
        except (ValueError, TypeError):
            age = None
    verdict = explain_inactivity(
        running=st.get("running", False), trading_state=controls.state,
        mode=st.get("mode", "replay"), timeframe=st.get("timeframe", "4h"),
        bars=st.get("bars", 0), signals=st.get("signals", 0),
        trades=st.get("trades", 0), rejections=st.get("rejections", 0),
        data_source=st.get("data_source"), last_activity_age_s=age,
    )
    return {
        **verdict,
        "running": st.get("running", False),
        "mode": st.get("mode"),
        "timeframe": st.get("timeframe"),
        "data_source": st.get("data_source"),
        "bars": st.get("bars", 0), "signals": st.get("signals", 0),
        "trades": st.get("trades", 0), "rejections": st.get("rejections", 0),
        "last_bar_ts": st.get("last_bar_ts"),
        "last_activity_age_s": round(age, 0) if age is not None else None,
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


class PositionSizeRequest(BaseModel):
    equity: float = 10000.0
    entry: float
    stop: Optional[float] = None
    side: str = "long"
    method: str = "percent"          # fixed | percent | atr | vol_adjusted
    risk_pct: float = 0.01
    fixed_risk: Optional[float] = None
    atr: Optional[float] = None
    atr_mult: float = 1.5
    leverage: float = 10.0
    vol_target_pct: float = 0.02


@router.post("/risk/position-size")
def risk_position_size(body: PositionSizeRequest):
    """Position sizing — fixed / percent / ATR / volatility-adjusted. Returns
    size, dollar risk, margin and a liquidation estimate."""
    from services.risk_engine import position_size
    return position_size(equity=body.equity, entry=body.entry, stop=body.stop, side=body.side,
                         method=body.method, risk_pct=body.risk_pct, fixed_risk=body.fixed_risk,
                         atr=body.atr, atr_mult=body.atr_mult, leverage=body.leverage,
                         vol_target_pct=body.vol_target_pct)


@router.get("/risk/correlation")
def risk_correlation(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT",
                     timeframe: str = "1d", lookback: int = 200):
    """Real correlation matrix of log returns over the cached Binance candles."""
    from services.risk_engine import correlation_matrix
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:8]
    return correlation_matrix(syms, timeframe=timeframe, lookback=lookback)


@router.get("/risk/portfolio")
def risk_portfolio(timeframe: str = "1d", conf: float = 0.95):
    """Portfolio risk: exposure (total/long/short/per-symbol), heat and a
    parametric Value-at-Risk from the real covariance matrix, with warnings."""
    from services.risk_engine import portfolio_risk
    raw = paper.positions()
    equity = paper.balance()
    pos = [{"symbol": p.get("symbol", ""), "direction": p.get("side", "long"),
            "notional": float(p.get("size", 0)) * float(p.get("entry", 0)),
            "risk": abs(float(p.get("entry", 0)) - float(p.get("stop") or p.get("entry", 0))) * float(p.get("size", 0))}
           for p in raw]
    out = portfolio_risk(equity, pos, timeframe=timeframe, conf=conf,
                         exposure_warn=settings.exposure_limit_pct)
    out["open_positions"] = len(pos)
    return out


@router.get("/risk/correlation-check")
def risk_correlation_check(candidate: str = "BTCUSDT", open_symbols: str = "",
                           timeframe: str = "1d", threshold: float = 0.8):
    """Would opening ``candidate`` stack onto an already-correlated position?"""
    from services.risk_engine import correlation_conflicts
    opens = [s.strip().upper() for s in open_symbols.split(",") if s.strip()]
    return correlation_conflicts(candidate.strip().upper(), opens,
                                 timeframe=timeframe, threshold=threshold)


@router.get("/coach/review")
def coach_review_endpoint(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                          timeframe: str = "15m", limit: int = 800):
    """AI Trading Coach — a mentor-style review of a REAL replay run: why trades
    won / lost, the recurring mistakes, weak conditions, suggestions, plus
    performance attribution and per-trade explanations."""
    from services.replay import build_replay
    from services.coach import coach_review
    rep = build_replay(symbol, timeframe, limit, strategy=strategy)
    if rep["meta"]["bars"] == 0:
        return {"available": False, "error": rep["meta"].get("data_warning", "No data."),
                "needs_download": rep["meta"].get("needs_download", False)}
    review = coach_review(rep["trades"], rep["stats"], symbol=symbol, strategy=strategy)
    review["available"] = True
    review["data_source"] = rep["meta"]["data_source_label"]
    return review


@router.get("/coach/leaderboard")
def coach_leaderboard(symbols: str = "BTCUSDT,ETHUSDT", strategies: str = "Decision Brain,EMA 20/50,Supply/Demand",
                      timeframe: str = "15m", limit: int = 600):
    """Performance attribution across strategies × symbols — which strategy and
    which symbol actually made money (#17). Runs real replays."""
    from services.replay import build_replay
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:4]
    strats = [s.strip() for s in strategies.split(",") if s.strip()][:5]
    grid, by_strategy, by_symbol = [], {}, {}
    for st in strats:
        for sym in syms:
            rep = build_replay(sym, timeframe, limit, strategy=st)
            s = rep["stats"]
            row = {"strategy": st, "symbol": sym, "trades": s["trades"],
                   "win_rate": s["win_rate"], "profit_factor": s["profit_factor"], "net_r": s["net_r"]}
            grid.append(row)
            by_strategy[st] = round(by_strategy.get(st, 0.0) + s["net_r"], 2)
            by_symbol[sym] = round(by_symbol.get(sym, 0.0) + s["net_r"], 2)
    grid.sort(key=lambda r: r["net_r"], reverse=True)
    rank = lambda d: sorted(({"key": k, "net_r": v} for k, v in d.items()), key=lambda x: x["net_r"], reverse=True)
    return {"timeframe": timeframe, "grid": grid,
            "by_strategy": rank(by_strategy), "by_symbol": rank(by_symbol),
            "best": grid[0] if grid else None}


@router.get("/lab/walk-forward")
def lab_walk_forward(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                     timeframe: str = "4h", bars: int = 4000, folds: int = 4):
    """Walk-forward: optimise per train block, validate on the next unseen block."""
    from services.backtest_lab import walk_forward
    return walk_forward(strategy, symbol, timeframe, bars=bars, folds=folds)


@router.get("/lab/monte-carlo")
def lab_monte_carlo(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                    timeframe: str = "4h", bars: int = 4000, runs: int = 1000):
    """Monte Carlo: bootstrap the trade sequence into an outcome distribution."""
    from services.backtest_lab import monte_carlo
    return monte_carlo(strategy, symbol, timeframe, bars=bars, runs=runs)


@router.get("/lab/out-of-sample")
def lab_out_of_sample(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                      timeframe: str = "4h", bars: int = 4000, split: float = 0.7):
    """Out-of-sample train/test split with an honest overfit verdict."""
    from services.backtest_lab import out_of_sample
    return out_of_sample(strategy, symbol, timeframe, bars=bars, split=split)


@router.get("/lab/sliced")
def lab_sliced(strategy: str = "Decision Brain", timeframe: str = "15m",
               symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", limit: int = 800):
    """Regime- / session- / symbol-conditional performance for one strategy."""
    from services.backtest_lab import sliced_performance
    syms = tuple(s.strip().upper() for s in symbols.split(",") if s.strip())[:4]
    return sliced_performance(strategy, timeframe, symbols=syms, limit=limit)


@router.get("/markets/watchlist")
def markets_watchlist(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT", timeframe: str = "1d"):
    """Real watchlist quotes from the cached Binance candles — last price, period
    change, volatility and a mini sparkline. Honest 'unavailable' per symbol when
    no real history is cached (never a faked price)."""
    from data.market_data import get_bars
    from services.risk_engine import log_returns, _stdev
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:12]
    out = []
    for sym in syms:
        rows, src = get_bars(sym, n=60, timeframe=timeframe, require_real=True)
        if not rows or len(rows) < 2:
            out.append({"symbol": sym, "available": False, "source": src})
            continue
        closes = [b.close for b in rows]
        last, prev = closes[-1], closes[-2]
        vol = _stdev(log_returns(closes)) * 100
        out.append({
            "symbol": sym, "available": True, "source": src,
            "last": round(last, 6), "change_pct": round((last / prev - 1) * 100, 2),
            "vol_pct": round(vol, 2), "spark": [round(c, 6) for c in closes[-30:]],
            "bars": len(rows),
        })
    return {"timeframe": timeframe, "symbols": out}


_STRATEGY_CATALOG = [
    {"key": "brain", "label": "Decision Brain",
     "desc": "Multi-factor trend: EMA trend + filter, momentum, RSI, regime; conviction-weighted sizing"},
    {"key": "supertrend", "label": "Supertrend", "desc": "ATR trend-following indicator"},
    {"key": "donchian", "label": "Donchian Breakout", "desc": "Classic Turtle channel breakout"},
    {"key": "ensemble", "label": "Confirmation Ensemble",
     "desc": "Trades only when 2 of 3 agree (EMA + Supertrend + Donchian)"},
    {"key": "ema", "label": "EMA Crossover", "desc": "Simple fast/slow EMA cross"},
    {"key": "smc", "label": "SMC (Smart Money)",
     "desc": "Liquidity sweep + CHoCH/BOS + FVG in line with higher-timeframe bias"},
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

# ------------------------------------------------- evolution engine stores
from services.lessons import LessonStore  # noqa: E402
from services.evolution import UpgradeStore, StrategyVersionStore  # noqa: E402
lesson_store = LessonStore(settings.lessons_path)
upgrade_store = UpgradeStore(settings.upgrades_path)
version_store = StrategyVersionStore(settings.versions_path)

# ------------------------------------------------- historical data engine
from data.historical import HistoricalStore  # noqa: E402
market_store = HistoricalStore(settings.market_db)

# ------------------------------------------------- market-context providers
from services.market_context import ProviderSettings  # noqa: E402
provider_settings = ProviderSettings(settings.providers_path)


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


def _build_builtin(key: str, symbol: str):
    """Construct a built-in strategy object by catalog key."""
    if key == "smc":
        from strategies.smc_strategy import SMCStrategy
        return SMCStrategy(symbol)
    if key == "supertrend":
        from strategies.supertrend_strategy import SupertrendStrategy
        return SupertrendStrategy(symbol)
    if key == "donchian":
        from strategies.donchian_strategy import DonchianStrategy
        return DonchianStrategy(symbol)
    if key == "ensemble":
        from strategies.ensemble_strategy import ConfirmationEnsemble
        return ConfirmationEnsemble(symbol)
    if key == "ema":
        from strategies.ema_strategy import EMAStrategy
        return EMAStrategy(symbol)
    from strategies.brain_strategy import DecisionBrain
    return DecisionBrain(symbol)


@router.get("/control/options")
def control_options():
    """Strategy / symbol / timeframe / mode options + default brain tuning for
    the top control bar."""
    from services.strategy_presets import STRATEGY_OPTIONS, SYMBOLS, TIMEFRAMES, MODES, DEFAULT_TUNING
    return {"strategies": STRATEGY_OPTIONS, "symbols": SYMBOLS, "timeframes": TIMEFRAMES,
            "modes": MODES, "default_tuning": DEFAULT_TUNING}


class ControlSimRequest(BaseModel):
    strategy: str = "Decision Brain"
    symbol: str = "BTCUSDT"
    timeframe: str = "4h"
    tuning: dict = {}
    custom_spec: Optional[dict] = None
    bars: int = 4000
    macro: Optional[str] = None
    confirmation: Optional[str] = None


@router.post("/control/simulate")
def control_simulate(body: ControlSimRequest):
    """Rerun a REAL simulation for the chosen strategy/symbol/timeframe/tuning.
    The macro/confirmation timeframes drive the multi-timeframe gate."""
    from services.strategy_presets import run_simulation
    return run_simulation(body.strategy, body.symbol, body.timeframe,
                          tuning=body.tuning, custom_spec=body.custom_spec, bars=body.bars,
                          macro=body.macro, confirmation=body.confirmation)


@router.post("/control/auto-tune")
def control_auto_tune(body: ControlSimRequest):
    """Search the brain-tuning space on real data (train/test split) and return
    the best configuration with an honest overfit verdict."""
    from services.strategy_presets import auto_tune
    return auto_tune(body.strategy, body.symbol, body.timeframe, macro=body.macro,
                     confirmation=body.confirmation, custom_spec=body.custom_spec, bars=body.bars)


class ControlCompareRequest(BaseModel):
    a: dict
    b: dict
    bars: int = 4000


@router.post("/control/compare")
def control_compare(body: ControlCompareRequest):
    """Compare two strategy/timeframe/symbol configurations on the same real data."""
    from services.strategy_presets import compare
    return compare(body.a, body.b, bars=body.bars)


@router.post("/control/save-version")
def control_save_version(body: ControlSimRequest, x_webhook_secret: Optional[str] = Header(default=None)):
    """Snapshot the current control-bar configuration as a new strategy version
    (never overwrites older versions)."""
    _check_secret(x_webhook_secret)
    from services.strategy_presets import run_simulation
    sim = run_simulation(body.strategy, body.symbol, body.timeframe,
                         tuning=body.tuning, custom_spec=body.custom_spec, bars=body.bars)
    if not sim.get("available"):
        raise HTTPException(400, sim.get("error", "Cannot version without real data."))
    r = sim["results"]
    stats = {k: r[k] for k in ("total_trades", "win_rate", "profit_factor", "net_r",
                               "max_drawdown_pct", "expectancy_r") if k in r}
    params = {"strategy": body.strategy, "symbol": body.symbol, "timeframe": body.timeframe,
              "tuning": body.tuning, "spec": sim.get("spec")}
    return version_store.add_version(body.strategy, params, stats,
                                     note=f"{body.strategy} {body.symbol} {body.timeframe}")


@router.get("/mtf/analyze")
def mtf_analyze(symbol: str = "BTCUSDT"):
    """Multi-timeframe decision: analyse Weekly→Daily→4H→15M→5M together and
    explain whether a trade is allowed, blocked or still waiting."""
    from services.mtf_engine import analyze
    return analyze(symbol)


@router.get("/data/coverage")
def data_coverage():
    """What real Binance history is cached locally (symbol/timeframe matrix)."""
    from data.historical import SYMBOLS, TIMEFRAMES
    return {"symbols": list(SYMBOLS), "timeframes": list(TIMEFRAMES),
            "coverage": market_store.all_coverage()}


@router.post("/data/sync")
def data_sync(symbol: str = "BTCUSDT", timeframe: str = "4h", target_candles: int = 3000,
              x_webhook_secret: Optional[str] = Header(default=None)):
    """Fetch REAL Binance candles and cache them locally (no synthetic data)."""
    _check_secret(x_webhook_secret)
    from data.historical import sync
    res = sync(market_store, symbol, timeframe, target_candles=target_candles)
    if "error" in res:
        ledger.log(level="warning", stage="data", message=f"Sync {symbol} {timeframe}: {res['error']}")
    else:
        ledger.log(level="info", stage="data",
                   message=f"Synced {symbol} {timeframe}: {res.get('stored')} candles cached")
    return res


@router.post("/data/sync-all")
def data_sync_all(target_candles: int = 2000, x_webhook_secret: Optional[str] = Header(default=None)):
    """Sync every supported symbol × timeframe (run once with network to populate)."""
    _check_secret(x_webhook_secret)
    from data.historical import sync, SYMBOLS, TIMEFRAMES
    out = []
    for s in SYMBOLS:
        for tf in TIMEFRAMES:
            out.append(sync(market_store, s, tf, target_candles=target_candles))
    ok = sum(1 for r in out if "error" not in r)
    return {"synced": ok, "total": len(out), "results": out}


@router.get("/replay/run")
def replay_run(symbol: str = "BTCUSDT", timeframe: str = "15m", limit: int = 800,
               start: Optional[str] = None, end: Optional[str] = None,
               strategy: str = "Supply/Demand", source: str = "binance",
               macro: Optional[str] = None, confirmation: Optional[str] = None):
    """Precompute a no-lookahead decision timeline for TradingView-style replay
    using the SELECTED strategy. ``source`` = binance | demo. ``start``/``end``
    (YYYY-MM-DD) jump to a specific historical window. ``macro``/``confirmation``
    pick the higher timeframes that drive the multi-timeframe entry gate."""
    from services.replay import build_replay
    return build_replay(symbol, timeframe, limit, start=start, end=end,
                        strategy=strategy, source=source,
                        macro=macro, confirmation=confirmation)


@router.get("/strategies/registry")
def strategies_registry():
    """The real strategy registry the selectors pull from (id / version / meta)."""
    from services.strategy_presets import REGISTRY
    return {"strategies": REGISTRY}


@router.get("/replay/stats")
def replay_stats(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT",
                 timeframe: str = "15m", limit: int = 600):
    """Per-asset replay stats (BTC/ETH/SOL/XRP) for the statistics panel."""
    from services.replay import multi_asset_stats
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:6]
    return {"timeframe": timeframe, "assets": multi_asset_stats(syms, timeframe, limit)}


@router.get("/evolution/sentiment")
def evolution_sentiment():
    """Real-world market sentiment (Fear & Greed, dominance) — filter only."""
    from services.sentiment import market_sentiment
    return market_sentiment()


@router.post("/evolution/learn")
def evolution_learn(symbol: str = "BTCUSDT", timeframe: str = "15m", limit: int = 1000,
                    strategy: str = "Supply/Demand",
                    x_webhook_secret: Optional[str] = Header(default=None)):
    """Study real replay results for a symbol, derive evidence-based lessons +
    upgrade suggestions, and record them (status 'Suggested' — never auto-applied)."""
    _check_secret(x_webhook_secret)
    from services.replay import build_replay
    from services.lessons import lessons_from_results, mtf_disagreement_lessons
    from services.evolution import suggest_improvements
    rep = build_replay(symbol, timeframe, limit, strategy=strategy)
    bundle = {"trades": rep["trades"], "stats": rep["stats"], "diagnosis": _replay_diag(rep)}
    # timeframe-disagreement detector (evidence-based, from the per-bar trends)
    dis = mtf_disagreement_lessons(rep, symbol=symbol, strategy=strategy)
    lessons = lessons_from_results(bundle, symbol=symbol, strategy=strategy) + dis
    added_lessons = lesson_store.add_many(lessons)
    added_upgrades = upgrade_store.add_many(
        suggest_improvements(bundle, symbol=symbol, strategy=strategy, extra_lessons=dis))
    ledger.log(level="info", stage="evolution",
               message=f"Learned from {symbol}: {len(added_lessons)} new lessons, "
                       f"{len(added_upgrades)} new suggestions")
    return {"lessons": added_lessons, "upgrades": added_upgrades,
            "studied_trades": rep["stats"]["trades"], "data_source": rep["meta"]["data_source"]}


def _replay_diag(rep: dict) -> dict:
    """Build a diagnosis-shaped dict from replay trades for the lessons engine."""
    from strategies.diagnosis import diagnose
    # replay trades use 'rr'; diagnose expects 'r'
    trades = [{**t, "r": t.get("rr")} for t in rep["trades"] if t.get("rr") is not None]
    return diagnose({"trades": trades, "total_trades": len(trades),
                     "win_rate": rep["stats"]["win_rate"], "profit_factor": rep["stats"]["profit_factor"],
                     "span_days": 30}, [])


@router.get("/evolution/lessons")
def evolution_lessons():
    return {"lessons": lesson_store.list(), "weekly": lesson_store.weekly_count(),
            "status_counts": lesson_store.status_counts()}


@router.post("/evolution/lessons/{lid}/status")
def evolution_lesson_status(lid: str, status: str,
                            x_webhook_secret: Optional[str] = Header(default=None)):
    _check_secret(x_webhook_secret)
    res = lesson_store.set_status(lid, status)
    if res is None:
        raise HTTPException(404, "Lesson not found or invalid status")
    return res


@router.get("/evolution/upgrades")
def evolution_upgrades():
    return {"upgrades": upgrade_store.list_sorted(), "status_counts": upgrade_store.status_counts()}


@router.post("/evolution/upgrades/{uid}/status")
def evolution_upgrade_status(uid: str, status: str,
                             x_webhook_secret: Optional[str] = Header(default=None)):
    """Advance an upgrade through its lifecycle. Approve/Reject/Archive are
    human-only; the bot can never set them itself."""
    _check_secret(x_webhook_secret)
    res = upgrade_store.set_status(uid, status, by="human")
    if res is None:
        raise HTTPException(404, "Upgrade not found")
    if "error" in res:
        raise HTTPException(400, res["error"])
    ledger.log(level="info", stage="evolution", message=f"Upgrade {uid[:8]} -> {status} (human)")
    return res


class ExperimentRequest(BaseModel):
    base: dict
    variant: dict
    bars: int = 4000


@router.post("/evolution/experiment")
def evolution_experiment(body: ExperimentRequest):
    """A/B two strategy specs with a train/test split + overfitting verdict."""
    from services.evolution import run_experiment
    return run_experiment(body.base, body.variant, bars=body.bars)


@router.post("/evolution/versions")
def evolution_add_version(body: dict, x_webhook_secret: Optional[str] = Header(default=None)):
    """Snapshot a strategy spec as a new version (with its simulated stats)."""
    _check_secret(x_webhook_secret)
    from strategies.custom import simulate
    from strategies.brain import TradeBrain
    from data.market_data import get_bars
    spec = body.get("spec") or {}
    strategy = body.get("strategy") or spec.get("name", "Strategy")
    rows, _ = get_bars(spec.get("symbol", "BTCUSDT"), n=4000, timeframe=spec.get("timeframe", "4h"))
    r = simulate(spec, rows, brain=TradeBrain(), min_score=int(spec.get("min_score", 60)))
    stats = {k: r[k] for k in ("total_trades", "win_rate", "profit_factor", "net_r",
                               "max_drawdown_pct", "avg_rr", "expectancy_r") if k in r}
    return version_store.add_version(strategy, spec, stats, note=body.get("note", ""))


@router.get("/evolution/versions")
def evolution_versions(strategy: str):
    return version_store.compare(strategy)


def _default_base_spec(strategy: str, symbol: str = "BTCUSDT") -> dict:
    """A representative base spec to patch when no prior version exists."""
    return {"name": strategy, "symbol": symbol, "timeframe": "4h", "side": "long",
            "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"}]},
            "stop": {"type": "atr", "mult": 1.5, "period": 14},
            "target": {"type": "rr", "rr": 2.0}, "risk_per_trade_pct": 0.01,
            "min_score": 60, "quality_filter": True}


@router.post("/evolution/upgrades/{uid}/promote")
def evolution_promote(uid: str, body: dict = None,
                      x_webhook_secret: Optional[str] = Header(default=None)):
    """Turn an APPROVED, auto-applicable upgrade into a new strategy version and
    run its backtest. The version then flows through Sim -> Paper -> (locked) Live."""
    _check_secret(x_webhook_secret)
    body = body or {}
    up = next((u for u in upgrade_store.list_sorted() if u["id"] == uid), None)
    if up is None:
        raise HTTPException(404, "Upgrade not found")
    if up.get("status") != "Approved":
        raise HTTPException(400, "Approve the upgrade before promoting it to a version.")
    patch = up.get("apply")
    if not patch:
        raise HTTPException(400, "This upgrade needs a manual change — no auto-patch available.")

    from services.evolution import apply_patch
    from strategies.custom import simulate
    from strategies.brain import TradeBrain
    from data.market_data import get_bars

    strategy = up.get("strategy", "Strategy")
    prior = version_store.versions(strategy)
    base = body.get("base_spec") or (prior[-1]["params"] if prior else _default_base_spec(strategy, up.get("symbol", "BTCUSDT")))
    new_spec = apply_patch(base, patch)

    rows, _ = get_bars(new_spec.get("symbol", "BTCUSDT"), n=4000, timeframe=new_spec.get("timeframe", "4h"))
    r = simulate(new_spec, rows, brain=TradeBrain(), min_score=int(new_spec.get("min_score", 60)))
    stats = {k: r[k] for k in ("total_trades", "win_rate", "profit_factor", "net_r",
                               "max_drawdown_pct", "expectancy_r") if k in r}
    version = version_store.add_version(strategy, new_spec, stats, note=up["title"])  # backtest gate done
    upgrade_store.set_status(uid, "Backtested", by="human")
    ledger.log(level="info", stage="evolution",
               message=f"Promoted upgrade {uid[:8]} -> {version['label']} (backtest done; sim/paper pending)")
    return {"version": version, "applied_patch": patch}


@router.post("/evolution/versions/{vid}/advance")
def evolution_advance_version(vid: str, gate: str,
                              x_webhook_secret: Optional[str] = Header(default=None)):
    """Advance a version through the safety gates. 'simulation' runs a sim;
    'paper' is a human-confirmed checkpoint; 'live_unlock' stays locked with no
    broker connected (by design)."""
    _check_secret(x_webhook_secret)
    v = version_store.get(vid)
    if v is None:
        raise HTTPException(404, "Version not found")
    stats = None
    if gate == "simulation":
        from strategies.custom import simulate
        from strategies.brain import TradeBrain
        from data.market_data import get_bars
        spec = v["params"]
        rows, _ = get_bars(spec.get("symbol", "BTCUSDT"), n=3000, timeframe=spec.get("timeframe", "4h"))
        r = simulate(spec, rows, brain=TradeBrain(), min_score=int(spec.get("min_score", 60)))
        stats = {k: r[k] for k in ("total_trades", "win_rate", "profit_factor", "net_r", "expectancy_r") if k in r}
    res = version_store.advance_gate(vid, gate, stats=stats,
                                     broker_connected=bool(getattr(engine, "live", False) and False))
    if res is None:
        raise HTTPException(404, "Version not found")
    if "error" in res:
        # live stays locked: surface the reason, not a hard failure
        if gate == "live_unlock":
            return res
        raise HTTPException(400, res["error"])
    ledger.log(level="info", stage="evolution", message=f"{v['label']} gate '{gate}' advanced")
    return res


@router.get("/evolution/market-context")
def evolution_market_context():
    """Live real-world market widgets (Fear & Greed, dominance, ETH/BTC, funding,
    OI, news…). Key-gated sources show 'Not connected' — never fake data."""
    from services.market_context import market_context
    return market_context(provider_settings)


@router.get("/evolution/providers")
def evolution_providers():
    """Per-provider connection status for the Data Providers settings panel
    (never exposes the key values)."""
    return {"providers": provider_settings.status()}


@router.post("/evolution/providers")
def evolution_set_providers(body: dict, x_webhook_secret: Optional[str] = Header(default=None)):
    """Save provider API keys (local store). Blanks are ignored (won't wipe)."""
    _check_secret(x_webhook_secret)
    return {"providers": provider_settings.save(body or {})}


@router.get("/evolution/dashboard")
def evolution_dashboard():
    """Aggregate widgets for the Evolution dashboard."""
    from services.sentiment import market_sentiment
    sent = market_sentiment()
    return {
        "sentiment": {"available": sent.get("available"), "mood": sent.get("mood"),
                      "risk_mode": sent.get("risk_mode"), "fear_greed": sent.get("fear_greed")},
        "lessons_weekly": lesson_store.weekly_count(),
        "lessons_total": len(lesson_store.list()),
        "lesson_status": lesson_store.status_counts(),
        "upgrade_status": upgrade_store.status_counts(),
        "workflow": ["Observe", "Diagnose", "Suggest", "New version", "Backtest",
                     "Simulation", "Paper trading", "Human approval", "Live unlock"],
        "live_rule": "Live trading changes require human approval — the bot never auto-applies upgrades.",
    }


@router.get("/strategy/builtin/simulate")
def builtin_simulate(strategy: str = "smc", symbol: str = "BTCUSDT",
                     timeframe: str = "4h", bars: int = 3000):
    """Simulate a built-in strategy (e.g. SMC) over real historical bars and
    return the same rich shape as the custom simulator (metrics + diagnosis)."""
    from strategies.custom import simulate_strategy
    from strategies.diagnosis import diagnose
    from data.market_data import get_bars
    n = max(300, min(int(bars or 3000), 10000))
    rows, source = get_bars(symbol, n=n, timeframe=timeframe)
    strat = _build_builtin(strategy, symbol)
    results = simulate_strategy(strat, rows)
    results["diagnosis"] = diagnose(results, [])
    label = next((s["label"] for s in _STRATEGY_CATALOG if s["key"] == strategy), strategy)
    return {
        "results": results,
        "warnings": [],
        "description": f"Built-in strategy: {label}.",
        "data_source": source, "symbol": symbol, "timeframe": timeframe,
        "label": "Simulation Result",
        "brain": {"quality_filter": False, "min_score": 0, "blocked_count": 0},
    }


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

    def _log_block(info: dict):
        """Record a brain-blocked paper setup to the decision log (avoiding bad
        trades is part of the edge — make it visible)."""
        ledger.log(level="info", stage="brain",
                   message=(f"{info['symbol']} {info['side']} blocked — {info['reason']} "
                            f"(score {info['score']}, {info['regime']}, HTF {info['htf_bias']})"),
                   symbol=info["symbol"])

    engine.reconfigure(
        symbols=[spec.get("symbol", "BTCUSDT")],
        timeframe=spec.get("timeframe", "4h"),
        strategy_factory=lambda sym, _s=spec: CustomStrategyAdapter(sym, _s, on_block=_log_block),
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


class StrategySelect(BaseModel):
    strategy: str


@router.post("/strategy/select")
def strategy_select(body: StrategySelect, x_webhook_secret: Optional[str] = Header(default=None)):
    """Switch the live (paper) engine's active built-in strategy and persist it.

    This actually changes the backend logic: the engine is reconfigured with the
    selected strategy factory so every symbol now trades the chosen strategy. The
    choice is saved so it survives a restart. Live trading stays locked (paper)."""
    _check_secret(x_webhook_secret)
    key = (body.strategy or "").strip()
    entry = next((s for s in _STRATEGY_CATALOG if s["key"] == key or s["label"] == key), None)
    if not entry:
        raise HTTPException(400, f"Unknown strategy '{key}'. "
                                 f"Choose one of: {', '.join(s['key'] for s in _STRATEGY_CATALOG)}.")
    if entry["key"] == settings.auto_strategy:
        return {"applied": True, "active": settings.auto_strategy, "unchanged": True,
                "status": engine.status()}
    settings.auto_strategy = entry["key"]                 # _make_strategy reads this live
    if engine.running:                                    # swap on the running engine
        engine.reconfigure(symbols=engine.symbols, timeframe=engine.timeframe,
                           strategy_factory=_make_strategy, label=entry["label"])
    else:                                                 # respect a stopped engine
        engine.strategy_factory = _make_strategy
        engine.strategy_label = entry["label"]
    save_overrides(settings.settings_path, _settings_snapshot())
    ledger.log(level="info", stage="audit",
               message=f"Active strategy switched to {entry['label']} ({entry['key']})")
    ledger.add_alert(severity="info", category="system", title="Strategy switched",
                     detail=f"Engine now trading {entry['label']} (paper mode)")
    return {"applied": True, "active": settings.auto_strategy,
            "label": entry["label"], "status": engine.status()}


@router.get("/strategy/performance")
def strategy_performance():
    """The bot's live paper-trading track record (real executed trades)."""
    from services.performance import summarize
    stats = summarize(paper.history(), paper.starting_balance)
    stats["strategy"] = engine.strategy_label
    stats["mode"] = "live" if engine.live else "replay"
    return stats


@router.get("/strategy/health")
def strategy_health():
    """Strategy health (rolling deterioration check) + the brain's block rate:
    how many setups the quality filter took vs avoided in paper."""
    from services.strategy_health import StrategyHealthMonitor
    hist = [{**t, "r": (t.get("rr") if t.get("rr") is not None else 0.0)} for t in paper.history()]
    health = StrategyHealthMonitor().evaluate(hist)

    logs = ledger.get_logs(limit=1000)
    blocked = sum(1 for l in logs if l.get("stage") == "brain")
    taken = sum(1 for l in logs if l.get("stage") == "execution"
                and "opened" in (l.get("message") or ""))
    total = blocked + taken
    # most common block reasons (text after the em dash, before the parenthesis)
    from collections import Counter
    reasons: Counter = Counter()
    for l in logs:
        if l.get("stage") == "brain":
            msg = l.get("message") or ""
            r = msg.split("blocked — ", 1)[-1].split("(")[0].strip() if "blocked — " in msg else "blocked"
            reasons[r] += 1

    # blocked counts per symbol (from the brain-stage decision log)
    blocked_by_sym: Counter = Counter()
    for l in logs:
        if l.get("stage") == "brain" and l.get("symbol"):
            blocked_by_sym[l["symbol"]] += 1

    return {
        "strategy": engine.strategy_label,
        "health": health.to_dict(),
        "brain": {
            "blocked": blocked, "taken": taken, "total": total,
            "block_rate": round(blocked / total * 100, 1) if total else 0.0,
            "top_reasons": dict(reasons.most_common(6)),
        },
        "breakdown": _health_breakdown(paper.history(), blocked_by_sym),
    }


def _session_of(hour: int) -> str:
    if 0 <= hour < 8:
        return "Asia"
    if 8 <= hour < 16:
        return "London"
    return "New York"


def _health_breakdown(history: list, blocked_by_sym) -> dict:
    """Per-symbol and per-session taken-trade performance (real P&L) + blocks."""
    def _hour(ts) -> int:
        try:
            return int(str(ts)[11:13])
        except (ValueError, TypeError):
            return -1

    sym: dict = {}
    sess: dict = {}
    for t in history:
        pnl = t.get("pnl") or 0.0
        s = sym.setdefault(t.get("symbol", "?"), {"trades": 0, "wins": 0, "net_pnl": 0.0})
        s["trades"] += 1; s["wins"] += 1 if pnl > 0 else 0; s["net_pnl"] += pnl
        h = _hour(t.get("opened_at"))
        if h >= 0:
            name = _session_of(h)
            g = sess.setdefault(name, {"trades": 0, "wins": 0, "net_pnl": 0.0})
            g["trades"] += 1; g["wins"] += 1 if pnl > 0 else 0; g["net_pnl"] += pnl

    def _rows(d, extra=None):
        out = []
        for name, v in d.items():
            row = {"name": name, "trades": v["trades"],
                   "win_rate": round(100 * v["wins"] / v["trades"], 0) if v["trades"] else 0.0,
                   "net_pnl": round(v["net_pnl"], 2)}
            if extra is not None:
                row["blocked"] = int(extra.get(name, 0))
            out.append(row)
        return sorted(out, key=lambda r: r["net_pnl"])

    # include symbols that were only ever blocked (never traded)
    by_symbol = _rows(sym, blocked_by_sym)
    seen = {r["name"] for r in by_symbol}
    for s, c in blocked_by_sym.items():
        if s not in seen:
            by_symbol.append({"name": s, "trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "blocked": int(c)})
    return {"by_symbol": by_symbol, "by_session": _rows(sess)}


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
