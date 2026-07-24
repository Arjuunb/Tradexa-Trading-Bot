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
    pnl: float = 0.0            # net of fees
    position_id: str = ""
    trade_id: str = ""
    fee: float = 0.0            # round-trip commission charged on this fill


def _dir(side: str) -> str:
    return "long" if side.upper() in ("BUY", "LONG") else "short"


class PaperExecutionEngine:
    def __init__(self, ledger: Ledger, starting_balance: float = 10_000.0, fill_model=None):
        self.ledger = ledger
        self.starting_balance = starting_balance
        if fill_model is None:
            from services.fill_model import PerfectFill
            fill_model = PerfectFill()
        self.fill_model = fill_model
        self.quality = None   # optional services.execution_quality.ExecutionQuality
        # optional data.account_store.AccountStore — persists the account snapshot
        # (current equity / available / realized) so capital survives a restart.
        self.account_store = None
        # H-5: history() is read ~10x per signal (PnL/streak/Kelly/curve).
        # Cache the closed-trade list and invalidate on any write, so one
        # process() call scans the ledger once, not ten times.
        self._hist_cache = None

    # --------------------------------------------------------------- queries
    def open_position(self, symbol: str) -> Optional[dict]:
        for p in self.ledger.get_positions("open"):
            if p["symbol"] == symbol:
                return p
        return None

    def positions(self) -> list[dict]:
        return self.ledger.get_positions("open")

    def history(self) -> list[dict]:
        if self._hist_cache is None:
            self._hist_cache = [t for t in self.ledger.get_paper_trades()
                                if t["status"] == "closed"]
        return self._hist_cache

    def _invalidate_history(self) -> None:
        self._hist_cache = None

    def update_stop(self, symbol: str, stop: float) -> int:
        """Persist a new stop on the OPEN position for a symbol (manual on-chart
        adjust) through this engine's own ledger. Returns rows updated."""
        return self.ledger.update_position_stop(symbol=symbol, stop=stop)

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

    def open_notional(self) -> float:
        return sum((p["size"] * p["entry"]) for p in self.positions())

    def available_balance(self) -> float:
        """Funds not committed to open positions."""
        return self.balance() - self.open_notional()

    def _persist_account_snapshot(self) -> None:
        """Save the account state to the persistent store so it survives a
        backend restart. Never raises into the trading path."""
        if self.account_store is None:
            return
        try:
            self.account_store.update_snapshot(
                current_equity=self.balance(),
                available_balance=self.available_balance(),
                realized_pnl=self.realized_pnl())
        except Exception:  # noqa: BLE001 — persistence must never block trading
            pass

    # --------------------------------------------------------------- actions
    def open(self, *, symbol: str, side: str, size: float, entry: float,
             stop: Optional[float], alert_id: str = "", maker: bool = False) -> FillResult:
        direction = _dir(side)
        # route the entry through the fill model (price/size/rejection);
        # maker fills (resting limits) execute at the limit price exactly
        action = "buy" if direction == "long" else "sell"
        f = self.fill_model.apply(action, entry, size, maker=maker)
        if f["rejected"] or f["size"] <= 0:
            return FillResult("rejected", symbol, direction, 0.0, entry)
        if self.quality is not None:
            self.quality.record(symbol=symbol, side=action, intended=entry,
                                filled=f["price"], kind="entry", maker=maker)
        entry, size = f["price"], f["size"]
        pid = self.ledger.open_position(symbol=symbol, side=direction, size=size,
                                        entry=entry, stop=stop)
        tid = self.ledger.record_paper_trade({
            "alert_id": alert_id, "symbol": symbol, "side": direction,
            "size": size, "entry": entry, "stop": stop,
        })
        self._invalidate_history()
        return FillResult("opened", symbol, direction, size, entry, 0.0, pid, tid)

    def reduce(self, *, symbol: str, exit_price: float, fraction: float) -> FillResult:
        """Partial close (scale-out): realize P&L on ``fraction`` of the position
        and keep the remainder open at the same entry/stop. Implemented as
        close-then-reopen so every Ledger backend works unchanged."""
        pos = self.open_position(symbol)
        if pos is None or not (0.0 < fraction < 1.0):
            return FillResult("noop", symbol, "", 0.0, exit_price)
        closed_size = pos["size"] * fraction
        f = self.fill_model.apply("sell" if pos["side"] == "long" else "buy",
                                  exit_price, closed_size,
                                  allow_reject=False, allow_partial=False)
        exit_price = f["price"]
        gross = self._pnl(pos["side"], closed_size, pos["entry"], exit_price)
        fee = self._round_trip_fee(closed_size, pos["entry"], exit_price)
        pnl = gross - fee          # realized P&L on the closed fraction, net of fees
        rr = self._rr(pos, exit_price)
        remainder = pos["size"] - closed_size
        self.ledger.close_position(pos["id"], exit_price=exit_price, pnl=pnl)
        self.ledger.open_position(symbol=symbol, side=pos["side"], size=remainder,
                                  entry=pos["entry"], stop=pos.get("stop"))
        for t in self.ledger.get_paper_trades():
            if t["symbol"] == symbol and t["status"] == "open":
                # M-9: the closed row records the CLOSED size (not the full
                # original), so per-trade R analytics (Growth Journey / Kelly)
                # see closed_size vs partial pnl — not full size vs partial pnl.
                self.ledger.close_paper_trade(t["id"], exit_price=exit_price,
                                              pnl=pnl, rr=rr, size=closed_size)
                break
        self.ledger.record_paper_trade({
            "alert_id": "", "symbol": symbol, "side": pos["side"],
            "size": remainder, "entry": pos["entry"], "stop": pos.get("stop"),
        })
        self._invalidate_history()
        self._persist_account_snapshot()
        return FillResult("reduced", symbol, pos["side"], closed_size, exit_price, pnl, pos["id"], fee=fee)

    def close(self, *, symbol: str, exit_price: float) -> FillResult:
        pos = self.open_position(symbol)
        if pos is None:
            return FillResult("noop", symbol, "", 0.0, exit_price)
        # exits cross the spread the other way; never reject/partial an exit
        action = "sell" if pos["side"] == "long" else "buy"
        f = self.fill_model.apply(action, exit_price, pos["size"],
                                  allow_reject=False, allow_partial=False)
        if self.quality is not None:
            self.quality.record(symbol=symbol, side=action, intended=exit_price,
                                filled=f["price"], kind="exit")
        exit_price = f["price"]
        gross = self._pnl(pos["side"], pos["size"], pos["entry"], exit_price)
        fee = self._round_trip_fee(pos["size"], pos["entry"], exit_price)
        pnl = gross - fee          # realized P&L is net of commission
        rr = self._rr(pos, exit_price)
        self.ledger.close_position(pos["id"], exit_price=exit_price, pnl=pnl)
        for t in self.ledger.get_paper_trades():
            if t["symbol"] == symbol and t["status"] == "open":
                self.ledger.close_paper_trade(t["id"], exit_price=exit_price, pnl=pnl, rr=rr)
                break
        self._invalidate_history()
        self._persist_account_snapshot()
        return FillResult("closed", symbol, pos["side"], pos["size"], exit_price, pnl, pos["id"], fee=fee)

    # --------------------------------------------------------------- helpers
    def _fee_rate(self, *, maker: bool = False) -> float:
        """Commission fraction from the fill model (0 for PerfectFill)."""
        fn = getattr(self.fill_model, "fee_pct", None)
        return fn(maker=maker) if fn else 0.0

    def _round_trip_fee(self, size: float, entry: float, exit_price: float) -> float:
        """Commission for a full round trip (entry + exit notional). Taker rate
        both sides — a conservative paper assumption that never understates cost.
        Zero when the fill model charges no fee, so ideal-fill behaviour is
        unchanged."""
        rate = self._fee_rate(maker=False)
        if rate <= 0:
            return 0.0
        return rate * size * (abs(entry) + abs(exit_price))

    def fees_paid(self) -> float:
        """Total commission booked across all closed trades (recomputed from the
        round-trip notional), for transparency in the account/analytics view."""
        rate = self._fee_rate(maker=False)
        if rate <= 0:
            return 0.0
        total = 0.0
        for t in self.history():
            entry, exit_price, size = t.get("entry"), t.get("exit"), t.get("size")
            if entry and exit_price and size:
                total += rate * size * (abs(entry) + abs(exit_price))
        return round(total, 8)

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
