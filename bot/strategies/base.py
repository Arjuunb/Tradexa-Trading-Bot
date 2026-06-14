"""Abstract strategy interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from bot.types import Bar, Signal


class Strategy(ABC):
    """Receives bars one at a time, returns a Signal or None."""

    name: str = "base"

    def __init__(self, symbol: str, **params):
        self.symbol = symbol
        self.params = params
        self.bars: list[Bar] = []

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        self.bars.append(bar)
        return self.generate(bar)

    @abstractmethod
    def generate(self, bar: Bar) -> Optional[Signal]:
        ...
