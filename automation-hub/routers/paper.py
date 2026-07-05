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


@router.get("/paper/account")
def paper_account():
    return {
        "starting_balance": _wa.paper.starting_balance,
        "balance": _wa.paper.balance(),
        "realized_pnl": _wa.paper.realized_pnl(),
        "open_positions": len(_wa.paper.positions()),
    }

@router.get("/paper/positions")
def paper_positions():
    return _wa.paper.positions()

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
