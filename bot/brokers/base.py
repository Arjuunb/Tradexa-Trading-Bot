"""Abstract broker interface. Every concrete broker implements these methods.

This is the multi-asset abstraction: the rest of the bot (strategy, risk,
backtester, live runner) only talks to a Broker, never to Binance / Alpaca /
OANDA directly. To support a new venue, write a new subclass.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, Optional

from bot.types import AccountSnapshot, Bar, Fill, Order, Position


class Broker(ABC):
    """Unified broker / exchange interface."""

    # ------------------------------------------------------------------ data
    @abstractmethod
    def get_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[Bar]:
        """Return OHLCV bars for backtesting or warm-up."""

    @abstractmethod
    def stream_bars(self, symbol: str, timeframe: str) -> Iterable[Bar]:
        """Yield new bars as they close (live trading)."""

    # ---------------------------------------------------------------- account
    @abstractmethod
    def get_account(self) -> AccountSnapshot:
        """Cash, equity, open positions."""

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        ...

    # ----------------------------------------------------------------- orders
    @abstractmethod
    def submit_order(self, order: Order) -> str:
        """Submit and return broker order id."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        ...

    @abstractmethod
    def get_fills(self, since: Optional[datetime] = None) -> list[Fill]:
        ...

    # ----------------------------------------------------------------- helpers
    @property
    @abstractmethod
    def name(self) -> str:
        ...
