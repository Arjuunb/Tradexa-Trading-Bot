"""Engine endpoints — split from webhook_api.py.

Endpoint bodies are unchanged except that references to shared state resolve via
``_wa.<name>`` so singletons (pipeline, ledger, paper, engine, …) are read from
webhook_api at request time. That keeps the test suite's fixture rebinding
(``webhook_api.pipeline = <fresh>``) working exactly as before the split.
"""
import webhook_api as _wa
from fastapi import APIRouter, Header, HTTPException, Body, Query, Depends  # noqa: F401
from typing import Optional, List, Dict  # noqa: F401

# Fallback: expose every webhook_api global by name so references the qualifier
# intentionally left bare (e.g. inside f-strings) still resolve. Qualified
# `_wa.<name>` uses stay dynamic; these copies are only a safety net.
globals().update({k: v for k, v in vars(_wa).items()
                  if not k.startswith("__") and k != "router"})

router = APIRouter()


# ─────────────────────── Trading modes + approvals (§7, §11) ───────────────
_MODES = ("full", "semi", "signal")


@router.get("/engine/mode")
def get_mode():
    """Current trading mode: full (auto-execute), semi (approve each entry),
    signal (alert only). Exits always execute automatically in every mode."""
    return {"mode": _wa.engine.trading_mode, "modes": list(_MODES),
            "pending_approvals": _wa.approvals.counts()["pending"]}


