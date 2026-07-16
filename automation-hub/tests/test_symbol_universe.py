"""Multi-asset symbol universe: catalog, search, filters, market info, and the
persistent favorites / pins / watchlists store.

The live CCXT crypto sync is forced to its offline fallback so these tests are
deterministic and never touch the network.
"""
from datetime import datetime, timezone

import pytest

from data.watchlist_store import WatchlistStore
from services import symbol_universe as su
from services import ttl_cache


@pytest.fixture(autouse=True)
def offline_crypto(monkeypatch):
    # force the crypto seed fallback + stub non-crypto quotes offline so these
    # tests are deterministic regardless of network or cross-test quote caching.
    monkeypatch.setattr(su, "_ccxt_crypto", lambda names: None)
    import services.quote_provider as qp
    monkeypatch.setattr(qp, "quote", lambda record, **k: None)
    ttl_cache.invalidate("symbol_universe")
    yield
    ttl_cache.invalidate("symbol_universe")


# ─────────────────────────── catalog ───────────────────────────
def test_catalog_spans_all_asset_classes():
    classes = {c["asset_class"] for c in su.asset_classes()}
    assert {"crypto", "stock", "etf", "index", "forex", "commodity"} <= classes


def test_catalog_uses_fallback_when_offline():
    cat = su.catalog(force=True)
    assert cat["crypto_source"].startswith("fallback")
    assert any(s["symbol"] == "BTC/USDT" for s in cat["symbols"])


# ─────────────────────────── search ───────────────────────────
def test_search_by_ticker():
    res = su.search("BTC")
    assert res and res[0]["symbol"] == "BTC/USDT"          # exact/prefix ranks first


def test_search_by_asset_name():
    names = [r["ticker"] for r in su.search("Apple")]
    assert "AAPL" in names


def test_search_bitcoin_by_name():
    assert any(r["symbol"] == "BTC/USDT" for r in su.search("Bitcoin"))


def test_search_empty_returns_nothing():
    assert su.search("") == []


# ─────────────────────────── filters ───────────────────────────
def test_filter_by_asset_class():
    rows = su.filter_symbols(asset_class="forex")
    assert rows and all(r["asset_class"] == "forex" for r in rows)
    assert any(r["symbol"] == "EUR/USD" for r in rows)


def test_filter_usdt_pairs():
    rows = su.filter_symbols(asset_class="crypto", quote="USDT")
    assert rows and all(r["quote"] == "USDT" for r in rows)


def test_filter_btc_pairs():
    rows = su.filter_symbols(asset_class="crypto", quote="BTC")
    assert rows and all(r["quote"] == "BTC" for r in rows)


def test_filter_by_explicit_tickers_favorites():
    rows = su.filter_symbols(tickers=["AAPL", "BTCUSDT"])
    got = {r["ticker"] for r in rows}
    assert "AAPL" in got and "BTCUSDT" in got


# ─────────────────────────── market info / status ───────────────────────────
def test_market_status_crypto_always_open():
    assert su.market_status("crypto", "Binance") == "open"


def test_market_status_equity_closed_on_weekend():
    sat = datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc)   # Saturday, mid-US-session hour
    assert su.market_status("stock", "NASDAQ", now=sat) == "closed"


def test_market_status_nasdaq_open_midsession_weekday():
    wed = datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc)   # Wed 15:00 UTC (US open)
    assert su.market_status("stock", "NASDAQ", now=wed) == "open"


def test_market_info_stock_has_metadata_no_fabricated_price():
    info = su.market_info("AAPL")
    assert info["found"] and info["asset_class"] == "stock"
    assert info["price_available"] is False        # no provider wired -> never faked
    assert info["exchange"] == "NASDAQ"


def test_market_info_unknown_symbol():
    assert su.market_info("NOPE123")["found"] is False


# ─────────────────────────── favorites / pins / watchlists ───────────────────────────
def test_favorite_toggle(tmp_path):
    st = WatchlistStore(str(tmp_path / "w.db"))
    st.set_favorite("BTCUSDT", True)
    assert "BTCUSDT" in st.get()["favorites"]
    st.set_favorite("BTCUSDT", False)
    assert "BTCUSDT" not in st.get()["favorites"]


def test_pin_implies_favorite_and_unfavorite_unpins(tmp_path):
    st = WatchlistStore(str(tmp_path / "w.db"))
    st.set_pin("ETHUSDT", True)
    d = st.get()
    assert "ETHUSDT" in d["pinned"] and "ETHUSDT" in d["favorites"]  # pin implies favorite
    st.set_favorite("ETHUSDT", False)
    assert "ETHUSDT" not in st.get()["pinned"]                       # unfavorite unpins


def test_watchlist_crud(tmp_path):
    st = WatchlistStore(str(tmp_path / "w.db"))
    st.create_watchlist("Crypto", ["BTCUSDT"])
    wid = st.get()["watchlists"][0]["id"]
    st.set_watchlist_symbol(wid, "ETHUSDT", True)
    st.rename_watchlist(wid, "Majors")
    wl = st.get()["watchlists"][0]
    assert wl["name"] == "Majors" and set(wl["symbols"]) == {"BTCUSDT", "ETHUSDT"}
    st.set_watchlist_symbol(wid, "BTCUSDT", False)
    assert st.get()["watchlists"][0]["symbols"] == ["ETHUSDT"]
    st.delete_watchlist(wid)
    assert st.get()["watchlists"] == []


def test_watchlist_persists_across_reopen(tmp_path):
    path = str(tmp_path / "w.db")
    WatchlistStore(path).create_watchlist("US Stocks", ["AAPL", "TSLA"])
    reopened = WatchlistStore(path)          # simulates restart
    assert reopened.get()["watchlists"][0]["name"] == "US Stocks"
