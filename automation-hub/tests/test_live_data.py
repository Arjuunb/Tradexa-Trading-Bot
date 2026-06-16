"""Real-data adapter: graceful fallback when ccxt/network is unavailable."""
from data.live_data import _to_pair, fetch_ohlcv
from data.market_data import get_bars


def test_symbol_to_pair():
    assert _to_pair("BTCUSDT") == "BTC/USDT"
    assert _to_pair("ETHUSDC") == "ETH/USDC"
    assert _to_pair("ETH/USDT") == "ETH/USDT"


def test_fetch_never_raises_offline():
    # No ccxt or no network must yield None, never an exception.
    out = fetch_ohlcv("BTCUSDT", "4h", 10)
    assert out is None or isinstance(out, list)


def test_get_bars_always_returns_data():
    bars, src = get_bars("BTCUSDT", n=200, timeframe="4h")
    assert bars
    assert src in ("bundled sample", "synthetic", "live (ccxt)")
