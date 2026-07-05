"""Bots endpoints — split from webhook_api.py.

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


@router.get("/brokers")
def brokers_list():
    """Broker layer — one interface for Binance / Bybit / IBKR / Alpaca; paper is
    executable, live execution is locked by design (#14)."""
    return _wa.broker_registry.list()

@router.get("/bots/live")
def bots_live():
    """Each engine symbol as a live 'bot' with real per-symbol stats."""
    history = _wa.paper.history()
    st = _wa.engine.status()
    running = st.get("running", False)
    out = []
    for sym in _wa.engine.symbols:
        sym_trades = [t for t in history if t["symbol"] == sym]
        wins = sum(1 for t in sym_trades if (t.get("pnl") or 0) > 0)
        realized = sum((t.get("pnl") or 0.0) for t in sym_trades)
        pos = _wa.paper.open_position(sym)
        if not _wa.controls.trading_allowed():
            status = _wa.controls.state            # Paused / Stopped
        else:
            status = "Running" if running else "Stopped"
        out.append({
            "id": sym, "symbol": sym, "name": f"{sym} · {engine.strategy_label}",
            "strategy": _wa.engine.strategy_label, "timeframe": _wa.engine.timeframe, "status": status,
            "open": pos is not None,
            "side": pos["side"] if pos else None,
            "size": pos["size"] if pos else 0.0,
            "entry": pos["entry"] if pos else 0.0,
            "num_trades": len(sym_trades),
            "win_rate": (wins / len(sym_trades)) if sym_trades else 0.0,
            "realized_pnl": round(realized, 2),
        })
    return out
