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


# ── strategy plugins ────────────────────────────────────────────────────────
# The installed strategies, as data. Everything here comes from what each
# strategy DECLARES about itself — nothing is maintained in this file, which is
# the point of the plugin registry: adding a strategy adds an entry here without
# anyone editing this endpoint.

@router.get("/strategies/installed")
def strategies_installed(refresh: bool = False):
    """Every installed strategy with its metadata, version, parameters,
    optimisation grid and generated documentation.

    ``refresh=true`` rescans the plugins directory — how a strategy dropped in
    while the process is running becomes visible without a restart.

    ``errors`` lists plugins that failed to load and why. A broken third-party
    file must not stop the rest from loading, but it must not vanish either:
    the author's only clue would otherwise be a strategy that never appears.
    """
    from bots import registry as _reg
    if refresh:
        _reg.STRATEGIES.refresh()
    return {
        "strategies": _reg.describe_strategies(),
        "offerable": [c.meta.key for c in _reg.registry().offerable()],
        "errors": _reg.discovery_errors(),
        "plugins_dir": str(_reg.PLUGINS_DIR),
    }


@router.get("/strategies/installed/{key}")
def strategy_detail(key: str):
    """One strategy, including its generated reference documentation."""
    from bots import registry as _reg
    cls = _reg.strategy_class(key)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy {key!r}")
    return {**cls.describe(), "documentation": cls.docs()}


@router.post("/strategies/installed/{key}/validate")
def strategy_validate(key: str, params: dict = Body(default={})):
    """Check a parameter set WITHOUT constructing anything.

    Reports every problem at once rather than the first — being told "fast must
    be below slow", fixing it and then being told the period is out of range is
    two round trips for one form submission.
    """
    from bots import registry as _reg
    cls = _reg.strategy_class(key)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy {key!r}")
    return cls.validate_params(params or {}).as_dict()
