"""Bybit exchange adapter — Phase 2 stub (ccxt exchange_id="bybit")."""
from __future__ import annotations

from typing import Optional

KEY = "bybit"
LABEL = "Bybit"
ASSET_CLASS = "crypto"


def make_broker(api_key: Optional[str] = None, api_secret: Optional[str] = None,
                sandbox: bool = True):
    from bot.brokers.ccxt_broker import CCXTBroker  # lazy: optional dep
    return CCXTBroker(exchange_id="bybit", api_key=api_key,
                      api_secret=api_secret, sandbox=sandbox)
