"""Broker adapters. Import lazily so optional deps (ccxt, alpaca, oanda) aren't
required unless the user actually uses that venue.
"""
from bot.brokers.base import Broker
from bot.brokers.paper import PaperBroker

__all__ = ["Broker", "PaperBroker", "get_broker"]


def get_broker(venue: str, **kwargs) -> Broker:
    """Factory: 'paper' | 'ccxt' | 'alpaca' | 'oanda'."""
    venue = venue.lower()
    if venue == "paper":
        return PaperBroker(**kwargs)
    if venue == "ccxt":
        from bot.brokers.ccxt_broker import CCXTBroker
        return CCXTBroker(**kwargs)
    if venue == "alpaca":
        from bot.brokers.alpaca_broker import AlpacaBroker
        return AlpacaBroker(**kwargs)
    if venue == "oanda":
        from bot.brokers.oanda_broker import OandaBroker
        return OandaBroker(**kwargs)
    raise ValueError(f"Unknown venue: {venue}")
