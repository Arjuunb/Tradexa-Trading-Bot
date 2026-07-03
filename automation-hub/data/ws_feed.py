"""WebSocket market feed — push candles instead of polling REST.

Runs ccxt.pro ``watch_ohlcv`` streams on a background asyncio thread and keeps
a rolling, thread-safe cache of bars per symbol. The engine consumes it through
``make_fetcher``: when the stream is fresh the engine reads from the cache
(millisecond latency, zero REST rate-limit pressure); the moment the stream is
stale or unavailable it falls back to the given REST fetcher — the bot degrades
gracefully instead of going blind.

No ccxt.pro / no network -> ``available`` is False and the fetcher is a pure
pass-through. The status endpoint reports exactly which mode is serving data.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

from bot.types import Bar

_TF_S = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
         "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def _to_pair(symbol: str) -> str:
    s = symbol.upper().replace("/", "")
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if s.endswith(quote):
            return f"{s[:-len(quote)]}/{quote}"
    return symbol


class WebSocketFeed:
    def __init__(self, symbols: list[str], timeframe: str = "1h",
                 exchange: str = "binance", max_bars: int = 600):
        self.symbols = list(symbols)
        self.timeframe = timeframe
        self.exchange = exchange
        self.max_bars = max_bars
        self._bars: dict[str, deque] = {s: deque(maxlen=max_bars) for s in self.symbols}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.available = False          # a stream is (or was) connected
        self.last_error: str = ""
        self.updates = 0                # candles ingested (all symbols)
        self.last_update: Optional[str] = None

    # ------------------------------------------------------------- ingestion
    def ingest_rows(self, symbol: str, rows: list) -> None:
        """Merge raw OHLCV rows [[ms, o, h, l, c, v], ...] into the cache.
        Updates the in-progress candle in place; appends newly closed ones."""
        bars = [Bar(datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc),
                    float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                    float(r[5] or 0.0)) for r in rows]
        with self._lock:
            dq = self._bars.setdefault(symbol, deque(maxlen=self.max_bars))
            for b in bars:
                if dq and dq[-1].timestamp == b.timestamp:
                    dq[-1] = b                       # refresh in-progress candle
                elif not dq or b.timestamp > dq[-1].timestamp:
                    dq.append(b)
            self.updates += len(bars)
            self.last_update = datetime.now(timezone.utc).isoformat()

    # --------------------------------------------------------------- queries
    def get_bars(self, symbol: str, limit: int = 250) -> list[Bar]:
        with self._lock:
            dq = self._bars.get(symbol) or ()
            return list(dq)[-limit:]

    def fresh(self, symbol: str) -> bool:
        """True when the newest cached candle is recent enough to trade on
        (within 2 timeframe-lengths of now)."""
        bars = self.get_bars(symbol, 1)
        if not bars:
            return False
        age = (datetime.now(timezone.utc) - bars[-1].timestamp).total_seconds()
        return age <= 2 * _TF_S.get(self.timeframe, 3600)

    def status(self) -> dict:
        with self._lock:
            depth = {s: len(dq) for s, dq in self._bars.items()}
        return {"running": self._thread is not None and self._thread.is_alive(),
                "available": self.available, "exchange": self.exchange,
                "timeframe": self.timeframe, "symbols": self.symbols,
                "bars_cached": depth, "updates": self.updates,
                "last_update": self.last_update, "last_error": self.last_error}

    # ------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        """Start the stream thread. Returns False (with last_error set) when
        ccxt.pro isn't installed — callers keep using their REST fetcher."""
        try:
            import ccxt.pro  # noqa: F401
        except Exception as e:  # noqa: BLE001
            self.last_error = f"ccxt.pro unavailable: {e}"
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ws-feed", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import asyncio
        asyncio.run(self._stream())

    async def _stream(self) -> None:
        import asyncio
        import ccxt.pro as ccxtpro
        ex = getattr(ccxtpro, self.exchange)({"enableRateLimit": True})
        try:
            async def watch(sym: str):
                pair = _to_pair(sym)
                while not self._stop.is_set():
                    try:
                        rows = await ex.watch_ohlcv(pair, self.timeframe)
                        self.available = True
                        self.ingest_rows(sym, rows)
                    except Exception as e:  # noqa: BLE001 — reconnect, don't die
                        self.last_error = str(e)
                        await asyncio.sleep(5)
            await asyncio.gather(*(watch(s) for s in self.symbols))
        finally:
            try:
                await ex.close()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------------------- fetcher
    def make_fetcher(self, fallback: Callable[[str, str, int], tuple]):
        """A drop-in engine fetcher: WS cache when fresh, REST fallback when not.
        Seeds the cache from the fallback so streams start with warm history."""
        def fetcher(symbol: str, timeframe: str, limit: int):
            if timeframe == self.timeframe and self.fresh(symbol):
                bars = self.get_bars(symbol, limit)
                if len(bars) >= min(limit, 30):
                    return bars, "live (websocket)"
            bars, src = fallback(symbol, timeframe, limit)
            # keep the cache warm so the stream picks up with full history
            if bars and timeframe == self.timeframe and not self.get_bars(symbol, 1):
                with self._lock:
                    dq = self._bars.setdefault(symbol, deque(maxlen=self.max_bars))
                    dq.extend(bars[-self.max_bars:])
            return bars, src
        return fetcher
