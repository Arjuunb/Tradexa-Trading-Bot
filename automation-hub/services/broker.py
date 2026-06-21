"""Broker Layer (#14) — one interface for many venues.

A single ``Broker`` interface with a paper implementation and credential-gated
adapters for Binance / Bybit / IBKR / Alpaca, so the rest of the app talks to
one abstraction and live venues can be added later without touching strategy or
risk code.

Safety invariant: live trading stays LOCKED. Real-venue adapters report their
connection status honestly (connected only when keys are present) but refuse to
place live orders here — the only executable broker is Paper.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone


class BrokerError(Exception):
    pass


class Broker:
    name = ""
    kind = ""
    supports_live = False

    def connected(self) -> bool:
        raise NotImplementedError

    def status(self) -> dict:
        return {"name": self.name, "kind": self.kind, "connected": self.connected(),
                "mode": "paper" if self.kind == "paper" else "live (locked)",
                "live_enabled": False,
                "note": "Executable (paper)." if self.kind == "paper"
                        else ("Connected — live execution stays locked by design."
                              if self.connected() else "Not connected — add API credentials.")}

    def place_order(self, symbol: str, side: str, qty: float, **kw) -> dict:
        raise NotImplementedError


class PaperBroker(Broker):
    """The only executable broker — routes to the simulated paper engine."""
    name = "Paper"
    kind = "paper"

    def __init__(self, place_fn=None):
        self._place = place_fn

    def connected(self) -> bool:
        return True

    def place_order(self, symbol: str, side: str, qty: float, **kw) -> dict:
        if side not in ("buy", "sell", "long", "short"):
            raise BrokerError(f"invalid side {side}")
        if qty <= 0:
            raise BrokerError("qty must be > 0")
        if self._place:
            return self._place(symbol, side, qty, **kw)
        return {"id": uuid.uuid4().hex, "broker": "paper", "status": "filled",
                "symbol": symbol, "side": side, "qty": qty, "mode": "paper",
                "ts": datetime.now(timezone.utc).isoformat()}


class KeyedBroker(Broker):
    """A real venue that needs credentials. Connection reflects key presence;
    live execution is refused here (the safety gate lives above this layer)."""
    supports_live = True

    def __init__(self, name: str, kind: str, env_key: str):
        self.name = name
        self.kind = kind
        self.env_key = env_key

    def connected(self) -> bool:
        return bool(os.environ.get(self.env_key))

    def place_order(self, symbol: str, side: str, qty: float, **kw) -> dict:
        if not self.connected():
            raise BrokerError(f"{self.name} not connected — add {self.env_key}.")
        raise BrokerError(f"Live execution on {self.name} is locked by design (paper only).")


# venue catalogue (name, kind, credential env var)
_VENUES = [
    ("Binance", "binance", "BINANCE_API_KEY"),
    ("Bybit", "bybit", "BYBIT_API_KEY"),
    ("Interactive Brokers", "ibkr", "IBKR_API_KEY"),
    ("Alpaca", "alpaca", "ALPACA_API_KEY"),
]


class BrokerRegistry:
    def __init__(self, paper_place_fn=None):
        self.paper = PaperBroker(paper_place_fn)
        self.brokers = {"paper": self.paper}
        for name, kind, env in _VENUES:
            self.brokers[kind] = KeyedBroker(name, kind, env)

    def get(self, kind: str) -> Broker | None:
        return self.brokers.get(kind)

    def active(self) -> Broker:
        return self.paper

    def live_locked(self) -> bool:
        return True   # always — no broker is unlocked for live in this build

    def list(self) -> dict:
        return {
            "active": "paper",
            "live_locked": self.live_locked(),
            "brokers": [b.status() for b in self.brokers.values()],
            "note": "One interface, many venues. Live execution is locked until a "
                    "broker is connected AND the full safety flow + human approval pass.",
        }
