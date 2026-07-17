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


def _from_local_store(symbol: str, n: int, timeframe: str, since_ms):
    """Read REAL cached Binance candles from the local historical store, if any."""
    try:
        from config import settings
        from data.historical import HistoricalStore
        store = HistoricalStore(settings.market_db)
        bars = store.get_bars(symbol, timeframe, n=n, start_ms=since_ms)
        # need a meaningful amount of real history to use it
        if len(bars) >= min(n, 200):
            return bars
    except Exception:  # noqa: BLE001 — store missing/empty -> fall through
        pass
    return None


def get_bars(symbol: str, n: int = 1500, timeframe: str = "1h",
             seed: int = 1, since_ms: Optional[int] = None,
             require_real: bool = False) -> tuple[list[Bar], str]:
    """Return (bars, source) for a symbol, REAL data first.

    Order: local cache of real Binance candles -> live ccxt (if enabled) ->
    bundled sample -> deterministic synthetic. Set ``HUB_REQUIRE_REAL_DATA=1``
    (env) or pass ``require_real=True`` to forbid the bundled/synthetic
    fallbacks entirely (production / replay: never fake data). ``since_ms``
    (epoch ms) selects history from a specific start time.
    """
    # 0. non-crypto assets (stocks / ETFs / indices / forex / commodities from
    # the symbol catalog): real candles via Yahoo (no key). Fail-closed — if
    # Yahoo is unreachable these return EMPTY with an honest source string;
    # non-crypto bars are never synthesized.
    from data.yahoo_bars import fetch_yahoo_bars, yahoo_symbol_for
    if yahoo_symbol_for(symbol):
        ybars = fetch_yahoo_bars(symbol, timeframe=timeframe, n=n)
        if ybars:
            return ybars, "live (yahoo)"
        return [], "unavailable (yahoo unreachable)"

    # 1. local cache of real candles (populated by the /data/sync engine)
    cached = _from_local_store(symbol, n, timeframe, since_ms)
    if cached:
        return cached, "local store (real)"

    # 2. live ccxt fetch when enabled
    if os.environ.get("HUB_USE_LIVE_DATA", "").lower() in ("1", "true", "yes"):
        from data.live_data import fetch_ohlcv
        exchange = os.environ.get("HUB_EXCHANGE", "binance")
        real = fetch_ohlcv(symbol, timeframe=timeframe, limit=n, exchange=exchange, since_ms=since_ms)
        if real:
            return real, "live (ccxt)"

    require_real = require_real or os.environ.get("HUB_REQUIRE_REAL_DATA", "").lower() in ("1", "true", "yes")
    if require_real:
        return [], "unavailable (real data required — run /data/sync)"

    # 3. bundled sample (real historical CSV shipped with the repo)
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

    # 4. deterministic synthetic (demo/tests only; not all timeframes supported)
    try:
        return generate_bars(n=n, timeframe=timeframe, seed=seed), "synthetic"
    except ValueError:
        return [], f"unavailable (no real data for {symbol} {timeframe})"
