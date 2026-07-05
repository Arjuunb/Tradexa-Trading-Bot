"""Risk endpoints — split from webhook_api.py.

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


@router.get("/risk/summary")
def risk_summary():
    """Live risk usage: exposure vs limit, open trades vs max, rejections."""
    positions = _wa.paper.positions()
    equity = _wa.paper.balance()
    notional = sum((p["size"] * p["entry"]) for p in positions)
    st = _wa.engine.status()
    return {
        "equity": equity,
        "realized_pnl": _wa.paper.realized_pnl(),
        "open_positions": len(positions),
        "max_open_positions": _wa.settings.max_open_positions,
        "exposure_notional": notional,
        "exposure_pct": (notional / equity) if equity > 0 else 0.0,
        "exposure_limit_pct": _wa.settings.exposure_limit_pct,
        "risk_per_trade_pct": _wa.settings.risk_per_trade_pct,
        "rejections": st.get("rejections", 0),
        "signals": st.get("signals", 0),
        "trading_state": _wa.controls.state,
        "engine_running": st.get("running", False),
        "max_drawdown_pct": _wa.settings.max_drawdown_pct,
        "auto_halted": _wa.pipeline.halted,
        "halt_reason": _wa.pipeline.halt_reason,
    }

@router.post("/risk/position-size")
def risk_position_size(body: _wa.PositionSizeRequest):
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
    raw = _wa.paper.positions()
    equity = _wa.paper.balance()
    pos = [{"symbol": p.get("symbol", ""), "direction": p.get("side", "long"),
            "notional": float(p.get("size", 0)) * float(p.get("entry", 0)),
            "risk": abs(float(p.get("entry", 0)) - float(p.get("stop") or p.get("entry", 0))) * float(p.get("size", 0))}
           for p in raw]
    out = portfolio_risk(equity, pos, timeframe=timeframe, conf=conf,
                         exposure_warn=_wa.settings.exposure_limit_pct)
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

@router.get("/risk/recovery")
def risk_recovery():
    """Drawdown Recovery — current drawdown off the equity peak and the
    protective actions / risk multiplier it recommends (#18)."""
    from services.recovery import drawdown_recovery
    trades = sorted((t for t in _wa.paper.history() if t.get("closed_at")), key=lambda t: t["closed_at"])
    eq = peak = _wa.paper.starting_balance
    for t in trades:
        eq += (t.get("pnl") or 0.0)
        peak = max(peak, eq)
    equity = _wa.paper.balance()
    out = drawdown_recovery(peak, equity)
    out["equity"] = round(equity, 2); out["peak_equity"] = round(peak, 2)
    return out
