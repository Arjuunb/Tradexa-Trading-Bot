"""Binance exchange adapter.

Phase 1 supplies metadata + a broker factory; the live connection reuses the
tested ``bot.brokers.ccxt_broker.CCXTBroker`` (ccxt, exchange_id="binance").
Requires ``pip install -e ".[crypto]"`` and API keys to go live (Phase 2/5).
"""
from __future__ import annotations

from typing import Optional

KEY = "binance"
LABEL = "Binance"
ASSET_CLASS = "crypto"


def make_broker(api_key: Optional[str] = None, api_secret: Optional[str] = None,
                sandbox: bool = True):
    from bot.brokers.ccxt_broker import CCXTBroker  # lazy: optional dep
    return CCXTBroker(exchange_id="binance", api_key=api_key,
                      api_secret=api_secret, sandbox=sandbox)
