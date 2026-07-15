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


# ----------------------------------------------------- permanent trade memory
# The AI's long-term memory of every trade. Composed from REAL captured data;
# uncaptured fields are marked honestly. Remembered forever unless deleted.
@router.get("/trade-memory/trades")
def trade_memory_trades(limit: int = 200, q: Optional[str] = None,
                        symbol: Optional[str] = None, result: Optional[str] = None,
                        strategy: Optional[str] = None, session: Optional[str] = None):
    """The trade timeline. Full-text search via ``q``; exact facet filters for
    symbol / result / strategy / session."""
    rows = _wa.trade_memory_store.list(limit=max(1, min(limit, 1000)), q=q,
                                       symbol=symbol, result=result,
                                       strategy=strategy, session=session)
    return {"trades": rows, "total": _wa.trade_memory_store.count()}


@router.get("/trade-memory/growth")
def trade_memory_growth():
    """Growth Journey — the bot's performance memory summarised from remembered
    trades only: lifetime record, expectancy, streaks, month-by-month progress
    and per-strategy / per-symbol splits. Honest empty state until the first
    trade is remembered; small samples labelled as provisional."""
    from services.growth_journey import build_growth
    return build_growth(_wa.trade_memory_store.list(limit=5000))


@router.get("/trade-memory/ask")
def trade_memory_ask(q: str, limit: int = 50):
    """Natural-language query over the memory ('show all losing BTC trades',
    'which setup has the highest expectancy?', 'why am I losing on Mondays?')."""
    return _wa.trade_memory.ask(q, limit=max(1, min(limit, 200)))


@router.get("/trade-memory/insights")
def trade_memory_insights():
    """Pattern recognition + data-driven coaching over the whole memory:
    win rate by weekday/symbol/strategy/session, best/worst setups, mistake
    library, winning patterns, Sharpe/Sortino/expectancy/max-drawdown. All
    computed from real trades; coaching is sample-gated."""
    return _wa.trade_memory.insights()


@router.get("/trade-memory/mistakes")
def trade_memory_mistakes():
    """The mistake library — recorded mistakes ranked by frequency, with the
    loss attributed and whether the mistake repeats."""
    return {"mistakes": _wa.trade_memory.insights().get("mistakes", [])}


@router.get("/trade-memory/reviews")
def trade_memory_reviews(period: Optional[str] = None, limit: int = 12):
    """Persisted weekly/monthly/yearly (and nightly) reviews. ``period`` one of
    nightly | weekly | monthly | yearly."""
    if period and period not in ("nightly", "weekly", "monthly", "yearly"):
        raise HTTPException(400, "period must be nightly|weekly|monthly|yearly")
    return {"reviews": _wa.trade_memory.reviews(period, max(1, min(limit, 60)))}


@router.get("/trade-memory/similar/{trade_id}")
def trade_memory_similar(trade_id: str, limit: int = 5):
    """Trades most similar to this one (cosine over a numeric feature vector —
    honest local retrieval, not an LLM embedding)."""
    if _wa.trade_memory_store.get(trade_id) is None:
        raise HTTPException(404, "No memory for that trade id")
    return {"similar": _wa.trade_memory.similar(trade_id, max(1, min(limit, 25)))}


@router.get("/trade-memory/{trade_id}")
def trade_memory_get(trade_id: str):
    """The full 8-category memory for one trade."""
    m = _wa.trade_memory_store.get(trade_id)
    if m is None:
        raise HTTPException(404, "No memory for that trade id")
    return m


@router.patch("/trade-memory/{trade_id}/notes")
def trade_memory_notes(trade_id: str, body: Dict = Body(...),
                       x_webhook_secret: Optional[str] = Header(default=None)):
    """Attach the trader's manual journal note (e.g. 'FOMO', 'entered early')."""
    _wa._check_secret(x_webhook_secret)
    if not _wa.trade_memory.set_notes(trade_id, str(body.get("notes", ""))):
        raise HTTPException(404, "No memory for that trade id")
    return _wa.trade_memory_store.get(trade_id)


@router.delete("/trade-memory/{trade_id}")
def trade_memory_delete(trade_id: str,
                        x_webhook_secret: Optional[str] = Header(default=None)):
    """Permanently forget one trade — the ONLY way a memory is ever removed."""
    _wa._check_secret(x_webhook_secret)
    return {"deleted": _wa.trade_memory.delete(trade_id)}


@router.post("/trade-memory/backfill")
def trade_memory_backfill(x_webhook_secret: Optional[str] = Header(default=None)):
    """Import already-closed journal trades that aren't in memory yet."""
    _wa._check_secret(x_webhook_secret)
    return _wa.trade_memory.backfill()


@router.post("/trade-memory/reviews/run")
def trade_memory_run_reviews(x_webhook_secret: Optional[str] = Header(default=None)):
    """Run the nightly/weekly/monthly/yearly reviews now (on-demand)."""
    _wa._check_secret(x_webhook_secret)
    return _wa.trade_memory.run_reviews()


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
