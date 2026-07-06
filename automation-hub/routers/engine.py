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


# ------------------------------------------------------------------- webhook
@router.post("/webhook/tradingview")
def tradingview_webhook(payload: _wa.WebhookPayload,
                        x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
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
