"""In-memory paper / backtest broker.

Fills market orders at next bar's open (configurable slippage + fee).
Tracks one position per symbol, supports SL/TP via attached child orders that
are checked on every bar.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Iterable, Optional

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


class PaperBroker(Broker):
    def __init__(
        self,
        starting_cash: float = 10_000.0,
        fee_bps: float = 5.0,          # 5 bps = 0.05% per side
        slippage_bps: float = 2.0,
    ):
        self._cash = starting_cash
        self._equity = starting_cash
        self._fee_bps = fee_bps / 10_000
        self._slip_bps = slippage_bps / 10_000
        self._positions: dict[str, Position] = {}
        self._pending: list[Order] = []
        self._fills: list[Fill] = []
        self._brackets: dict[str, tuple[float, float]] = {}   # symbol -> (sl, tp)
        self._last_price: dict[str, float] = {}

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
        order.client_id = order.client_id or str(uuid.uuid4())
        self._pending.append(order)
        return order.client_id

    def cancel_order(self, order_id: str) -> None:
        self._pending = [o for o in self._pending if o.client_id != order_id]

    def get_fills(self, since: Optional[datetime] = None) -> list[Fill]:
        if since is None:
            return list(self._fills)
        return [f for f in self._fills if f.timestamp >= since]

    @property
    def name(self) -> str:
        return "paper"

    # ----------------------------------------------------- backtester hooks
    def on_bar(self, symbol: str, bar: Bar) -> list[Fill]:
        """Called by the backtester for each new bar.

        1. Fills any pending market orders at bar.open with slippage.
        2. Checks active SL/TP brackets against bar high/low.
        3. Updates mark-to-market equity.
        """
        new_fills: list[Fill] = []

        # 1. fill pending market orders at open
        still_pending = []
        for order in self._pending:
            if order.symbol != symbol:
                still_pending.append(order)
                continue
            if order.order_type == OrderType.MARKET:
                px = self._apply_slippage(bar.open, order.side)
                fill = self._execute(order, px, bar.timestamp)
                new_fills.append(fill)
                if order.stop_loss or order.take_profit:
                    self._brackets[symbol] = (
                        order.stop_loss or 0.0,
                        order.take_profit or 0.0,
                    )
            elif order.order_type == OrderType.LIMIT:
                lp = order.limit_price
                if lp is None:
                    continue
                hit = (
                    (order.side == Side.BUY and bar.low <= lp)
                    or (order.side == Side.SELL and bar.high >= lp)
                )
                if hit:
                    fill = self._execute(order, lp, bar.timestamp)
                    new_fills.append(fill)
                else:
                    still_pending.append(order)
        self._pending = still_pending

        # 2. SL / TP
        pos = self._positions.get(symbol)
        if pos and symbol in self._brackets:
            sl, tp = self._brackets[symbol]
            exit_side = Side.SELL if pos.qty > 0 else Side.BUY
            exit_price = None
            if pos.qty > 0:        # long
                if sl and bar.low <= sl:
                    exit_price = sl
                elif tp and bar.high >= tp:
                    exit_price = tp
            else:                  # short
                if sl and bar.high >= sl:
                    exit_price = sl
                elif tp and bar.low <= tp:
                    exit_price = tp
            if exit_price is not None:
                exit_order = Order(
                    symbol=symbol,
                    side=exit_side,
                    qty=abs(pos.qty),
                    order_type=OrderType.MARKET,
                )
                fill = self._execute(exit_order, exit_price, bar.timestamp)
                new_fills.append(fill)
                self._brackets.pop(symbol, None)

        # 3. mark-to-market
        self._last_price[symbol] = bar.close
        self._recompute_equity()
        return new_fills

    # --------------------------------------------------------------- internal
    def _apply_slippage(self, px: float, side: Side) -> float:
        return px * (1 + self._slip_bps) if side == Side.BUY else px * (1 - self._slip_bps)

    def _execute(self, order: Order, price: float, ts: datetime) -> Fill:
        notional = price * order.qty
        fee = notional * self._fee_bps
        signed_qty = order.qty if order.side == Side.BUY else -order.qty

        pos = self._positions.get(order.symbol)
        if pos is None:
            self._positions[order.symbol] = Position(
                symbol=order.symbol, qty=signed_qty, avg_price=price
            )
            self._cash -= signed_qty * price + fee
        else:
            new_qty = pos.qty + signed_qty
            if pos.qty * new_qty < 0 or new_qty == 0:
                # closing / flipping: realize PnL on closed portion
                closed_qty = min(abs(pos.qty), abs(signed_qty)) * (1 if pos.qty > 0 else -1)
                realized = (price - pos.avg_price) * closed_qty
                self._cash += realized
                self._cash -= signed_qty * price + fee - realized  # net cash effect
                if new_qty == 0:
                    del self._positions[order.symbol]
                else:
                    self._positions[order.symbol] = Position(
                        symbol=order.symbol, qty=new_qty, avg_price=price
                    )
            else:
                # adding to existing position
                total_cost = pos.avg_price * pos.qty + price * signed_qty
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, qty=new_qty, avg_price=total_cost / new_qty
                )
                self._cash -= signed_qty * price + fee

        fill = Fill(
            order_id=order.client_id or str(uuid.uuid4()),
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=price,
            timestamp=ts,
            fee=fee,
        )
        self._fills.append(fill)
        return fill

    def _recompute_equity(self) -> None:
        eq = self._cash
        for sym, pos in self._positions.items():
            last = self._last_price.get(sym, pos.avg_price)
            eq += pos.qty * last
            pos.unrealized_pnl = (last - pos.avg_price) * pos.qty
        self._equity = eq
