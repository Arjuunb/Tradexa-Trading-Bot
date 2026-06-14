"""Crypto broker via the ccxt library (Binance, Coinbase, Kraken, Bybit, ...).

Install:  pip install ccxt
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from bot.brokers.base import Broker
from bot.types import AccountSnapshot, Bar, Fill, Order, OrderType, Position, Side


_TIMEFRAME_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


class CCXTBroker(Broker):
    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        sandbox: bool = True,
    ):
        import ccxt  # lazy import
        klass = getattr(ccxt, exchange_id)
        self._x = klass({
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "enableRateLimit": True,
        })
        if sandbox and hasattr(self._x, "set_sandbox_mode"):
            self._x.set_sandbox_mode(True)
        self._exchange_id = exchange_id

    @property
    def name(self) -> str:
        return f"ccxt:{self._exchange_id}"

    # ------------------------------------------------------------------ data
    def get_historical_bars(self, symbol, timeframe, start, end=None, limit=None):
        since = int(start.timestamp() * 1000)
        out: list[Bar] = []
        step = _TIMEFRAME_MS.get(timeframe, 3_600_000)
        while True:
            chunk = self._x.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not chunk:
                break
            for ts, o, h, l, c, v in chunk:
                bar_ts = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                if end and bar_ts > end:
                    return out
                out.append(Bar(bar_ts, o, h, l, c, v))
            since = chunk[-1][0] + step
            if limit and len(out) >= limit:
                return out[:limit]
            if len(chunk) < 1000:
                break
        return out

    def stream_bars(self, symbol: str, timeframe: str) -> Iterable[Bar]:
        """Simple polling stream — yields each newly-closed bar."""
        import time
        last_ts = None
        step = _TIMEFRAME_MS.get(timeframe, 60_000) / 1000
        while True:
            bars = self._x.fetch_ohlcv(symbol, timeframe, limit=2)
            if bars and len(bars) >= 2:
                ts, o, h, l, c, v = bars[-2]   # last *closed* bar
                if ts != last_ts:
                    last_ts = ts
                    yield Bar(
                        datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                        o, h, l, c, v,
                    )
            time.sleep(max(1.0, step / 4))

    # ---------------------------------------------------------------- account
    def get_account(self) -> AccountSnapshot:
        bal = self._x.fetch_balance()
        total = bal.get("total", {})
        # Use quote currency (USDT) as cash proxy
        cash = float(total.get("USDT", 0.0))
        positions: list[Position] = []
        for asset, qty in total.items():
            if asset == "USDT" or not qty:
                continue
            positions.append(Position(symbol=f"{asset}/USDT", qty=float(qty), avg_price=0.0))
        equity = cash + sum(p.qty for p in positions)   # rough
        return AccountSnapshot(cash=cash, equity=equity, positions=positions)

    def get_position(self, symbol: str) -> Optional[Position]:
        acct = self.get_account()
        for p in acct.positions:
            if p.symbol == symbol:
                return p
        return None

    # ----------------------------------------------------------------- orders
    def submit_order(self, order: Order) -> str:
        side = order.side.value
        type_ = order.order_type.value
        params = {}
        result = self._x.create_order(
            symbol=order.symbol,
            type=type_,
            side=side,
            amount=order.qty,
            price=order.limit_price,
            params=params,
        )
        oid = result.get("id", "")
        # Submit SL/TP as separate stop / take orders if requested.
        if order.stop_loss:
            try:
                self._x.create_order(
                    order.symbol, "stop_market",
                    "sell" if order.side == Side.BUY else "buy",
                    order.qty, None, {"stopPrice": order.stop_loss},
                )
            except Exception:
                pass
        if order.take_profit:
            try:
                self._x.create_order(
                    order.symbol, "take_profit_market",
                    "sell" if order.side == Side.BUY else "buy",
                    order.qty, None, {"stopPrice": order.take_profit},
                )
            except Exception:
                pass
        return oid

    def cancel_order(self, order_id: str) -> None:
        self._x.cancel_order(order_id)

    def get_fills(self, since: Optional[datetime] = None) -> list[Fill]:
        since_ms = int(since.timestamp() * 1000) if since else None
        trades = self._x.fetch_my_trades(since=since_ms)
        return [
            Fill(
                order_id=t.get("order", ""),
                symbol=t["symbol"],
                side=Side(t["side"]),
                qty=float(t["amount"]),
                price=float(t["price"]),
                timestamp=datetime.fromtimestamp(t["timestamp"] / 1000, tz=timezone.utc),
                fee=float((t.get("fee") or {}).get("cost", 0.0)),
            )
            for t in trades
        ]
