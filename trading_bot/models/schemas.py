"""Pydantic schemas — light validation for the strategy spec the builder posts."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Rule(BaseModel):
    type: str
    negate: bool = False
    # rule params are free-form (type-specific); validated server-side
    model_config = {"extra": "allow"}


class EntryTree(BaseModel):
    op: str = "AND"
    rules: list[dict[str, Any]] = Field(default_factory=list)


class StrategySpec(BaseModel):
    name: str = "My Strategy"
    market: str = "crypto"
    symbol: str = "BTCUSDT"
    timeframe: str = "4h"
    side: str = "long"
    entry: EntryTree = Field(default_factory=EntryTree)
    stop: dict[str, Any] = Field(default_factory=lambda: {"type": "atr", "mult": 1.5, "period": 14})
    target: dict[str, Any] = Field(default_factory=lambda: {"type": "rr", "rr": 1.5})
    risk_per_trade_pct: float = 0.01
    max_trades_per_day: int = 0
    id: Optional[str] = None
