"""In-memory paper / backtest broker.

Fills market orders at next bar's open (with slippage + fee).
Tracks one position per symbol, supports SL/TP via attached brackets that are
checked on every bar's high/low.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from bot.brokers.base import Broker
from bot.types import (
    AccountSnapshot,
    Bar,
    Fill,
    Order,
    OrderType,
    Position,
    Side,
)

log = logging.getLogger("bot.paper")


@dataclass
class _Bracket:
    """Tracks SL/TP and the role of an outstanding fill for trade bookkeeping."""
    stop_loss: float = 0.0
    take_profit: float = 0.0


class PaperBroker(Broker):
    def __init__(
        self,
        starting_cash: float = 10_000.0,
        fee_bps: float = 5.0,          # 5 bps = 0.05% per side
        slippage_bps: float = 2.0,
    ):
        if starting_cash <= 0:
            raise ValueError("starting_cash must be > 0")
        self._cash = starting_cash
        self._equity = starting_cash
        self._fee_bps = fee_bps / 10_000
        self._slip_bps = slippage_bps / 10_000
        self._positions: dict[str, Position] = {}
        self._pending: list[Order] = []
        self._fills: list[Fill] = []
        self._brackets: dict[str, _Bracket] = {}
        self._last_price: dict[str, float] = {}
        # role tagging so the backtester knows entry vs exit
        self._fill_roles: dict[str, str] = {}    # fill order_id -> "entry"|"exit"

    # ------------------------------------------------------------------ data
    def get_historical_bars(self, symbol, timeframe, start, end=None, limit=None):
        raise NotImplementedError("PaperBroker is fed bars by the backtester.")

    def stream_bars(self, symbol, timeframe):
        raise NotImplementedError("PaperBroker is fed bars by the backtester.")

    # ---------------------------------------------------------------- account
    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            cash=self._cash,
            equity=self._equity,
            positions=list(self._positions.values()),
        )

    def get_position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    # ----------------------------------------------------------------- orders
    def submit_order(self, order: Order) -> str:
        if order.qty <= 0:
            raise ValueError(f"Order qty must be > 0, got {order.qty}")
        order.client_id = order.client_id or str(uuid.uuid4())
        self._pending.append(order)
        return order.client_id

    def cancel_order(self, order_id: str) -> None:
        self._pending = [o for o in self._pending if o.client_id != order_id]

    def get_fills(self, since: Optional[datetime] = None) -> list[Fill]:
        if since is None:
            return list(self._fills)
        return [f for f in self._fills if f.timestamp >= since]

    def fill_role(self, fill: Fill) -> str:
        """Return 'entry' or 'exit' for a previously emitted fill."""
        return self._fill_roles.get(fill.order_id, "entry")

    @property
    def name(self) -> str:
        return "paper"

    # ----------------------------------------------------- backtester hooks
    def on_bar(self, symbol: str, bar: Bar) -> list[Fill]:
        """Called by the backtester for each new bar.

        1. Fills pending market orders at bar.open (with slippage).
        2. Fills pending limit orders if their price was touched.
        3. Triggers SL/TP brackets against bar high/low (also with slippage).
        4. Updates mark-to-market equity.
        """
        new_fills: list[Fill] = []

        still_pending = []
        for order in self._pending:
            if order.symbol != symbol:
                still_pending.append(order)
                continue

            if order.order_type == OrderType.MARKET:
                px = self._apply_slippage(bar.open, order.side)
                # Was there an existing position? -> this is an exit
                role = "exit" if symbol in self._positions and \
                    ((self._positions[symbol].qty > 0 and order.side == Side.SELL)
                     or (self._positions[symbol].qty < 0 and order.side == Side.BUY)) \
                    else "entry"
                fill = self._execute(order, px, bar.timestamp, role)
                new_fills.append(fill)
                if role == "entry" and (order.stop_loss or order.take_profit):
                    self._brackets[symbol] = _Bracket(
                        stop_loss=order.stop_loss or 0.0,
                        take_profit=order.take_profit or 0.0,
                    )

            elif order.order_type == OrderType.LIMIT:
                lp = order.limit_price
                if lp is None:
                    log.warning("Limit order with no limit_price; dropping")
                    continue
                hit = (
                    (order.side == Side.BUY and bar.low <= lp)
                    or (order.side == Side.SELL and bar.high >= lp)
                )
                if hit:
                    role = "exit" if symbol in self._positions and \
                        ((self._positions[symbol].qty > 0 and order.side == Side.SELL)
                         or (self._positions[symbol].qty < 0 and order.side == Side.BUY)) \
                        else "entry"
                    fill = self._execute(order, lp, bar.timestamp, role)
                    new_fills.append(fill)
                    if role == "entry" and (order.stop_loss or order.take_profit):
                        self._brackets[symbol] = _Bracket(
                            stop_loss=order.stop_loss or 0.0,
                            take_profit=order.take_profit or 0.0,
                        )
                else:
                    still_pending.append(order)
            else:
                still_pending.append(order)
        self._pending = still_pending

        # SL / TP triggers
        pos = self._positions.get(symbol)
        if pos and symbol in self._brackets:
            br = self._brackets[symbol]
            sl, tp = br.stop_loss, br.take_profit
            exit_side = Side.SELL if pos.qty > 0 else Side.BUY
            trigger_price = None
            if pos.qty > 0:
                if sl and bar.low <= sl:
                    trigger_price = sl
                elif tp and bar.high >= tp:
                    trigger_price = tp
            else:
                if sl and bar.high >= sl:
                    trigger_price = sl
                elif tp and bar.low <= tp:
                    trigger_price = tp
            if trigger_price is not None:
                # Slippage on stops/takes too (real markets always slip on stops).
                fill_px = self._apply_slippage(trigger_price, exit_side)
                exit_order = Order(
                    symbol=symbol, side=exit_side,
                    qty=abs(pos.qty), order_type=OrderType.MARKET,
                )
                exit_order.client_id = str(uuid.uuid4())
                fill = self._execute(exit_order, fill_px, bar.timestamp, role="exit")
                new_fills.append(fill)
                self._brackets.pop(symbol, None)

        # mark-to-market
        self._last_price[symbol] = bar.close
        self._recompute_equity()
        return new_fills

    # --------------------------------------------------------------- internal
    def _apply_slippage(self, px: float, side: Side) -> float:
        return px * (1 + self._slip_bps) if side == Side.BUY else px * (1 - self._slip_bps)

    def _execute(self, order: Order, price: float, ts: datetime, role: str) -> Fill:
        """Execute a fill and update cash + position correctly.

        Cash accounting (consistent for long, short, partial, and flips):
            cash -= signed_qty * price        # buying lowers cash, selling raises it
            cash -= fee                       # always a debit
        Realized PnL is implicit in cash deltas — no double counting.
        """
        notional = price * order.qty
        fee = notional * self._fee_bps
        signed_qty = order.qty if order.side == Side.BUY else -order.qty

        pos = self._positions.get(order.symbol)
        if pos is None:
            self._positions[order.symbol] = Position(
                symbol=order.symbol, qty=signed_qty, avg_price=price
            )
        else:
            new_qty = pos.qty + signed_qty
            if new_qty == 0:
                # fully closed
                del self._positions[order.symbol]
            elif pos.qty * new_qty < 0:
                # flipped through zero — leftover side opens at fill price
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, qty=new_qty, avg_price=price
                )
            elif abs(new_qty) < abs(pos.qty):
                # partial close — average price of remaining position is unchanged
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, qty=new_qty, avg_price=pos.avg_price
                )
            else:
                # increasing existing position — VWAP the entries
                total_cost = pos.avg_price * pos.qty + price * signed_qty
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, qty=new_qty, avg_price=total_cost / new_qty
                )

        # Single, consistent cash update for every branch
        self._cash -= signed_qty * price
        self._cash -= fee

        fill = Fill(
            order_id=order.client_id or str(uuid.uuid4()),
            symbol=order.symbol, side=order.side,
            qty=order.qty, price=price, timestamp=ts, fee=fee,
        )
        self._fills.append(fill)
        self._fill_roles[fill.order_id] = role
        return fill

    def _recompute_equity(self) -> None:
        eq = self._cash
        for sym, pos in self._positions.items():
            last = self._last_price.get(sym, pos.avg_price)
            eq += pos.qty * last
            pos.unrealized_pnl = (last - pos.avg_price) * pos.qty
        self._equity = eq
