"""Market data access.

Phase 1 loads historical bars for paper/backtest runs: a bundled sample CSV
when one matches the symbol, otherwise deterministic synthetic data. Live
streaming is ``data/websocket.py`` (Phase 2).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from bot.data.csv_loader import load_csv_bars
from bot.data.synthetic import generate_bars
from bot.types import Bar

# repo root holds data/samples/*.csv (the existing engine's bundled data)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLES = _REPO_ROOT / "data" / "samples"

# Map common venue symbols to bundled sample files.
_SAMPLE_MAP = {
    "BTCUSDT": "BTC-USD", "BTC-USD": "BTC-USD", "BTCUSD": "BTC-USD",
    "ETHUSDT": "ETH-USD", "ETH-USD": "ETH-USD", "ETHUSD": "ETH-USD",
    "AAPL": "AAPL",
}


def get_bars(symbol: str, n: int = 1500, timeframe: str = "1h",
             seed: int = 1) -> tuple[list[Bar], str]:
    """Return (bars, source) for a symbol.

    With ``HUB_USE_LIVE_DATA=1`` (and ccxt installed + network), fetch real
    candles; otherwise use a bundled sample or deterministic synthetic data.
    """
    if os.environ.get("HUB_USE_LIVE_DATA", "").lower() in ("1", "true", "yes"):
        from data.live_data import fetch_ohlcv
        exchange = os.environ.get("HUB_EXCHANGE", "binance")
        real = fetch_ohlcv(symbol, timeframe=timeframe, limit=n, exchange=exchange)
        if real:
            return real, "live (ccxt)"

    key = symbol.upper().replace("/", "").replace("-", "")
    mapped: Optional[str] = None
    for raw, sample in _SAMPLE_MAP.items():
        if raw.replace("-", "") == key:
            mapped = sample
            break
    if mapped:
        path = _SAMPLES / f"{mapped}.csv"
        if path.exists():
            bars = load_csv_bars(str(path))
            if bars:
                return bars[-n:] if len(bars) > n else bars, "bundled sample"
    return generate_bars(n=n, timeframe=timeframe, seed=seed), "synthetic"
