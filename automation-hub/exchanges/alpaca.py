"""Alpaca exchange adapter — US stocks (reuses bot.brokers.alpaca_broker).

Phase 2 stub: metadata + broker factory. Requires ``pip install -e ".[stocks]"``.
"""
from __future__ import annotations

KEY = "alpaca"
LABEL = "Alpaca"
ASSET_CLASS = "stocks"


def make_broker(api_key: str, api_secret: str, paper: bool = True):
    from bot.brokers.alpaca_broker import AlpacaBroker  # lazy: optional dep
    return AlpacaBroker(api_key=api_key, api_secret=api_secret, paper=paper)
