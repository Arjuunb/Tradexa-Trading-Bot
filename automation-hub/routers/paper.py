"""Paper endpoints — split from webhook_api.py.

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


def _persistence_status() -> dict:
    """Is account/trade state actually persistent? Supabase counts only when it
    really CONNECTED at boot (probe passed) — configured-but-broken shows the
    exact error instead of silently claiming persistence."""
    from data import ledger as _ledger_mod
    env = _wa._os.environ.get
    on_cloud = bool(env("RENDER") or env("DYNO"))
    data_dir_set = bool(env("HUB_DATA_DIR"))
    sb = _ledger_mod.SUPABASE_STATUS
    supabase_ok = bool(sb.get("connected"))
    persistent = data_dir_set or supabase_ok or not on_cloud
    warning = None
    if sb.get("configured") and not supabase_ok:
        warning = ("Supabase is configured but NOT connected "
                   f"({sb.get('error') or 'unknown error'}) — using local SQLite. "
                   "Run automation-hub/data/ledger_schema.sql in the Supabase SQL "
                   "editor and verify SUPABASE_URL / SUPABASE_KEY (service_role), "
                   "then redeploy.")
        if not persistent:
            warning += " Until fixed, capital and trades may reset on redeploy."
    elif not persistent:
        warning = ("No persistent storage configured — capital and trades may "
                   "reset on redeploy. Free fix: set SUPABASE_URL + SUPABASE_KEY "
                   "(free Supabase Postgres), or attach a disk and set HUB_DATA_DIR.")
    return {"persistent": persistent, "supabase": supabase_ok,
            "data_dir": data_dir_set, "warning": warning}


@router.get("/paper/account")
def paper_account():
    """Paper account with initial_capital and current_equity kept SEPARATE and
    the current values persisted, so capital survives logout / refresh / restart
    (with HUB_DATA_DIR). Legacy keys (starting_balance / balance) are kept."""
    acct = _wa.account_store.get() or {}
    realized = _wa.paper.realized_pnl()
    initial = float(acct.get("initial_capital", _wa.paper.starting_balance))
    current_equity = _wa.paper.balance()          # initial + realized P&L
    available = _wa.paper.available_balance()
    persist = _persistence_status()
    return {
        # separated, persisted concepts
        "initial_capital": initial,
        "current_equity": current_equity,
        "available_balance": available,
        "realized_pnl": realized,
        "fees_paid": _wa.paper.fees_paid(),
        "unrealized_pnl": float(acct.get("unrealized_pnl", 0.0)),
        "last_updated": acct.get("last_updated"),
        "open_positions": len(_wa.paper.positions()),
        "persistent": persist["persistent"],
        "storage": ("supabase" if persist["supabase"] else "disk" if persist["data_dir"] else "ephemeral"),
        "warning": persist["warning"],
        # legacy keys (unchanged) so existing callers keep working
        "starting_balance": initial,
        "balance": current_equity,
    }


class InitialCapital(_wa.BaseModel):
    amount: float
    confirm: bool = False       # must be true — resets the paper account
    reset_trades: bool = True   # clear trade history so equity == new initial


@router.post("/paper/initial-capital")
def paper_set_initial_capital(body: InitialCapital,
                              x_webhook_secret: Optional[str] = Header(default=None)):
    """Change the initial capital. This RESETS the paper account, so it requires
    an explicit ``confirm: true``. Never touches live trading."""
    _wa._check_secret(x_webhook_secret)
    if not body.confirm:
        raise HTTPException(400, "Changing initial capital resets the paper account — "
                                 "resend with confirm=true to proceed.")
    if body.amount <= 0:
        raise HTTPException(400, "initial capital must be positive")
    if body.reset_trades:
        try:
            _wa.ledger.reset_paper()   # clears trades + positions if supported
        except Exception:  # noqa: BLE001 — some ledgers can't reset; snapshot still resets
            pass
    _wa.account_store.set_initial_capital(body.amount, reset_account=True)
    _wa.paper.starting_balance = body.amount
    _wa.paper._persist_account_snapshot()
    _wa.ledger.log(level="warning", stage="account",
                   message=f"Initial capital set to {body.amount} — paper account reset.")
    return {"ok": True, **(paper_account())}

@router.get("/paper/positions")
def paper_positions():
    return _wa.paper.positions()


class ClosePosition(_wa.BaseModel):
    symbol: str
    # optional client-observed mark (the terminal already streams the live
    # price); the server prefers its OWN fetched price and only uses this if it
    # can't reach a data source — it is never used to fabricate a fill.
    price: Optional[float] = None


@router.post("/paper/close")
def paper_close(body: ClosePosition,
                x_webhook_secret: Optional[str] = Header(default=None)):
    """Manually close an open PAPER position at the current market price through
    the real paper execution engine (same close path the engine uses on a
    stop/target). Never touches live trading."""
    _wa._check_secret(x_webhook_secret)
    symbol = (body.symbol or "").upper().strip()
    if not symbol:
        raise HTTPException(400, "symbol is required")
    pos = _wa.paper.open_position(symbol)
    if pos is None:
        raise HTTPException(404, f"No open paper position for {symbol}.")
    # real current price: latest candle close (crypto/Yahoo). Fall back to the
    # client's observed mark only if the server can't fetch one right now.
    price = None
    try:
        from data.market_data import get_bars
        bars, _src = get_bars(symbol, n=3, timeframe="1h")
        if bars:
            price = float(bars[-1].close)
    except Exception:  # noqa: BLE001 — fetch failure falls through to client mark
        price = None
    if price is None and body.price and float(body.price) > 0:
        price = float(body.price)
    if price is None or price <= 0:
        raise HTTPException(503, "Could not determine a current market price to close at. "
                                 "Try again once market data is reachable.")
    res = _wa.paper.close(symbol=symbol, exit_price=price)
    if getattr(res, "action", "") != "closed":
        raise HTTPException(409, f"Could not close {symbol} — position not open.")
    _wa.ledger.log(level="info", stage="execution",
                   message=f"Manual close {symbol} @ {round(price, 6)} — "
                           f"realized {res.pnl:+.2f}")
    return {"ok": True, "symbol": symbol, "exit_price": round(price, 6),
            "pnl": round(res.pnl, 2), "size": res.size, "side": res.side,
            **paper_account()}

@router.get("/paper/trades")
def paper_trades():
    return _wa.paper.history()

@router.get("/ledger/logs")
def ledger_logs(limit: int = 200):
    return _wa.ledger.get_logs(limit)

@router.get("/ledger/alerts")
def ledger_alerts(limit: int = 100):
    return _wa.ledger.get_alerts(limit)

@router.get("/ledger/logs/export")
def export_logs(fmt: str = "csv", limit: int = 2000):
    return _wa._export(_wa.ledger.get_logs(limit), ["ts", "level", "stage", "symbol", "message"], fmt, "decision_logs")

@router.get("/ledger/alerts/export")
def export_alerts(fmt: str = "csv", limit: int = 1000):
    return _wa._export(_wa.ledger.get_alerts(limit), ["ts", "severity", "category", "title", "detail"], fmt, "alerts")

@router.get("/paper/trades/export")
def export_trades(fmt: str = "csv"):
    return _wa._export(_wa.paper.history(), ["symbol", "side", "size", "entry", "exit", "pnl", "rr",
                                     "opened_at", "closed_at"], fmt, "paper_trades")

@router.get("/paper/equity-curve")
def paper_equity_curve():
    """Realized-equity curve: starting balance + cumulative closed-trade P&L."""
    trades = sorted((t for t in _wa.paper.history() if t.get("closed_at")),
                    key=lambda t: t["closed_at"])
    eq = _wa.paper.starting_balance
    points = [{"t": None, "equity": round(eq, 2)}]
    for t in trades:
        eq += (t.get("pnl") or 0.0)
        points.append({"t": t.get("closed_at"), "equity": round(eq, 2)})
    return {"starting_balance": _wa.paper.starting_balance, "points": points}
