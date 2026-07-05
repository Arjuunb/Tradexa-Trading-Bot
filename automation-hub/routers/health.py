"""Health endpoints — split from webhook_api.py.

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


@router.get("/health/scorecard")
def health_scorecard_endpoint(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                              timeframe: str = "15m", limit: int = 800):
    """Strategy Health scorecard — win rate / PF / drawdown / expectancy plus
    Stability and Confidence scores, with an auto unhealthy flag (#10)."""
    from services.replay import build_replay
    from services.recovery import health_scorecard
    rep = build_replay(symbol, timeframe, limit, strategy=strategy)
    if rep["meta"]["bars"] == 0:
        return {"available": False, "error": rep["meta"].get("data_warning", "No data."),
                "needs_download": rep["meta"].get("needs_download", False)}
    trades = [{"pnl": t["rr"], "r": t["rr"]} for t in rep["trades"] if t.get("rr") is not None]
    card = health_scorecard(trades)
    card.update({"available": True, "symbol": symbol, "strategy": strategy})
    return card

@router.get("/bot-os")
def bot_os_snapshot():
    """Bot Operating System — the nine engines, their live state and recent
    events on the shared bus (#20)."""
    # reflect live data freshness for the Market engine before snapshotting
    try:
        cov = _wa.market_store.all_coverage()
        have = sum(1 for c in cov if (c.get("candles") or 0) > 0)
        _wa.bot_os.set_status_fn("Market Engine", lambda h=have, n=len(cov):
                             {"state": "up" if h else "idle", "detail": f"{h}/{n} datasets cached"})
    except Exception:  # noqa: BLE001
        pass
    return _wa.bot_os.snapshot()

@router.get("/production/readiness")
def production_readiness():
    """Production Readiness — API / DB / data freshness / errors / memory /
    engine uptime in one operational status (#19)."""
    from services.production import readiness
    # database + data coverage
    db_ok, db_detail, coverage = True, "SQLite reachable", []
    try:
        coverage = _wa.market_store.all_coverage()
    except Exception as e:  # noqa: BLE001
        db_ok, db_detail = False, f"market store error: {str(e)[:80]}"
    # recent errors from the ledger, split into strategy vs order/execution
    strat_err = order_err = 0
    try:
        for row in _wa.ledger.get_logs(200):
            if str(row.get("level", "")).lower() in ("error", "critical"):
                stage = str(row.get("stage", "")).lower()
                if stage in ("execution", "order", "paper", "risk"):
                    order_err += 1
                else:
                    strat_err += 1
    except Exception:  # noqa: BLE001
        pass
    st = _wa.engine.status()
    return readiness(api_ok=True, db_ok=db_ok, db_detail=db_detail, coverage=coverage,
                     strategy_errors=strat_err, order_errors=order_err,
                     uptime_s=round(_wa.time.time() - _wa._BOOT, 0), engine_running=st.get("running", False))

@router.get("/safety/live-readiness")
def safety_live_readiness():
    """The enforced live-trading checklist. Every item is computed from real
    state; ``live_allowed`` is only True when all pass and the build's hard lock
    is off (it is always on here — paper mode only)."""
    from services.safety_gate import build_live_readiness
    try:
        closed = sum(1 for t in _wa.ledger.get_paper_trades()
                     if str(t.get("status")) == "closed")
    except Exception:  # noqa: BLE001
        closed = 0
    return build_live_readiness(
        hard_locked=_wa.broker_registry.live_locked(),
        closed_paper_trades=closed,
        max_daily_loss_pct=float(getattr(_wa.settings, "max_daily_loss_pct", 0) or 0),
        max_drawdown_pct=float(getattr(_wa.settings, "max_drawdown_pct", 0) or 0),
        broker_connected=_wa._broker_live_connected(),
        decision_logging=getattr(_wa.pipeline, "journal", None) is not None,
        emergency_stop_tested_at=_wa.safety_state.emergency_stop_tested_at(),
    )

@router.post("/safety/test-emergency-stop")
def safety_test_emergency_stop(x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Verify the kill switch really halts trading, then restore the prior state
    and record the test. This actually exercises stop_all — it does not fake it."""
    _wa._check_secret(x_webhook_secret)
    prior = _wa.controls.state
    _wa.controls.stop_all()
    verified = _wa.controls.state == "Stopped"
    # restore whatever the operator had before the drill
    if prior == "Active":
        _wa.controls.resume()
    elif prior == "Paused":
        _wa.controls.resume()
        _wa.controls.pause_all()
    # if prior was "Stopped", leave it stopped
    tested_at = _wa.safety_state.mark_emergency_stop_tested() if verified else None
    _wa.ledger.log(level="info" if verified else "error", stage="safety",
               message=f"Emergency-stop test: {'verified' if verified else 'FAILED'} "
                       f"(restored to {prior})")
    return {"ok": verified, "verified": verified, "prior_state": prior,
            "state_after": _wa.controls.state, "tested_at": tested_at}

@router.get("/health/bot")
def health_bot():
    """One-call Bot Health — engine, data source, broker, last candle / signal /
    rejection, open positions, today's P&L, risk usage, watchdog and the latest
    errors. Every field is real; nothing is fabricated."""
    from datetime import datetime, timezone
    st = _wa.engine.status()
    positions = _wa.paper.positions()
    equity = _wa.paper.balance()
    try:
        trades = _wa.ledger.get_paper_trades()
    except Exception:  # noqa: BLE001
        trades = []

    last_trade = max(trades, key=lambda t: str(t.get("opened_at") or ""), default=None) if trades else None
    last_rej = (_wa.skipped_store.list(limit=1) or [None])[0]

    today = datetime.now(timezone.utc).date().isoformat()
    daily_pnl = sum((t.get("pnl") or 0) for t in trades
                    if str(t.get("status")) == "closed" and str(t.get("closed_at") or "").startswith(today))

    errors = []
    try:
        for row in _wa.ledger.get_logs(200):
            if str(row.get("level", "")).lower() in ("error", "critical"):
                errors.append({"ts": row.get("ts"), "stage": row.get("stage"),
                               "message": row.get("message"), "symbol": row.get("symbol")})
                if len(errors) >= 8:
                    break
    except Exception:  # noqa: BLE001
        pass

    notional = sum((p["size"] * p["entry"]) for p in positions)
    return {
        "engine": {
            "running": st.get("running", False),
            "mode": st.get("mode"),
            "strategy": _wa.engine.strategy_label,
            "symbols": _wa.engine.symbols,
            "timeframe": _wa.engine.timeframe,
            "bars_processed": st.get("bars", 0),
            "signals": st.get("signals", 0),
            "trades": st.get("trades", 0),
            "rejections": st.get("rejections", 0),
            "uptime_s": round(_wa.time.time() - _wa._BOOT, 0),
            "started_at": st.get("started_at"),
        },
        "data_source": "live (ccxt)" if _wa.engine.live else "synthetic / replay",
        "broker": {
            "connected": _wa._broker_live_connected(),
            "active": "paper",
            "live_locked": _wa.broker_registry.live_locked(),
            "note": "paper execution only — no live venue connected",
        },
        "last_candle": {"symbol": (_wa.engine.symbols[0] if _wa.engine.symbols else None),
                        "ts": st.get("last_bar_ts")},
        "last_signal": (None if not last_trade else {
            "symbol": last_trade.get("symbol"), "side": last_trade.get("side"),
            "entry": last_trade.get("entry"), "ts": last_trade.get("opened_at")}),
        "last_rejected": (None if not last_rej else {
            "symbol": last_rej.get("symbol"), "side": last_rej.get("side"),
            "stage": last_rej.get("stage"), "reason": last_rej.get("reason"),
            "ts": last_rej.get("ts")}),
        "open_positions": len(positions),
        "daily_pnl": round(daily_pnl, 2),
        "risk": {
            "equity": equity,
            "exposure_pct": (notional / equity) if equity > 0 else 0.0,
            "exposure_limit_pct": _wa.settings.exposure_limit_pct,
            "open_positions": len(positions),
            "max_open_positions": _wa.settings.max_open_positions,
            "trading_state": _wa.controls.state,
            "auto_halted": _wa.pipeline.halted,
            "halt_reason": _wa.pipeline.halt_reason,
            "max_drawdown_pct": _wa.settings.max_drawdown_pct,
        },
        "watchdog": _wa.watchdog.status(),
        "errors": errors,
    }

@router.post("/ops/backup")
def ops_backup(x_webhook_secret: str = _wa.Header(default="")):
    """Snapshot every database and JSON store now (consistent sqlite copies)."""
    _wa._check_secret(x_webhook_secret)
    import config as _cfg
    from services.backup import backup_now
    res = backup_now(str(_cfg.DATA_DIR))
    _wa.ledger.log(level="info", stage="ops",
               message=f"Manual backup: {res.get('snapshot', res.get('error'))}")
    return res

@router.get("/ops/backups")
def ops_backups():
    import config as _cfg
    from services.backup import list_backups
    return list_backups(str(_cfg.DATA_DIR))

@router.post("/ops/drill")
def ops_drill(x_webhook_secret: str = _wa.Header(default="")):
    """Run the failure drills (crash-mid-position, backup-restore,
    reconciliation, kill-switch) against temporary state. A failing drill is
    a red alert — it means a recovery path is broken."""
    _wa._check_secret(x_webhook_secret)
    from services.drill import run_drills
    res = run_drills()
    level = "info" if res["ok"] else "error"
    _wa.ledger.log(level=level, stage="ops",
               message=f"Failure drills: {res['passed']}/{res['total']} passed")
    if not res["ok"]:
        _wa.ledger.add_alert(severity="critical", category="ops",
                         title="Failure drill FAILED",
                         detail="; ".join(r["drill"] for r in res["results"] if not r["ok"]))
    return res

@router.get("/ops/watchdog")
def ops_watchdog():
    """Watchdog heartbeat + current findings (stalled feed, dead engine thread,
    degraded websocket) and the live feed's stream status."""
    return _wa.watchdog.status()

@router.get("/ops/storage")
def ops_storage():
    """Where the bot's state lives, and whether it survives a redeploy. On
    cloud hosts without a persistent disk everything here is EPHEMERAL."""
    import config as _cfg
    paths = {"ledger": _wa.settings.ledger_path, "market_data": _wa.settings.market_db,
             "learning": _wa.learning_book.path, "runtime_settings": _wa.settings.settings_path,
             "providers": _wa.settings.providers_path}
    files = {}
    for name, p in paths.items():
        try:
            files[name] = {"path": p, "exists": _wa._os.path.exists(p),
                           "bytes": _wa._os.path.getsize(p) if _wa._os.path.exists(p) else 0}
        except OSError:
            files[name] = {"path": p, "exists": False, "bytes": 0}
    data_dir_set = bool(_wa._os.environ.get("HUB_DATA_DIR"))
    on_cloud = bool(_wa._os.environ.get("RENDER") or _wa._os.environ.get("DYNO"))
    warning = None
    if on_cloud and not data_dir_set:
        warning = ("Storage is EPHEMERAL: every redeploy wipes trade history, cached "
                   "candles and learned lessons. Attach a persistent disk and set "
                   "HUB_DATA_DIR to its mount path.")
    return {"data_dir": str(_cfg.DATA_DIR), "hub_data_dir_set": data_dir_set,
            "persistent": data_dir_set or not on_cloud, "warning": warning,
            "files": files}


@router.get("/validation/paper")
def validation_paper():
    """Paper-trading validation readiness (Phase 8) — real closed trades, skip
    log and Safety Center rolled into a single human-review verdict. Never
    unlocks live trading; live stays hard-locked regardless of this result."""
    from services.performance import summarize
    from services.safety_gate import build_live_readiness
    from services.paper_validation import build_paper_validation

    trades = _wa.paper.history()
    perf = summarize(trades, _wa.paper.starting_balance)

    rr = [float(t["rr"]) for t in trades if t.get("rr") is not None]
    avg_rr = (sum(rr) / len(rr)) if rr else 0.0

    # per-symbol net P&L from the real closed trades
    by_sym: dict = {}
    for t in trades:
        if t.get("pnl") is not None:
            by_sym[t["symbol"]] = round(by_sym.get(t["symbol"], 0.0) + float(t["pnl"]), 2)
    per_symbol = [{"name": s, "net_pnl": v} for s, v in by_sym.items()]

    # per-strategy net R from the decision journal's evolution memory (real)
    by_strat: dict = {}
    try:
        for e in _wa.decision_journal_store.evolution():
            by_strat[e["strategy"]] = round(by_strat.get(e["strategy"], 0.0) + float(e.get("net_r", 0)), 2)
    except Exception:  # noqa: BLE001
        pass
    per_strategy = [{"name": s, "net_r": v} for s, v in by_strat.items()]

    closed = sum(1 for t in trades if str(t.get("status")) == "closed")
    readiness = build_live_readiness(
        hard_locked=_wa.broker_registry.live_locked(),
        closed_paper_trades=closed,
        max_daily_loss_pct=float(getattr(_wa.settings, "max_daily_loss_pct", 0) or 0),
        max_drawdown_pct=float(getattr(_wa.settings, "max_drawdown_pct", 0) or 0),
        broker_connected=_wa._broker_live_connected(),
        decision_logging=getattr(_wa.pipeline, "journal", None) is not None,
        emergency_stop_tested_at=_wa.safety_state.emergency_stop_tested_at(),
    )

    return build_paper_validation(
        perf=perf, avg_rr=avg_rr, per_symbol=per_symbol, per_strategy=per_strategy,
        skipped_total=_wa.skipped_store.total(),
        skipped_by_category=_wa.skipped_store.categories(),
        readiness=readiness)


@router.get("/validation/daily-report")
def validation_daily_report(day_index: Optional[int] = None):
    """Daily paper-validation digest — closed-trade summary, new skip reasons,
    risk events, health errors, and whether validation is improving or
    weakening. All from real stored data; live trading stays LOCKED."""
    from services.strategy_health import StrategyHealthMonitor
    from services.validation_report import build_daily_report

    validation = validation_paper()   # same real-data verdict as /validation/paper

    hist = [{**t, "r": (t.get("rr") if t.get("rr") is not None else 0.0)}
            for t in _wa.paper.history()]
    health = StrategyHealthMonitor().evaluate(hist).to_dict()

    # risk events = recent skips in the risk/safety categories (real failed gates)
    risk_events = [
        {"ts": s["ts"], "symbol": s["symbol"], "category": s["category"],
         "stage": s["stage"], "reason": s["reason"]}
        for s in _wa.skipped_store.list(limit=50)
        if s.get("category") in ("risk", "safety")
    ][:10]

    # health errors = recent error/critical log lines
    health_errors = []
    try:
        for row in _wa.ledger.get_logs(200):
            if str(row.get("level", "")).lower() in ("error", "critical"):
                health_errors.append({"ts": row.get("ts"), "stage": row.get("stage"),
                                      "message": row.get("message")})
                if len(health_errors) >= 8:
                    break
    except Exception:  # noqa: BLE001
        pass

    return build_daily_report(
        validation=validation,
        recent=health.get("recent", {}),
        previous=health.get("previous", {}),
        risk_events=risk_events,
        health_errors=health_errors,
        day_index=day_index)
