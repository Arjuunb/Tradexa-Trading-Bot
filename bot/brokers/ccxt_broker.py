"""Crypto broker via the ccxt library.

Install:  pip install ccxt

Notes
-----
* ``submit_order`` attaches SL/TP as LINKED siblings: if either fills, the other
  is cancelled. If the entry fails, both legs are cancelled. This avoids
  leaving naked stops/targets on the book.
* ``get_account`` marks each non-quote holding to its **last price** before
  summing into equity.  USDT is treated as the quote/cash currency.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from bot.brokers.base import Broker
from bot.types import AccountSnapshot, Bar, Fill, Order, OrderType, Position, Side

log = logging.getLogger("bot.ccxt")


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
        quote_currency: str = "USDT",
    ):
        import ccxt   # lazy import — stays optional
        klass = getattr(ccxt, exchange_id)
        self._x = klass({
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "enableRateLimit": True,
        })
        if sandbox and hasattr(self._x, "set_sandbox_mode"):
            self._x.set_sandbox_mode(True)
        self._exchange_id = exchange_id
        self._quote = quote_currency
        # entry_id -> {"sl_id": ..., "tp_id": ..., "symbol": ...}
        self._brackets: dict[str, dict] = {}
        self._rules: dict[str, object] = {}       # symbol -> SymbolRules cache
        self._submitted_client_ids: set[str] = set()  # idempotency guard

    # ------------------------------------------------------------ symbol rules
    def rules_for(self, symbol: str):
        """Exchange filters for a symbol (lot/tick/min-notional), cached.
        Falls back to unconstrained rules if the market can't be loaded."""
        from bot.brokers.symbol_rules import SymbolRules, from_ccxt
        if symbol not in self._rules:
            try:
                self._x.load_markets()
                self._rules[symbol] = from_ccxt(self._x.market(symbol))
            except Exception as e:
                log.warning("Could not load market rules for %s: %s", symbol, e)
                return SymbolRules(symbol=symbol)
        return self._rules[symbol]

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
        import time
        last_ts = None
        step = _TIMEFRAME_MS.get(timeframe, 60_000) / 1000
        while True:
            bars = self._x.fetch_ohlcv(symbol, timeframe, limit=2)
            if bars and len(bars) >= 2:
                ts, o, h, l, c, v = bars[-2]
                if ts != last_ts:
                    last_ts = ts
                    yield Bar(datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                              o, h, l, c, v)
            time.sleep(max(1.0, step / 4))

    # ---------------------------------------------------------------- account
    def get_account(self) -> AccountSnapshot:
        bal = self._x.fetch_balance()
        total = bal.get("total", {})
        cash = float(total.get(self._quote, 0.0))
        equity = cash
        positions: list[Position] = []
        for asset, qty in total.items():
            qty = float(qty or 0.0)
            if asset == self._quote or not qty:
                continue
            symbol = f"{asset}/{self._quote}"
            # Mark to last traded price.
            try:
                ticker = self._x.fetch_ticker(symbol)
                last_px = float(ticker.get("last") or ticker.get("close") or 0.0)
            except Exception as e:
                log.warning("Could not fetch ticker for %s: %s", symbol, e)
                last_px = 0.0
            positions.append(Position(symbol=symbol, qty=qty, avg_price=last_px))
            equity += qty * last_px
        return AccountSnapshot(cash=cash, equity=equity, positions=positions)

    def get_position(self, symbol: str) -> Optional[Position]:
        for p in self.get_account().positions:
            if p.symbol == symbol:
                return p
        return None

    def _last_price(self, symbol: str) -> float:
        try:
            t = self._x.fetch_ticker(symbol)
            return float(t.get("last") or t.get("close") or 0.0)
        except Exception as e:
            log.warning("No reference price for %s: %s", symbol, e)
            return 0.0

    # ----------------------------------------------------------------- orders
    def submit_order(self, order: Order) -> str:
        """Submit entry; attach SL/TP as linked siblings.

        If the entry order id can be retrieved, store the SL/TP ids alongside.
        Callers can invoke ``on_fill(entry_id)`` to cancel the unfilled sibling
        when one of the brackets executes.
        """
        side = order.side.value
        type_ = order.order_type.value

        # Idempotency: a retried submit with the same client id must not
        # double-buy. Guard locally and pass the id to the exchange, which
        # enforces uniqueness server-side too.
        if order.client_id:
            if order.client_id in self._submitted_client_ids:
                log.warning("Duplicate client order id %s — skipping resubmit", order.client_id)
                return f"duplicate:{order.client_id}"
            self._submitted_client_ids.add(order.client_id)

        # Exchange symbol filters: floor qty to lot size, prices to tick size,
        # and refuse orders below the minimum notional BEFORE the API rejects
        # them (the #1 first-live-order failure).
        rules = self.rules_for(order.symbol)
        ref_price = order.limit_price or self._last_price(order.symbol)
        qty, why = rules.clamp(order.qty, ref_price or 0.0)
        if qty <= 0:
            raise ValueError(f"Order violates exchange filters: {why}")
        limit_price = rules.round_price(order.limit_price)
        sl_price = rules.round_price(order.stop_loss)
        tp_price = rules.round_price(order.take_profit)

        params = {"clientOrderId": order.client_id} if order.client_id else {}
        try:
            result = self._x.create_order(
                symbol=order.symbol, type=type_, side=side,
                amount=qty, price=limit_price, params=params,
            )
        except Exception:
            log.exception("Entry order failed on %s", order.symbol)
            self._submitted_client_ids.discard(order.client_id or "")
            raise

        entry_id = str(result.get("id") or "")
        sl_id = tp_id = None
        exit_side = "sell" if order.side == Side.BUY else "buy"

        try:
            if sl_price:
                sl_res = self._x.create_order(
                    order.symbol, "stop_market", exit_side,
                    qty, None, {"stopPrice": sl_price},
                )
                sl_id = str(sl_res.get("id") or "")
            if tp_price:
                tp_res = self._x.create_order(
                    order.symbol, "take_profit_market", exit_side,
                    qty, None, {"stopPrice": tp_price},
                )
                tp_id = str(tp_res.get("id") or "")
        except Exception:
            # If we couldn't attach one leg, cancel everything we placed so
            # no naked exposure or naked stop lingers on the book.
            log.exception("Bracket leg failed on %s; cancelling siblings", order.symbol)
            for oid in (entry_id, sl_id, tp_id):
                if oid:
                    try:
                        self._x.cancel_order(oid, order.symbol)
                    except Exception as e:
                        log.warning("Cancel cleanup failed for %s: %s", oid, e)
            raise

        if entry_id and (sl_id or tp_id):
            self._brackets[entry_id] = {
                "sl_id": sl_id, "tp_id": tp_id, "symbol": order.symbol,
            }
        return entry_id

    def on_fill(self, filled_order_id: str) -> None:
        """Caller hook: when one bracket leg fills, cancel its sibling.

        Searches all tracked brackets for any leg matching the filled id and
        cancels the surviving sibling.
        """
        for entry_id, br in list(self._brackets.items()):
            symbol = br["symbol"]
            if filled_order_id == br.get("sl_id") and br.get("tp_id"):
                self._safe_cancel(br["tp_id"], symbol)
                self._brackets.pop(entry_id, None)
                return
            if filled_order_id == br.get("tp_id") and br.get("sl_id"):
                self._safe_cancel(br["sl_id"], symbol)
                self._brackets.pop(entry_id, None)
                return

    def _safe_cancel(self, order_id: str, symbol: str) -> None:
        try:
            self._x.cancel_order(order_id, symbol)
        except Exception as e:
            log.warning("Failed to cancel sibling %s on %s: %s", order_id, symbol, e)

    def cancel_order(self, order_id: str) -> None:
        # Symbol may be required by some venues; best-effort search.
        symbol = None
        for br in self._brackets.values():
            if order_id in (br.get("sl_id"), br.get("tp_id")):
                symbol = br["symbol"]
                break
        try:
            if symbol:
                self._x.cancel_order(order_id, symbol)
            else:
                self._x.cancel_order(order_id)
        except Exception:
            log.exception("cancel_order failed for %s", order_id)
            raise

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
