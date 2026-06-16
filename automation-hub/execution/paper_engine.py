"""Paper Execution Engine (Phase 1) — no real broker.

Signal-driven (not bar-driven): opens a position at the alert's entry, closes on
an opposite/close signal, computes P&L, and persists everything to the Ledger
(positions + paper_trades). Realized P&L drives the paper account balance;
unrealized P&L is computed against supplied mark prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from data.ledger import Ledger


@dataclass
class FillResult:
    action: str                 # "opened" | "closed" | "noop"
    symbol: str
    side: str
    size: float
    price: float
    pnl: float = 0.0
    position_id: str = ""
    trade_id: str = ""


def _dir(side: str) -> str:
    return "long" if side.upper() in ("BUY", "LONG") else "short"


class PaperExecutionEngine:
    def __init__(self, ledger: Ledger, starting_balance: float = 10_000.0):
        self.ledger = ledger
        self.starting_balance = starting_balance

    # --------------------------------------------------------------- queries
    def open_position(self, symbol: str) -> Optional[dict]:
        for p in self.ledger.get_positions("open"):
            if p["symbol"] == symbol:
                return p
        return None

    def positions(self) -> list[dict]:
        return self.ledger.get_positions("open")

    def history(self) -> list[dict]:
        return [t for t in self.ledger.get_paper_trades() if t["status"] == "closed"]

    def realized_pnl(self) -> float:
        return sum((t.get("pnl") or 0.0) for t in self.history())

    def balance(self) -> float:
        return self.starting_balance + self.realized_pnl()

    def unrealized_pnl(self, marks: dict[str, float]) -> float:
        total = 0.0
        for p in self.positions():
            mark = marks.get(p["symbol"])
            if mark is None:
                continue
            total += self._pnl(p["side"], p["size"], p["entry"], mark)
        return total

    def equity(self, marks: Optional[dict[str, float]] = None) -> float:
        return self.balance() + (self.unrealized_pnl(marks) if marks else 0.0)

    # --------------------------------------------------------------- actions
    def open(self, *, symbol: str, side: str, size: float, entry: float,
             stop: Optional[float], alert_id: str = "") -> FillResult:
        direction = _dir(side)
        pid = self.ledger.open_position(symbol=symbol, side=direction, size=size,
                                        entry=entry, stop=stop)
        tid = self.ledger.record_paper_trade({
            "alert_id": alert_id, "symbol": symbol, "side": direction,
            "size": size, "entry": entry, "stop": stop,
        })
        return FillResult("opened", symbol, direction, size, entry, 0.0, pid, tid)

    def close(self, *, symbol: str, exit_price: float) -> FillResult:
        pos = self.open_position(symbol)
        if pos is None:
            return FillResult("noop", symbol, "", 0.0, exit_price)
        pnl = self._pnl(pos["side"], pos["size"], pos["entry"], exit_price)
        rr = self._rr(pos, exit_price)
        self.ledger.close_position(pos["id"], exit_price=exit_price, pnl=pnl)
        for t in self.ledger.get_paper_trades():
            if t["symbol"] == symbol and t["status"] == "open":
                self.ledger.close_paper_trade(t["id"], exit_price=exit_price, pnl=pnl, rr=rr)
                break
        return FillResult("closed", symbol, pos["side"], pos["size"], exit_price, pnl, pos["id"])

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _pnl(direction: str, size: float, entry: float, exit_price: float) -> float:
        return (exit_price - entry) * size if direction == "long" else (entry - exit_price) * size

    @staticmethod
    def _rr(pos: dict, exit_price: float) -> float:
        stop = pos.get("stop")
        if not stop:
            return 0.0
        risk = abs(pos["entry"] - stop)
        if risk <= 0:
            return 0.0
        move = (exit_price - pos["entry"]) if pos["side"] == "long" else (pos["entry"] - exit_price)
        return round(move / risk, 3)
