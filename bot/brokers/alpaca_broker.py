"""US equities & options via Alpaca.

Install:  pip install alpaca-py
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from bot.brokers.base import Broker
from bot.types import AccountSnapshot, Bar, Fill, Order, OrderType, Position, Side


class AlpacaBroker(Broker):
    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical import StockHistoricalDataClient
        self._trading = TradingClient(api_key, api_secret, paper=paper)
        self._data = StockHistoricalDataClient(api_key, api_secret)
        self._paper = paper

    @property
    def name(self) -> str:
        return f"alpaca:{'paper' if self._paper else 'live'}"

    # ------------------------------------------------------------------ data
    def get_historical_bars(self, symbol, timeframe, start, end=None, limit=None):
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        tf_map = {
            "1m": TimeFrame.Minute,
            "5m": TimeFrame(5, TimeFrameUnit.Minute),
            "15m": TimeFrame(15, TimeFrameUnit.Minute),
            "1h": TimeFrame.Hour,
            "1d": TimeFrame.Day,
        }
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf_map.get(timeframe, TimeFrame.Hour),
            start=start,
            end=end,
            limit=limit,
        )
        resp = self._data.get_stock_bars(req)
        bars = []
        for b in resp[symbol]:
            bars.append(Bar(b.timestamp, b.open, b.high, b.low, b.close, b.volume))
        return bars

    def stream_bars(self, symbol: str, timeframe: str) -> Iterable[Bar]:
        import time
        last_ts = None
        while True:
            recent = self.get_historical_bars(
                symbol, timeframe, datetime.now(timezone.utc), limit=2
            )
            if recent and recent[-1].timestamp != last_ts:
                last_ts = recent[-1].timestamp
                yield recent[-1]
            time.sleep(30)

    # ---------------------------------------------------------------- account
    def get_account(self) -> AccountSnapshot:
        a = self._trading.get_account()
        positions = []
        for p in self._trading.get_all_positions():
            positions.append(Position(symbol=p.symbol, qty=float(p.qty), avg_price=float(p.avg_entry_price)))
        return AccountSnapshot(cash=float(a.cash), equity=float(a.equity), positions=positions)

    def get_position(self, symbol: str) -> Optional[Position]:
        try:
            p = self._trading.get_open_position(symbol)
            return Position(symbol=p.symbol, qty=float(p.qty), avg_price=float(p.avg_entry_price))
        except Exception:
            return None

    # ----------------------------------------------------------------- orders
    def submit_order(self, order: Order) -> str:
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

        side = OrderSide.BUY if order.side == Side.BUY else OrderSide.SELL
        bracket = None
        if order.stop_loss or order.take_profit:
            kwargs = {}
            if order.take_profit:
                kwargs["take_profit"] = TakeProfitRequest(limit_price=order.take_profit)
            if order.stop_loss:
                kwargs["stop_loss"] = StopLossRequest(stop_price=order.stop_loss)
            bracket = OrderClass.BRACKET
            extra = kwargs
        else:
            extra = {}

        if order.order_type == OrderType.MARKET:
            req = MarketOrderRequest(
                symbol=order.symbol, qty=order.qty, side=side,
                time_in_force=TimeInForce.DAY,
                order_class=bracket,
                **extra,
            )
        else:
            req = LimitOrderRequest(
                symbol=order.symbol, qty=order.qty, side=side,
                limit_price=order.limit_price,
                time_in_force=TimeInForce.DAY,
                order_class=bracket,
                **extra,
            )
        resp = self._trading.submit_order(req)
        return str(resp.id)

    def cancel_order(self, order_id: str) -> None:
        self._trading.cancel_order_by_id(order_id)

    def get_fills(self, since: Optional[datetime] = None) -> list[Fill]:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=since)
        orders = self._trading.get_orders(filter=req)
        fills = []
        for o in orders:
            if o.filled_qty and float(o.filled_qty) > 0:
                fills.append(Fill(
                    order_id=str(o.id),
                    symbol=o.symbol,
                    side=Side(o.side.value),
                    qty=float(o.filled_qty),
                    price=float(o.filled_avg_price or 0),
                    timestamp=o.filled_at or datetime.now(timezone.utc),
                ))
        return fills
