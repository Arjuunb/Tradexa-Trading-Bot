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

# Last fetch attempt per symbol — so the engine/diagnostics can show WHY the
# live feed is failing instead of silently falling back. {symbol: {...}}
LAST_FETCH: dict = {}


def _record(symbol: str, timeframe: str, exchange: str, ok: bool,
            bars: int, error: Optional[str]) -> None:
    LAST_FETCH[symbol.upper()] = {
        "symbol": symbol.upper(), "timeframe": timeframe, "exchange": exchange,
        "ok": ok, "bars": bars, "error": error,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    status = f"OK n={bars}" if ok else f"FAILED: {error}"
    # print -> host logs (Render), where deploy debugging actually happens
    print(f"[data] fetch {symbol} {timeframe} via {exchange}: {status}", flush=True)


def last_error(symbol: Optional[str] = None) -> Optional[str]:
    """The most recent fetch error (for one symbol, or any symbol)."""
    if symbol:
        rec = LAST_FETCH.get(symbol.upper())
        return rec.get("error") if rec else None
    for rec in LAST_FETCH.values():
        if rec.get("error"):
            return rec["error"]
    return None


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
        _record(symbol, timeframe, exchange, False, 0, "ccxt not installed")
        return None
    try:
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        rows = ex.fetch_ohlcv(_to_pair(symbol), timeframe=_TF.get(timeframe, "4h"),
                              limit=limit, since=since_ms)
        bars = [Bar(datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc),
                    float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0))
                for r in rows]
        _record(symbol, timeframe, exchange, bool(bars), len(bars), None if bars else "exchange returned 0 rows")
        return bars or None
    except Exception as e:  # noqa: BLE001 — record WHY, then let callers fall back
        # e.g. Binance answers HTTP 451 to US/datacenter IPs (Render US regions)
        _record(symbol, timeframe, exchange, False, 0, f"{type(e).__name__}: {str(e)[:200]}")
        return None
