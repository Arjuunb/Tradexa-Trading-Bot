"""The paper engine, as a ``Venue``.

Proves the port against a real implementation rather than only against fakes. A
protocol that has only ever been satisfied by test doubles is a protocol shaped
like its tests: this adapter is where the five methods meet an executor that
holds positions, charges fees and refuses fills.

It is an **adapter, not a rewrite**. Every call goes to the existing
``PaperExecutionEngine``, which remains the single executor for paper trading —
the same object the signal pipeline uses. Two execution paths for one account is
how a position appears in one view and not the other.

**This does not put the execution engine on the live path.** The paper pipeline
still calls the paper engine directly. Routing production through
``ExecutionEngine`` is a separate, deliberate step with its own verification;
what this file buys today is that the port is real, the health and latency
numbers describe an actual executor, and reconciliation has something true to
compare against.
"""
from __future__ import annotations

from typing import Optional, Sequence

from bot.types import Order, Position, Side
from tradexa.core.models import ExecutionReport, ExecutionStatus


class PaperVenue:
    """Wraps ``PaperExecutionEngine`` behind the execution engine's port."""

    def __init__(self, paper, *, name: str = "paper") -> None:
        self.name = name
        self._paper = paper
        #: client id -> the paper engine's own trade id, so cancel and amend can
        #: find the position a submit created. The paper engine keys on symbol;
        #: the execution engine keys on order id, and something has to bridge
        #: the two rather than each guessing at the other's identifiers.
        self._orders: dict[str, dict] = {}

    # ------------------------------------------------------------------ port
    def submit(self, order: Order, *, client_id: str) -> ExecutionReport:
        """Route an order to the paper executor.

        The paper engine fills or rejects immediately — it has no resting book —
        so a report from here is always terminal. That is a property of paper
        trading, not of the port: a real venue's ACCEPTED is answered later by
        the stream.
        """
        side = "BUY" if _is_long(order.side) else "SELL"
        fill = self._paper.open(
            symbol=order.symbol, side=side, size=float(order.qty),
            entry=float(order.limit_price or 0.0),
            stop=float(order.stop_loss) if order.stop_loss is not None else 0.0,
            alert_id=client_id)
        if getattr(fill, "action", "") == "rejected":
            return ExecutionReport(
                status=ExecutionStatus.REJECTED, order=order,
                message="rejected by the paper fill model",
                context={"client_id": client_id})
        self._orders[client_id] = {"trade_id": getattr(fill, "trade_id", None),
                                   "symbol": order.symbol}
        return ExecutionReport(
            status=ExecutionStatus.FILLED, order=order,
            broker_order_id=str(getattr(fill, "trade_id", "") or client_id),
            filled_qty=float(getattr(fill, "size", order.qty)),
            avg_fill_price=float(getattr(fill, "price", order.limit_price or 0.0)),
            context={"client_id": client_id})

    def cancel(self, broker_order_id: str) -> ExecutionReport:
        """Paper orders fill or reject on submission; there is nothing resting.

        Reported honestly as a rejection with the reason rather than a cheerful
        CANCELLED — a caller that believes it cancelled something would go on to
        replace a position that is still open.
        """
        return ExecutionReport(
            status=ExecutionStatus.REJECTED,
            order=Order(symbol="", side=Side.BUY, qty=0.0),
            broker_order_id=broker_order_id,
            message="the paper engine fills or rejects on submission — there is "
                    "no resting order to cancel. Close the position instead.")

    def amend(self, broker_order_id: str, *, qty: Optional[float] = None,
              limit_price: Optional[float] = None) -> ExecutionReport:
        """Stops can be moved on an open paper position; quantity cannot.

        Amending the size of an already-filled position is not an amendment, it
        is a new trade, and reporting it as an amendment would hide a change in
        exposure inside what reads as a price tweak.
        """
        record = next((v for v in self._orders.values()
                       if str(v.get("trade_id")) == str(broker_order_id)), None)
        if record is None or limit_price is None:
            return ExecutionReport(
                status=ExecutionStatus.REJECTED,
                order=Order(symbol="", side=Side.BUY, qty=0.0),
                broker_order_id=broker_order_id,
                message=("the paper engine can move a stop on an open position; "
                         "it cannot change the size of a filled one"))
        changed = self._paper.update_stop(record["symbol"], float(limit_price))
        return ExecutionReport(
            status=ExecutionStatus.ACCEPTED if changed else ExecutionStatus.REJECTED,
            order=Order(symbol=record["symbol"], side=Side.BUY, qty=0.0),
            broker_order_id=broker_order_id,
            message="" if changed else "no open position on that symbol")

    def fetch_order(self, broker_order_id: str) -> Optional[ExecutionReport]:
        for trade in self._paper.history():
            if str(trade.get("id")) == str(broker_order_id):
                return ExecutionReport(
                    status=ExecutionStatus.FILLED,
                    order=Order(symbol=trade.get("symbol", ""),
                                side=Side.BUY if trade.get("side") == "long" else Side.SELL,
                                qty=float(trade.get("size") or 0.0)),
                    broker_order_id=broker_order_id,
                    filled_qty=float(trade.get("size") or 0.0),
                    avg_fill_price=float(trade.get("entry") or 0.0))
        return None

    def fetch_positions(self) -> Sequence[Position]:
        """The paper engine's book, signed the way reconciliation needs it."""
        return [Position(symbol=p["symbol"],
                         qty=float(p["size"]) * (1.0 if p.get("side") == "long" else -1.0),
                         avg_price=float(p.get("entry") or 0.0))
                for p in self._paper.positions()]


def _is_long(side) -> bool:
    return str(getattr(side, "value", side)).lower() in ("buy", "long")


__all__ = ["PaperVenue"]
