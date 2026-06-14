"""Lightweight pub/sub event bus.

The backtester, multi-symbol backtester, and live runner all emit a uniform
stream of events. Anything that wants to observe the engine — CLI logger,
HTML reporter, web dashboard — just subscribes to the bus.

Design choices
--------------
- Pure stdlib. No asyncio, no threads in the publisher path. Subscribers may
  spawn their own threads if they need them (the dashboard does).
- Events are plain dicts with a `type` discriminator so they JSON-serialize
  cleanly for SSE/WebSocket transport.
- Backpressure: subscribers that block slow down the engine. The dashboard
  subscriber uses a bounded queue and drops oldest events on overflow — that
  policy lives in the subscriber, not here.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


Event = dict[str, Any]
Subscriber = Callable[[Event], None]


class EventBus:
    """In-process pub/sub. Thread-safe enough for the dashboard's read thread."""

    def __init__(self, history: int = 5000):
        self._subs: list[Subscriber] = []
        self._history: Deque[Event] = deque(maxlen=history)

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        self._subs.append(fn)

        def _unsub() -> None:
            try:
                self._subs.remove(fn)
            except ValueError:
                pass

        return _unsub

    def publish(self, event: Event) -> None:
        self._history.append(event)
        for s in list(self._subs):
            try:
                s(event)
            except Exception:  # noqa: BLE001 — a bad sub mustn't break the engine
                pass

    def replay(self) -> list[Event]:
        """Snapshot of buffered history for late subscribers (e.g. dashboard
        clients that connected mid-run)."""
        return list(self._history)


# ----------------------------- event constructors ----------------------------
# Tiny helpers so call sites don't repeat the string keys everywhere.

def ev_run_started(run_id: str, kind: str, symbols: list[str],
                   starting_cash: float) -> Event:
    return {
        "type": "run_started", "run_id": run_id, "kind": kind,
        "symbols": symbols, "starting_cash": starting_cash,
        "ts": _now_iso(),
    }


def ev_run_finished(run_id: str, ending_equity: float, metrics: dict) -> Event:
    return {
        "type": "run_finished", "run_id": run_id,
        "ending_equity": ending_equity, "metrics": metrics,
        "ts": _now_iso(),
    }


def ev_bar(symbol: str, bar_ts: datetime, close: float, equity: float) -> Event:
    return {
        "type": "bar", "symbol": symbol,
        "bar_ts": bar_ts.isoformat(), "close": close, "equity": equity,
    }


def ev_signal(symbol: str, side: str, entry: float, sl: float, tp: float,
              reason: str, bar_ts: datetime) -> Event:
    return {
        "type": "signal", "symbol": symbol, "side": side,
        "entry": entry, "sl": sl, "tp": tp, "reason": reason,
        "bar_ts": bar_ts.isoformat(),
    }


def ev_risk_block(symbol: str, reason: str, bar_ts: datetime) -> Event:
    return {
        "type": "risk_block", "symbol": symbol, "reason": reason,
        "bar_ts": bar_ts.isoformat(),
    }


def ev_order(order_id: str, symbol: str, side: str, qty: float) -> Event:
    return {
        "type": "order", "order_id": order_id, "symbol": symbol,
        "side": side, "qty": qty,
    }


def ev_fill(order_id: str, symbol: str, side: str, qty: float, price: float,
            fee: float, role: str, bar_ts: datetime) -> Event:
    return {
        "type": "fill", "order_id": order_id, "symbol": symbol, "side": side,
        "qty": qty, "price": price, "fee": fee, "role": role,
        "bar_ts": bar_ts.isoformat(),
    }


def ev_trade_closed(symbol: str, side: str, entry_price: float, exit_price: float,
                    qty: float, pnl: float, r: float, bar_ts: datetime) -> Event:
    return {
        "type": "trade_closed", "symbol": symbol, "side": side,
        "entry_price": entry_price, "exit_price": exit_price,
        "qty": qty, "pnl": pnl, "r": r, "bar_ts": bar_ts.isoformat(),
    }
