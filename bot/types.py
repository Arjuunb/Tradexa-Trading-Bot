"""Shared dataclasses used across brokers, strategies, backtester, and live runner."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class SignalType(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Bar:
    """OHLCV bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    """Strategy output."""
    timestamp: datetime
    symbol: str
    type: SignalType
    entry: float
    stop_loss: float
    take_profit: float
    reason: str = ""
    confidence: float = 1.0


@dataclass
class Order:
    symbol: str
    side: Side
    qty: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    client_id: Optional[str] = None


@dataclass
class Position:
    symbol: str
    qty: float          # signed: positive = long, negative = short
    avg_price: float
    unrealized_pnl: float = 0.0


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    timestamp: datetime
    fee: float = 0.0


@dataclass
class AccountSnapshot:
    cash: float
    equity: float
    positions: list[Position] = field(default_factory=list)
