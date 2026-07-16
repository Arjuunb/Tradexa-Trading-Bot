"""Live non-crypto quotes via Yahoo Finance (no API key).

Uses an injected fetcher so the tests never touch the network. Verifies the
symbol mapping, quote extraction, and that an unreachable source degrades to
None (never a fabricated price).
"""
import pytest

from services import quote_provider as qp
from services import ttl_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    # these tests seed the shared TTL cache with fake quotes; clear after each so
    # they never leak into other tests (e.g. market_info's "no fabricated price").
    yield
    ttl_cache.clear()


def _rec(ticker, ac, exchange="", base="", quote=""):
    return {"ticker": ticker, "symbol": f"{base}/{quote}" if base else ticker,
            "asset_class": ac, "exchange": exchange, "base": base, "quote": quote}


# ─────────────────────────── symbol mapping ───────────────────────────
def test_yahoo_symbol_mapping():
    assert qp.yahoo_symbol(_rec("AAPL", "stock", "NASDAQ")) == "AAPL"
    assert qp.yahoo_symbol(_rec("HSBA", "stock", "LSE")) == "HSBA.L"      # London suffix
    assert qp.yahoo_symbol(_rec("SPY", "etf", "NYSE Arca")) == "SPY"
    assert qp.yahoo_symbol(_rec("UKX", "index")) == "^FTSE"
    assert qp.yahoo_symbol(_rec("EURUSD", "forex", base="EUR", quote="USD")) == "EURUSD=X"
    assert qp.yahoo_symbol(_rec("XAUUSD", "commodity")) == "GC=F"
    assert qp.yahoo_symbol(_rec("BTCUSDT", "crypto")) is None            # crypto has its own feed


# ─────────────────────────── quote extraction ───────────────────────────
def _yahoo_payload(price, prev, vol=1000):
    return {"chart": {"result": [{
        "meta": {"regularMarketPrice": price, "chartPreviousClose": prev, "regularMarketVolume": vol},
        "indicators": {"quote": [{"close": [prev, price], "volume": [vol, vol]}]},
    }]}}


def test_quote_returns_live_numbers():
    ttl_cache.invalidate("quote:AAPL")
    fake = lambda url: _yahoo_payload(190.0, 188.0)   # noqa: E731
    q = qp.quote(_rec("AAPL", "stock", "NASDAQ"), get_json=fake, ttl=0)
    assert q["price"] == 190.0
    assert q["change_24h_pct"] == round((190 - 188) / 188 * 100, 2)
    assert q["source"] == "yahoo"


def test_quote_unreachable_is_none_not_faked():
    ttl_cache.invalidate("quote:^FTSE")
    q = qp.quote(_rec("UKX", "index"), get_json=lambda url: None, ttl=0)
    assert q is None                                   # never a fabricated price


def test_quote_none_for_crypto():
    assert qp.quote(_rec("BTCUSDT", "crypto"), get_json=lambda url: {}, ttl=0) is None
