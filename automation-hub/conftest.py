"""Make the Hub's sibling packages importable during test collection, and seed
the local historical store so the REAL-data replay path is exercised in tests.

Replay now refuses to fall back to synthetic data (production never fakes data),
so tests must provide candles through the same channel production uses: the
local Binance cache. We populate a temporary SQLite store with deterministic,
real-shaped OHLCV (generated once) and point ``settings.market_db`` at it. This
is a test fixture only — production reads genuine Binance history.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

# symbols / timeframes the replay + stats tests touch
_SEED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
_SEED_TFS = ("15m", "5m")
_SEED_BARS = 2900  # covers the largest replay window (limit 1500 + 1200 warmup)


def _seed_store(db_path: str) -> None:
    from bot.data.synthetic import generate_bars
    from data.historical import HistoricalStore
    store = HistoricalStore(db_path)
    for si, sym in enumerate(_SEED_SYMBOLS):
        for tf in _SEED_TFS:
            try:
                bars = generate_bars(n=_SEED_BARS, timeframe=tf, seed=11 + si)
            except ValueError:
                continue
            rows = [(int(b.timestamp.timestamp() * 1000), b.open, b.high, b.low, b.close, b.volume)
                    for b in bars]
            store.upsert(sym, tf, rows)


@pytest.fixture(scope="session", autouse=True)
def _seed_market_db(tmp_path_factory):
    """Seed a temp historical store and point config.settings at it for the run."""
    import config
    db = tmp_path_factory.mktemp("market") / "seed.db"
    _seed_store(str(db))
    prev = config.settings.market_db
    config.settings.market_db = str(db)
    yield
    config.settings.market_db = prev
