"""Non-crypto candles via Yahoo (no key) + get_bars routing.

Stocks / forex / commodities get REAL bars so the AI analysis works on every
asset class; crypto routing is untouched; unreachable Yahoo → empty + honest
source, never synthesized. Injected fetcher — no network.
"""
import pytest

from data import yahoo_bars as yb
from data.market_data import get_bars
from services import ttl_cache
from services import ai_intelligence as ai


@pytest.fixture(autouse=True)
def _clean():
    yield
    ttl_cache.clear()


def _payload(n=80, base=100.0):
    ts = [1700000000 + i * 3600 for i in range(n)]
    px = [base + i * 0.5 for i in range(n)]
    return {"chart": {"result": [{
        "timestamp": ts,
        "indicators": {"quote": [{
            "open": px, "high": [p + 1 for p in px], "low": [p - 1 for p in px],
            "close": [p + 0.2 for p in px], "volume": [1000] * n}]},
    }]}}


# ─────────────────────────── mapping ───────────────────────────
def test_symbol_mapping_covers_all_classes():
    assert yb.yahoo_symbol_for("AAPL") == "AAPL"
    assert yb.yahoo_symbol_for("HSBA") == "HSBA.L"          # LSE suffix
    assert yb.yahoo_symbol_for("SPY") == "SPY"
    assert yb.yahoo_symbol_for("UKX") == "^FTSE"
    assert yb.yahoo_symbol_for("EURUSD") == "EURUSD=X"
    assert yb.yahoo_symbol_for("EUR/USD") == "EURUSD=X"     # slash form too
    assert yb.yahoo_symbol_for("XAUUSD") == "GC=F"
    assert yb.yahoo_symbol_for("BTCUSDT") is None           # crypto -> existing pipeline


# ─────────────────────────── fetch + conversion ───────────────────────────
def test_fetch_converts_bars_and_trims():
    bars = yb.fetch_yahoo_bars("AAPL", timeframe="1h", n=50, get_json=lambda url: _payload(80))
    assert bars is not None and len(bars) == 50
    b = bars[-1]
    assert b.high > b.low and b.volume == 1000
    assert b.timestamp.tzinfo is not None                   # aware timestamps


def test_fetch_unreachable_is_none():
    ttl_cache.clear()
    assert yb.fetch_yahoo_bars("AAPL", get_json=lambda url: None) is None


def test_null_padded_rows_skipped():
    p = _payload(5)
    p["chart"]["result"][0]["indicators"]["quote"][0]["close"][2] = None
    bars = yb.fetch_yahoo_bars("SPY", get_json=lambda url: p)
    assert bars is not None and len(bars) == 4              # the null row is dropped


# ─────────────────────────── get_bars routing ───────────────────────────
def test_get_bars_routes_noncrypto_to_yahoo(monkeypatch):
    monkeypatch.setattr("data.yahoo_bars.fetch_yahoo_bars",
                        lambda symbol, timeframe="1d", n=500, **k: yb._to_bars(_payload(60))[-n:])
    bars, src = get_bars("AAPL", n=40, timeframe="1d")
    assert src == "live (yahoo)" and len(bars) == 40


def test_get_bars_noncrypto_unreachable_is_honest(monkeypatch):
    monkeypatch.setattr("data.yahoo_bars.fetch_yahoo_bars", lambda *a, **k: None)
    bars, src = get_bars("EURUSD", n=40, timeframe="1h")
    assert bars == [] and "unavailable" in src              # never synthesized


def test_get_bars_crypto_path_unchanged():
    bars, src = get_bars("BTCUSDT", n=60, timeframe="1h")
    assert bars and "yahoo" not in src                      # crypto untouched


# ─────────────────────────── AI end-to-end on a stock ───────────────────────────
def test_ai_analyzes_a_stock(monkeypatch):
    monkeypatch.setattr("data.yahoo_bars.fetch_yahoo_bars",
                        lambda symbol, timeframe="1d", n=500, **k: yb._to_bars(_payload(250))[-n:])
    bars, src = get_bars("AAPL", n=250, timeframe="1d")
    out = ai.analyze_setup(symbol="AAPL", timeframe="1d", bars=bars, equity=10_000, risk_pct=0.01)
    assert out["decision"] in ("BUY", "SELL", "WAIT", "SKIP")
    assert 0 <= out["overall_score"] <= 100                 # the AI can now score stocks
