"""Live market-data feeds.

A *feed* yields closed bars one at a time; the live runner steps the engine on
each. Two implementations:

- ``ReplayFeed``  — streams historical/synthetic bars (offline, deterministic).
  Used for the in-app "go live" demo and for tests, since the runner code path
  is identical to a real feed.
- ``BrokerFeed``  — wraps any ``bot.brokers.base.Broker.stream_bars`` (Binance
  via ccxt, Alpaca, OANDA). This is the real-time Phase-2 path; it needs the
  venue SDK + network, so it's exercised live rather than in CI.
"""
from __future__ import annotations

import time
from threading import Event
from typing import Iterator, Optional, Sequence

from bot.types import Bar


class LiveFeed:
    """Feed interface: ``stream(stop)`` yields ``Bar`` until exhausted/stopped."""

    def stream(self, stop: Optional[Event] = None) -> Iterator[Bar]:  # pragma: no cover
        raise NotImplementedError


class ReplayFeed(LiveFeed):
    def __init__(self, bars: Sequence[Bar], delay_s: float = 0.0):
        self.bars = list(bars)
        self.delay_s = delay_s

    def stream(self, stop: Optional[Event] = None) -> Iterator[Bar]:
        for bar in self.bars:
            if stop is not None and stop.is_set():
                return
            yield bar
            if self.delay_s:
                time.sleep(self.delay_s)


class BrokerFeed(LiveFeed):
    """Real-time feed over a broker's ``stream_bars`` generator."""

    def __init__(self, broker, symbol: str, timeframe: str = "1h"):
        self.broker = broker
        self.symbol = symbol
        self.timeframe = timeframe

    def stream(self, stop: Optional[Event] = None) -> Iterator[Bar]:  # pragma: no cover
        for bar in self.broker.stream_bars(self.symbol, self.timeframe):
            if stop is not None and stop.is_set():
                return
            yield bar
