"""Catalog of available strategies and exchanges.

Single source of truth the UI and BotManager use to list options and to
construct concrete objects from a BotConfig's string keys.
"""
from __future__ import annotations

from strategies.base_strategy import HubStrategy
from strategies.ema_strategy import EMAStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.smc_strategy import SMCStrategy

# key -> (class, human label, ready?)
STRATEGIES: dict[str, tuple[type[HubStrategy], str, bool]] = {
    "ema": (EMAStrategy, "EMA Trend Bot", True),
    "rsi": (RSIStrategy, "RSI Scalper", True),
    "smc": (SMCStrategy, "SMC Bot", False),   # Phase 2
}

# key -> (human label, asset class, ready?)
EXCHANGES: dict[str, tuple[str, str, bool]] = {
    "binance": ("Binance", "crypto", True),    # Phase 2 live wiring
    "bybit": ("Bybit", "crypto", False),
    "alpaca": ("Alpaca", "stocks", False),
}


def build_strategy(key: str, symbol: str, **params) -> HubStrategy:
    if key not in STRATEGIES:
        raise ValueError(f"unknown strategy {key!r}")
    cls, _label, _ready = STRATEGIES[key]
    return cls(symbol=symbol, **params)


def strategy_label(key: str) -> str:
    return STRATEGIES.get(key, (None, key, False))[1]


def exchange_label(key: str) -> str:
    return EXCHANGES.get(key, (key, "", False))[0]
