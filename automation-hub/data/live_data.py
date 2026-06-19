"""Optional real market data via ccxt (Binance by default).

Used when ``HUB_USE_LIVE_DATA=1`` and ccxt is installed (``pip install ccxt``);
otherwise the engine falls back to bundled/synthetic data. Network and ccxt are
never required for tests — every failure path returns ``None`` so callers fall
back cleanly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from bot.types import Bar

_TF = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
       "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d"}


def _to_pair(symbol: str) -> str:
    if "/" in symbol:
        return symbol.upper()
    s = symbol.upper()
    for q in ("USDT", "USDC", "BUSD", "USD"):
        if s.endswith(q):
            return f"{s[:-len(q)]}/{q}"
    return s


def fetch_ohlcv(symbol: str, timeframe: str = "4h", limit: int = 500,
                exchange: str = "binance", since_ms: Optional[int] = None) -> Optional[list[Bar]]:
    """Return real OHLCV bars, or ``None`` if ccxt/network is unavailable.

    ``since_ms`` (epoch milliseconds) fetches candles starting at that time —
    used by the replay engine to jump to a specific historical date range.
    """
    try:
        import ccxt  # optional dependency
    except Exception:
        return None
    try:
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        rows = ex.fetch_ohlcv(_to_pair(symbol), timeframe=_TF.get(timeframe, "4h"),
                              limit=limit, since=since_ms)
        bars = [Bar(datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc),
                    float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0))
                for r in rows]
        return bars or None
    except Exception:
        return None
