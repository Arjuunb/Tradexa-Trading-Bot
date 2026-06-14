"""Live market-data websocket feed — Phase 2 interface.

Phase 1 trades on historical/synthetic bars (see ``market_data.py``). The live
supervisor will subscribe to this feed and push closed bars into each running
bot's strategy. Defined now so the scheduler/execution path can depend on it.
"""
from __future__ import annotations

from typing import Callable, Iterator

from bot.types import Bar

BarHandler = Callable[[Bar], None]


class LiveFeed:
    """Streaming bar feed. Phase 2 will back this with ccxt.watch_ohlcv /
    exchange websockets; the interface stays stable."""

    def __init__(self, symbol: str, timeframe: str = "1h"):
        self.symbol = symbol
        self.timeframe = timeframe
        self._handlers: list[BarHandler] = []

    def on_bar(self, handler: BarHandler) -> None:
        self._handlers.append(handler)

    def stream(self) -> Iterator[Bar]:  # pragma: no cover - Phase 2
        raise NotImplementedError("Live websocket streaming lands in Phase 2.")
