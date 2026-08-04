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


#: Below this many trades in a window, a result is a sample-size artefact
#: rather than a measurement. Same floor the spec optimiser already applies.
_MIN_TRADES = 10


class OptimiseBody(_wa.BaseModel):
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    bars: int = 1000
    #: Which declared parameters to sweep. Empty = every tunable one, which is
    #: often too many — the endpoint refuses rather than running for an hour.
    only: List[str] = []
    #: Values pinned for parameters NOT being swept, so the search happens
    #: around the configuration actually being traded.
    overrides: Dict[str, float] = {}
    split: float = 0.7
    max_candidates: int = 200


@router.post("/strategies/installed/{key}/optimise")
def strategy_optimise(key: str, body: OptimiseBody):
    """Sweep a strategy's declared parameter grid over real candles.

    Optimises on the first ``split`` of history and re-scores the winner on the
    unseen remainder. Reporting an in-sample winner alone is overfitting with a
    progress bar; ``robust`` is what says whether the choice survived data the
    search never saw.

    Returns ``available: false`` with the reason when candles cannot be
    fetched — Binance answers HTTP 451 from datacenter IPs, which is where this
    deploys, so no data is a normal outcome and inventing bars to fill it would
    make every number here fiction.
    """
    from bots import registry as _reg
    from tradexa.strategy import OptimisationError, grid_search, split as _split

    cls = _reg.strategy_class(key)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy {key!r}")

    from data.live_data import fetch_ohlcv, last_error
    bars = fetch_ohlcv(body.symbol, timeframe=body.timeframe, limit=body.bars)
    if not bars:
        return {"available": False,
                "note": f"no candles for {body.symbol} {body.timeframe}"
                        f"{f' — {last_error()}' if last_error() else ''}",
                "strategy": key}

    train, test = _split(bars, body.split)
    if len(train) < 50 or len(test) < 20:
        return {"available": False,
                "note": f"only {len(bars)} candles returned — too few to split "
                        "into a search window and an out-of-sample check",
                "strategy": key}

    def _score(strategy_cls, params, window):
        from bot.backtester import Backtester
        result = Backtester(strategy_cls(symbol=body.symbol, **params),
                            list(window), timeframe=body.timeframe).run()
        m = result.metrics or {}
        trades = int(m.get("num_trades", 0) or 0)
        # Net R — average R times trade count — is what the platform's existing
        # spec optimiser ranks by. Using the same measure means two optimisers
        # cannot disagree about which configuration is better.
        net_r = float(m.get("avg_r", 0.0) or 0.0) * trades
        # A three-trade run is not a better strategy than a fifty-trade one with
        # the same R; it is a smaller sample. Ranked below every adequately
        # sampled candidate, but kept and reported rather than dropped.
        return {"score": net_r if trades >= _MIN_TRADES else net_r - 1e6 + trades,
                "net_r": round(net_r, 4), "trades": trades,
                "win_rate": round(float(m.get("win_rate", 0.0) or 0.0), 4),
                "profit_factor": round(float(m.get("profit_factor", 0.0) or 0.0), 4),
                "max_drawdown": round(float(m.get("max_dd", 0.0) or 0.0), 4)}

    try:
        result = grid_search(
            cls, lambda c, p: _score(c, p, train),
            only=body.only or None, overrides=body.overrides or None,
            validate_with=lambda c, p: _score(c, p, test),
            max_candidates=body.max_candidates)
    except OptimisationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"available": True, **result.as_dict(),
            "symbol": body.symbol, "timeframe": body.timeframe,
            "bars": len(bars), "train_bars": len(train), "test_bars": len(test),
            "score_basis": f"net R over the window; runs under {_MIN_TRADES} trades are "
                           "ranked last rather than dropped"}
