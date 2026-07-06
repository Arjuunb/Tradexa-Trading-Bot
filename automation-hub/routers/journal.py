"""Journal endpoints — split from webhook_api.py.

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


@router.get("/journal")
def journal_list():
    """Trade journal entries (auto-created from trades, human-editable)."""
    return {"entries": _wa.journal_store.list()}

@router.post("/journal/from-replay")
def journal_from_replay(symbol: str = "BTCUSDT", strategy: str = "Decision Brain",
                        timeframe: str = "15m", limit: int = 800,
                        x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Auto-journal every closed trade from a real replay run (#11)."""
    _wa._check_secret(x_webhook_secret)
    from services.replay import build_replay
    rep = build_replay(symbol, timeframe, limit, strategy=strategy)
    if rep["meta"]["bars"] == 0:
        raise _wa.HTTPException(400, rep["meta"].get("data_warning", "No data."))
    closed = [t for t in rep["trades"] if t.get("rr") is not None]
    added = _wa.journal_store.add_from_trades(closed, symbol=symbol, strategy=strategy, timeframe=timeframe)
    return {"added": len(added), "entries": added}

@router.patch("/journal/{eid}")
def journal_update(eid: str, body: _wa.JournalEdit, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Edit the human fields of a journal entry."""
    _wa._check_secret(x_webhook_secret)
    r = _wa.journal_store.update(eid, body.model_dump(exclude_none=True))
    if r is None:
        raise _wa.HTTPException(404, "Entry not found")
    return r

@router.delete("/journal/{eid}")
def journal_delete(eid: str, x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    return {"deleted": _wa.journal_store.delete(eid)}

@router.get("/skipped/trades")
def skipped_trades(limit: int = 100, symbol: _wa.Optional[str] = None,
                   stage: _wa.Optional[str] = None, q: _wa.Optional[str] = None):
    """Every setup the bot rejected — newest first — with the exact reason, the
    gate that failed, and the market snapshot. Filter by symbol / stage or
    free-text search across reason + symbol + stage."""
    return {"trades": _wa.skipped_store.list(limit=max(1, min(limit, 500)),
                                         symbol=symbol, stage=stage, q=q)}

@router.get("/skipped/summary")
def skipped_summary():
    """Count of skips per failed gate — where the bot most often says 'no'."""
    return {"stages": _wa.skipped_store.summary()}

@router.get("/journal/trades")
def journal_trades(limit: int = 100, mode: _wa.Optional[str] = None,
                   symbol: _wa.Optional[str] = None, result: _wa.Optional[str] = None):
    """List trades that have a decision journal (newest first), with summary +
    grade. Filter by mode / symbol / result. The full journal is at
    GET /journal/{trade_id}."""
    return {"trades": _wa.decision_journal_store.list(limit=max(1, min(limit, 500)), mode=mode,
                                                  symbol=symbol, result=result)}

@router.get("/journal/evolution")
def journal_evolution():
    """Aggregated evolution memory per setup (strategy·regime·side) with the
    early-signal / building / evidence staging that governs how much a pattern
    can be trusted. Never auto-changes risk."""
    return {"setups": _wa.decision_journal_store.evolution()}

@router.get("/journal/{trade_id}")
def journal_trade(trade_id: str):
    """The full decision journal for one trade: summary, entry decision, rule
    checklist, market snapshot, risk check, timeline, exit decision, post-trade
    review and evolution note."""
    j = _wa.decision_journal_store.get(trade_id)
    if j is None:
        raise _wa.HTTPException(404, "No journal for that trade id")
    return j


@router.get("/decisions/latest")
def decisions_latest(limit: int = 50, symbol: Optional[str] = None):
    """The most recent trade decisions — accepted AND rejected — with the full
    unified decision object (scores, rules, reason, executed)."""
    return {"decisions": _wa.decision_store.list(limit=max(1, min(limit, 200)),
                                                 symbol=symbol)}


@router.get("/decisions/rejected")
def decisions_rejected(limit: int = 50, symbol: Optional[str] = None):
    """Only the rejected signals, newest first — why the bot said no."""
    return {"decisions": _wa.decision_store.list(limit=max(1, min(limit, 200)),
                                                 decision="rejected", symbol=symbol)}


@router.get("/decisions/state")
def decisions_state():
    """One-call dashboard state: current bot state, risk status, active
    positions and the latest decisions — all real, nothing fabricated."""
    st = _wa.engine.status()
    positions = _wa.paper.positions()
    equity = _wa.paper.balance()
    notional = sum((p["size"] * p["entry"]) for p in positions)
    return {
        "bot": {
            "running": st.get("running", False),
            "mode": st.get("mode"),
            "strategy": st.get("strategy"),
            "timeframe": st.get("timeframe"),
            "feed_status": st.get("feed_status"),
            "trading_state": _wa.controls.state,
            "bars": st.get("bars", 0), "signals": st.get("signals", 0),
            "trades": st.get("trades", 0), "rejections": st.get("rejections", 0),
        },
        "risk": {
            "equity": equity,
            "exposure_pct": (notional / equity) if equity > 0 else 0.0,
            "open_positions": len(positions),
            "max_open_positions": _wa.settings.max_open_positions,
            "auto_halted": _wa.pipeline.halted,
            "halt_reason": _wa.pipeline.halt_reason,
        },
        "positions": positions,
        "latest_decisions": _wa.decision_store.list(limit=10),
    }
