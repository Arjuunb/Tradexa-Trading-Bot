"""Historical market-data engine — REAL Binance candles, cached locally.

A reusable service that fetches genuine OHLCV history from Binance's public REST
API and stores it in a local SQLite database for fast, offline reuse. There is
NO synthetic price generation here: if neither the local cache nor the network
has data, callers get an explicit "unavailable" result, never a fabricated one.

    store = HistoricalStore(db_path)
    sync(store, "BTCUSDT", "4h", target_candles=3000)   # fetch + cache real data
    bars = store.get_bars("BTCUSDT", "4h", n=1500)       # read back as Bar objects

Binance kline endpoint (public, no key):
    GET /api/v3/klines?symbol=BTCUSDT&interval=4h&limit=1000[&endTime=ms]
Row: [openTime, open, high, low, close, volume, closeTime, ...]
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from bot.types import Bar

# Symbols + timeframes the engine officially supports (real Binance markets).
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m")
_TF_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
          "1d": 86_400_000, "1w": 604_800_000}

# Binance REST hosts (the data-api mirror is friendlier to cloud IPs).
_HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")


# --------------------------------------------------------------- local store
class HistoricalStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.execute("""CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT, timeframe TEXT, open_time INTEGER,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (symbol, timeframe, open_time))""")
        return c

    def upsert(self, symbol: str, timeframe: str, rows: list) -> int:
        """rows = [(open_time_ms, o, h, l, c, v), ...]. Returns count written."""
        if not rows:
            return 0
        c = self._conn()
        try:
            c.executemany(
                "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)",
                [(symbol, timeframe, int(r[0]), float(r[1]), float(r[2]),
                  float(r[3]), float(r[4]), float(r[5])) for r in rows])
            c.commit()
            return len(rows)
        finally:
            c.close()

    def get_bars(self, symbol: str, timeframe: str, *, n: Optional[int] = None,
                 start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> list[Bar]:
        c = self._conn()
        try:
            q = "SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol=? AND timeframe=?"
            args: list = [symbol, timeframe]
            if start_ms is not None:
                q += " AND open_time>=?"; args.append(int(start_ms))
            if end_ms is not None:
                q += " AND open_time<=?"; args.append(int(end_ms))
            q += " ORDER BY open_time"
            rows = c.execute(q, args).fetchall()
        finally:
            c.close()
        if n is not None and len(rows) > n:
            rows = rows[-n:]
        return [Bar(datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc),
                    r[1], r[2], r[3], r[4], r[5]) for r in rows]

    def coverage(self, symbol: str, timeframe: str) -> dict:
        c = self._conn()
        try:
            row = c.execute(
                "SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM candles WHERE symbol=? AND timeframe=?",
                (symbol, timeframe)).fetchone()
        finally:
            c.close()
        count, lo, hi = row if row else (0, None, None)
        iso = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None
        return {"symbol": symbol, "timeframe": timeframe, "candles": count or 0,
                "first": iso(lo), "last": iso(hi)}

    def all_coverage(self) -> list:
        return [self.coverage(s, tf) for s in SYMBOLS for tf in TIMEFRAMES]

    def last_open_time(self, symbol: str, timeframe: str) -> Optional[int]:
        c = self._conn()
        try:
            row = c.execute("SELECT MAX(open_time) FROM candles WHERE symbol=? AND timeframe=?",
                            (symbol, timeframe)).fetchone()
        finally:
            c.close()
        return row[0] if row and row[0] is not None else None


# --------------------------------------------------------------- REST fetcher
def fetch_klines(symbol: str, interval: str, *, limit: int = 1000,
                 end_ms: Optional[int] = None, start_ms: Optional[int] = None,
                 hosts=_HOSTS) -> list:
    """Fetch real klines from Binance. Returns raw rows, or raises on failure
    (so callers can distinguish 'no data' from 'fabricated data')."""
    import requests
    params = {"symbol": symbol, "interval": interval, "limit": min(int(limit), 1000)}
    if end_ms is not None:
        params["endTime"] = int(end_ms)
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    last_err = None
    for host in hosts:
        try:
            r = requests.get(f"{host}/api/v3/klines", params=params, timeout=10,
                             headers={"User-Agent": "automation-hub/1.0"})
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — try the next host, then report
            last_err = e
    raise RuntimeError(f"Binance klines fetch failed: {last_err}")


def sync(store: HistoricalStore, symbol: str, timeframe: str, *, target_candles: int = 3000,
         fetcher: Callable = fetch_klines) -> dict:
    """Fetch up to ``target_candles`` recent REAL candles and cache them.

    Pages backward from the latest candle in 1000-row batches. Idempotent (the
    store upserts on the primary key). ``fetcher`` is injectable for testing."""
    if symbol not in SYMBOLS:
        return {"error": f"unsupported symbol {symbol}"}
    if timeframe not in TIMEFRAMES:
        return {"error": f"unsupported timeframe {timeframe}"}
    collected: list = []
    end = None
    try:
        while len(collected) < target_candles:
            batch = fetcher(symbol, timeframe, limit=1000, end_ms=end)
            if not batch:
                break
            collected = batch + collected
            end = int(batch[0][0]) - 1     # one ms before the earliest open time
            if len(batch) < 1000:
                break
            time.sleep(0.25)               # be polite to the API
    except Exception as e:  # noqa: BLE001 — network/API down: report, don't fake
        if not collected:
            return {"error": f"fetch failed and no cache written: {e}", "stored": 0}

    rows = [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in collected]
    written = store.upsert(symbol, timeframe, rows)
    return {"symbol": symbol, "timeframe": timeframe, "fetched": len(collected),
            "stored": written, "source": "binance (real)", **store.coverage(symbol, timeframe)}


def update(store: HistoricalStore, symbol: str, timeframe: str, *,
           fetcher: Callable = fetch_klines) -> dict:
    """Incrementally fetch only candles newer than what's cached."""
    last = store.last_open_time(symbol, timeframe)
    if last is None:
        return sync(store, symbol, timeframe, fetcher=fetcher)
    start = last + _TF_MS.get(timeframe, 0)
    try:
        batch = fetcher(symbol, timeframe, start_ms=start, limit=1000)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "stored": 0}
    rows = [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in batch]
    written = store.upsert(symbol, timeframe, rows)
    return {"symbol": symbol, "timeframe": timeframe, "stored": written,
            "source": "binance (real)", **store.coverage(symbol, timeframe)}


def _main() -> None:
    """CLI: populate the local cache with REAL Binance history.

        python -m data.historical                 # sync all symbols × timeframes
        python -m data.historical BTCUSDT 4h 5000  # one symbol/timeframe/target
    """
    import sys
    try:
        from config import settings
        db = settings.market_db
    except Exception:  # noqa: BLE001
        db = "market_data.db"
    store = HistoricalStore(db)
    args = sys.argv[1:]
    if len(args) >= 2:
        target = int(args[2]) if len(args) > 2 else 3000
        print(sync(store, args[0].upper(), args[1], target_candles=target))
        return
    for s in SYMBOLS:
        for tf in TIMEFRAMES:
            r = sync(store, s, tf, target_candles=int(args[0]) if args else 2000)
            print(f"{s} {tf}: {r.get('stored', r.get('error'))}")


if __name__ == "__main__":
    _main()
