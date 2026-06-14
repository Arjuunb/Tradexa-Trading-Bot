"""FX broker via OANDA v20 REST API.

Install:  pip install oandapyV20
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from bot.brokers.base import Broker
from bot.types import AccountSnapshot, Bar, Fill, Order, OrderType, Position, Side


_GRANULARITY = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D",
}


class OandaBroker(Broker):
    def __init__(self, account_id: str, access_token: str, practice: bool = True):
        import oandapyV20
        env = "practice" if practice else "live"
        self._client = oandapyV20.API(access_token=access_token, environment=env)
        self._account_id = account_id

    @property
    def name(self) -> str:
        return "oanda"

    def get_historical_bars(self, symbol, timeframe, start, end=None, limit=None):
        from oandapyV20.endpoints.instruments import InstrumentsCandles
        params = {
            "granularity": _GRANULARITY.get(timeframe, "H1"),
            "from": start.isoformat("T") + "Z",
            "price": "M",
        }
        if end:
            params["to"] = end.isoformat("T") + "Z"
        if limit:
            params["count"] = min(limit, 5000)
        r = InstrumentsCandles(instrument=symbol, params=params)
        self._client.request(r)
        out = []
        for c in r.response["candles"]:
            if not c.get("complete"):
                continue
            mid = c["mid"]
            ts = datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
            out.append(Bar(ts, float(mid["o"]), float(mid["h"]), float(mid["l"]), float(mid["c"]), float(c["volume"])))
        return out

    def stream_bars(self, symbol, timeframe):
        import time
        last = None
        while True:
            bars = self.get_historical_bars(symbol, timeframe, datetime.now(timezone.utc), limit=2)
            if bars and bars[-1].timestamp != last:
                last = bars[-1].timestamp
                yield bars[-1]
            time.sleep(15)

    def get_account(self):
        from oandapyV20.endpoints.accounts import AccountSummary, AccountDetails
        r = AccountDetails(self._account_id)
        self._client.request(r)
        d = r.response["account"]
        positions = []
        for p in d.get("positions", []):
            long_units = float(p["long"]["units"])
            short_units = float(p["short"]["units"])
            qty = long_units + short_units
            if qty == 0:
                continue
            avg = float(p["long"]["averagePrice"]) if long_units else float(p["short"]["averagePrice"])
            positions.append(Position(symbol=p["instrument"], qty=qty, avg_price=avg))
        return AccountSnapshot(cash=float(d["balance"]), equity=float(d["NAV"]), positions=positions)

    def get_position(self, symbol):
        for p in self.get_account().positions:
            if p.symbol == symbol:
                return p
        return None

    def submit_order(self, order: Order) -> str:
        from oandapyV20.endpoints.orders import OrderCreate
        units = int(order.qty) if order.side == Side.BUY else -int(order.qty)
        body = {"order": {
            "instrument": order.symbol,
            "units": str(units),
            "type": "MARKET" if order.order_type == OrderType.MARKET else "LIMIT",
            "timeInForce": "FOK" if order.order_type == OrderType.MARKET else "GTC",
            "positionFill": "DEFAULT",
        }}
        if order.order_type == OrderType.LIMIT and order.limit_price:
            body["order"]["price"] = f"{order.limit_price:.5f}"
        if order.stop_loss:
            body["order"]["stopLossOnFill"] = {"price": f"{order.stop_loss:.5f}"}
        if order.take_profit:
            body["order"]["takeProfitOnFill"] = {"price": f"{order.take_profit:.5f}"}
        r = OrderCreate(self._account_id, data=body)
        self._client.request(r)
        return str(r.response.get("orderFillTransaction", {}).get("id", ""))

    def cancel_order(self, order_id: str) -> None:
        from oandapyV20.endpoints.orders import OrderCancel
        self._client.request(OrderCancel(self._account_id, orderID=order_id))

    def get_fills(self, since=None):
        # Simplified: not implemented for brevity.
        return []