@router.post("/engine/mode")
def set_mode(body: dict = Body(...), x_webhook_secret: Optional[str] = Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    mode = str(body.get("mode", "")).lower()
    if mode not in _MODES:
        raise HTTPException(400, f"mode must be one of {_MODES}")
    _wa.engine.trading_mode = mode
    _wa.save_overrides(_wa.settings.settings_path, _wa._settings_snapshot())
    _wa.ledger.log(level="info", stage="controls", message=f"Trading mode → {mode}")
    return {"mode": mode}


@router.get("/approvals")
def list_approvals(limit: int = 50):
    """Pending trade ideas awaiting approval (semi-auto) plus recent resolved
    ideas (approved / rejected / expired / signalled) for the audit trail."""
    return {"mode": _wa.engine.trading_mode,
            "pending": _wa.approvals.list_pending(),
            "recent": _wa.approvals.list_recent(max(1, min(limit, 200)))}


@router.post("/approvals/{iid}/approve")
def approve_idea(iid: int, x_webhook_secret: Optional[str] = Header(default=None)):
    """Approve a queued idea — routes it through the SAME risk pipeline (all
    gates still apply). 404 if the idea expired or was already resolved."""
    _wa._check_secret(x_webhook_secret)
    idea = _wa.approvals.approve(iid)
    if idea is None:
        raise HTTPException(404, "No pending idea with that id (it may have expired)")
    result = _wa.engine.execute_approved(idea)
    return {"approved": True, "id": iid, "result": result}


@router.post("/approvals/{iid}/reject")
def reject_idea(iid: int, body: dict = Body(default={}),
                x_webhook_secret: Optional[str] = Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    idea = _wa.approvals.reject(iid, str(body.get("reason", "")))
    if idea is None:
        raise HTTPException(404, "No pending idea with that id (it may have expired)")
    # grade the rejection like any veto: was the trade we passed on a winner?
    if _wa.counterfactual is not None:
        try:
            _wa.counterfactual.record_veto(
                symbol=idea.get("symbol"),
                side="long" if idea.get("side") == "BUY" else "short",
                entry=idea.get("entry"), stop=idea.get("stop"),
                target=idea.get("target"), rule="approval-reject",
                detail=idea.get("reject_reason", "manual"))
        except Exception:  # noqa: BLE001
            pass
    return {"rejected": True, "id": iid}


# ─────────────────────────── Risk profile presets (§9) ─────────────────────
# Each preset is a coherent bundle; the headline is risk-per-trade (0.5/1/2%),
# with drawdown / daily-loss / exposure / max-positions scaled to match. All
# values are FRACTIONS (0.01 = 1%), the same units POST /settings expects.
RISK_PRESETS = {
    "conservative": {"risk_per_trade_pct": 0.005, "max_open_positions": 2,
                     "max_daily_loss_pct": 0.02, "max_drawdown_pct": 0.10,
                     "exposure_limit_pct": 0.10},
    "balanced": {"risk_per_trade_pct": 0.01, "max_open_positions": 3,
                 "max_daily_loss_pct": 0.03, "max_drawdown_pct": 0.15,
                 "exposure_limit_pct": 0.15},
    "aggressive": {"risk_per_trade_pct": 0.02, "max_open_positions": 5,
                   "max_daily_loss_pct": 0.05, "max_drawdown_pct": 0.25,
                   "exposure_limit_pct": 0.30},
}


def _active_risk_preset() -> Optional[str]:
    """Which preset (if any) the live risk config currently matches exactly."""
    cur = {"risk_per_trade_pct": _wa.pipeline.risk_per_trade_pct,
           "max_open_positions": _wa.pipeline.max_open_positions,
           "max_daily_loss_pct": _wa.pipeline.max_daily_loss_pct,
           "max_drawdown_pct": _wa.pipeline.max_drawdown_pct,
           "exposure_limit_pct": _wa.pipeline.exposure_limit_pct}
    for name, vals in RISK_PRESETS.items():
        if all(abs(float(cur[k]) - float(v)) < 1e-9 for k, v in vals.items()):
            return name
    return None


@router.get("/risk/presets")
def risk_presets():
    return {"presets": RISK_PRESETS, "active": _active_risk_preset()}


@router.post("/risk/preset")
def apply_risk_preset(body: dict = Body(...), x_webhook_secret: Optional[str] = Header(default=None)):
    """Apply a named risk preset to the live engine (persisted). 'custom' is a
    no-op marker — edit individual fields under Settings for custom profiles."""
    _wa._check_secret(x_webhook_secret)
    name = str(body.get("name", "")).lower()
    if name == "custom":
        return {"applied": "custom", "note": "edit individual risk fields under Settings"}
    preset = RISK_PRESETS.get(name)
    if preset is None:
        raise HTTPException(400, f"Unknown preset {name!r}")
    for k, val in preset.items():
        if k == "max_open_positions":
            _wa.pipeline.max_open_positions = int(val)
        else:
            setattr(_wa.pipeline, k, float(val))
    _wa.save_overrides(_wa.settings.settings_path, _wa._settings_snapshot())
    _wa.ledger.log(level="info", stage="audit", message=f"Risk preset applied: {name}")
    return {"applied": name, "values": preset}




# ------------------------------------------------------------------- webhook
@router.post("/webhook/tradingview")
def tradingview_webhook(payload: _wa.WebhookPayload,
                        x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_webhook_secret(x_webhook_secret)
    result = _wa.pipeline.process(payload.model_dump())
    return {"status": "ok", **result.to_dict()}

# ------------------------------------------------------- emergency controls
@router.post("/controls/pause-all")
def pause_all(x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    _wa.controls.pause_all()
    _wa.ledger.log(level="warning", stage="controls", message="PAUSE ALL — entries blocked")
    return {"state": _wa.controls.state}

@router.post("/controls/stop-all")
def stop_all(x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    _wa.controls.stop_all()
    _wa.ledger.log(level="warning", stage="controls", message="STOP ALL — trading halted")
    return {"state": _wa.controls.state}

@router.post("/controls/resume")
def resume(x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    _wa.controls.resume()
    _wa.pipeline.resume()          # also clear any auto-halt (drawdown breaker)
    _wa.ledger.log(level="info", stage="controls", message="RESUME — trading active")
    return {"state": _wa.controls.state, "auto_halted": _wa.pipeline.halted}

# ---------------------------------------------------- autonomous engine
@router.post("/engine/start")
def engine_start(x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    started = _wa.engine.start()
    return {"started": started, "status": _wa.engine.status()}

@router.post("/engine/stop")
def engine_stop(x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    stopped = _wa.engine.stop()
    return {"stopped": stopped, "status": _wa.engine.status()}

@router.get("/engine/status")
def engine_status():
    return _wa.engine.status()

@router.get("/system/status")
def system_status():
    """Real bot/system health — no fabricated values. Paper-only until a live
    broker is wired (live execution is a future phase)."""
    st = _wa.engine.status()
    return {
        "mode": "paper",                     # the engine paper-executes; no live broker
        "broker_connected": False,           # honest: no live venue connected
        "data_source": "live (ccxt)" if _wa.engine.live else "synthetic / replay",
        "engine_running": st.get("running", False),
        "engine_mode": st.get("mode"),
        "strategy": _wa.engine.strategy_label,
        "symbols": _wa.engine.symbols,
        "timeframe": _wa.engine.timeframe,
        "bars_processed": st.get("bars", 0),
        "signals": st.get("signals", 0),
        "trades": st.get("trades", 0),
        "started_at": st.get("started_at"),
        "uptime_s": round(_wa.time.time() - _wa._BOOT, 0),
        "trading_state": _wa.controls.state,
        "auto_halted": _wa.pipeline.halted,
        "halt_reason": _wa.pipeline.halt_reason,
    }

@router.get("/engine/diagnostics")
def engine_diagnostics():
    """Plain-English answer to 'why isn't the bot trading?' — built from real
    engine activity (running state, data feed, bars/signals/rejections, and how
    long since the last new candle)."""
    from datetime import datetime, timezone
    from services.auto_engine import explain_inactivity
    st = _wa.engine.status()
    age = None
    if st.get("last_activity"):
        try:
            la = datetime.fromisoformat(str(st["last_activity"]).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - la).total_seconds()
        except (ValueError, TypeError):
            age = None
    verdict = explain_inactivity(
        running=st.get("running", False), trading_state=_wa.controls.state,
        mode=st.get("mode", "replay"), timeframe=st.get("timeframe", "4h"),
        bars=st.get("bars", 0), signals=st.get("signals", 0),
        trades=st.get("trades", 0), rejections=st.get("rejections", 0),
        data_source=st.get("data_source"), last_activity_age_s=age,
        feed_error=st.get("feed_error"),
    )
    return {
        **verdict,
        "running": st.get("running", False),
        "mode": st.get("mode"),
        "timeframe": st.get("timeframe"),
        "data_source": st.get("data_source"),
        "feed_status": st.get("feed_status"),
        "feed_error": st.get("feed_error"),
        "bars": st.get("bars", 0), "signals": st.get("signals", 0),
        "trades": st.get("trades", 0), "rejections": st.get("rejections", 0),
        "last_bar_ts": st.get("last_bar_ts"),
        "last_activity_age_s": round(age, 0) if age is not None else None,
    }

# ------------------------------------------------------------- read (dashboard)
@router.get("/controls/state")
def control_state():
    return {"state": _wa.controls.state}


# ------------------------------------------------- Explainable Trading reports
@router.get("/engine/cycles")
def engine_cycles(limit: int = 100, symbol: Optional[str] = None,
                  decision: Optional[str] = None):
    """Per-cycle Decision Reports, newest first — EVERY analysis cycle is here,
    including WAIT candles. Filter by symbol or decision (BUY/SELL/WAIT/SKIP)."""
    return {"cycles": _wa.cycle_store.list(limit=max(1, min(limit, 500)),
                                           symbol=symbol, decision=decision),
            "total": _wa.cycle_store.count()}


@router.get("/engine/cycles/{cid}")
def engine_cycle(cid: int):
    """The COMPLETE Decision Report for one cycle: narrated market analysis,
    rule-by-rule checklist, five-category confidence score, decision, reasons
    and recommendation."""
    c = _wa.cycle_store.get(cid)
    if c is None:
        raise HTTPException(404, "No cycle report with that id")
    return c


# Timeframes the data layer supports end-to-end (live fetch, synthetic, engine).
_TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d")


@router.post("/engine/timeframe")
def engine_set_timeframe(timeframe: str,
                         x_webhook_secret: Optional[str] = Header(default=None)):
    """Switch the engine's candle timeframe (1m/5m/15m/1h/4h/1d) and restart it.

    The choice is persisted so it survives restarts/redeploys. 4h remains the
    walk-forward-validated config; lower timeframes give faster activity and
    count as their own experiment. Paper only — live stays locked."""
    _wa._check_secret(x_webhook_secret)
    tf = (timeframe or "").strip().lower()
    if tf not in _TIMEFRAMES:
        raise HTTPException(400, f"Unsupported timeframe '{timeframe}'. "
                                 f"Choose one of: {', '.join(_TIMEFRAMES)}.")
    _wa.engine.reconfigure(symbols=_wa.engine.symbols, timeframe=tf,
                           strategy_factory=_wa.engine.strategy_factory,
                           label=_wa.engine.strategy_label)
    # persist alongside the other runtime settings (applied again at boot)
    _wa.save_overrides(_wa.settings.settings_path, _wa._settings_snapshot())
    _wa.ledger.log(level="info", stage="audit",
                   message=f"Engine timeframe set to {tf} (engine restarted)")
    return {"applied": True, "timeframe": _wa.engine.timeframe,
            "options": list(_TIMEFRAMES)}
