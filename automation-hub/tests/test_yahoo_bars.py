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


# ─────────────────────────── timeframe integrity ───────────────────────────
# The engine runs at whatever HUB_AUTO_TIMEFRAME says. Before this, an
# unsupported timeframe fell back to DAILY bars — so pointing a 5m engine at a
# stock ran the strategy on daily candles while every report said "5m". The
# bars were real, just not the ones asked for, which is why nothing downstream
# could catch it.

def test_the_engine_default_timeframe_is_actually_supported():
    """5m is the shipped HUB_AUTO_TIMEFRAME on at least one deployment. If it
    is not in the table, adding a stock symbol silently changes timeframe."""
    assert "5m" in yb.supported_timeframes()


def test_an_unsupported_timeframe_is_refused_not_substituted():
    """The whole point. Returning daily bars for a 3m request is worse than
    returning nothing, because only one of those is detectable."""
    assert yb.fetch_yahoo_bars("AAPL", timeframe="3m",
                               get_json=lambda url: _payload(50)) is None


def test_a_refused_timeframe_reaches_get_bars_as_unavailable(monkeypatch):
    bars, src = get_bars("AAPL", n=40, timeframe="3m")
    assert bars == [] and "unavailable" in src


def test_each_supported_timeframe_requests_the_right_yahoo_interval():
    seen = {}

    def spy(url):
        seen["url"] = url
        return _payload(200)

    for tf, expected in (("5m", "interval=5m"), ("15m", "interval=15m"),
                         ("1h", "interval=1h"), ("1d", "interval=1d"),
                         ("1w", "interval=1wk")):
        ttl_cache.clear()
        yb.fetch_yahoo_bars("AAPL", timeframe=tf, get_json=spy)
        assert expected in seen["url"], f"{tf} -> {seen['url']}"


# ─────────────────────────── aggregation ───────────────────────────
# Yahoo has no 4h bar. Asking for one used to return raw HOURLY bars, so a 4h
# Supertrend was computed from 1h candles.

def test_four_hour_bars_are_folded_from_hourly_not_served_raw():
    ttl_cache.clear()
    hourly = yb.fetch_yahoo_bars("AAPL", timeframe="1h", n=400,
                                 get_json=lambda url: _payload(200))
    ttl_cache.clear()
    four_h = yb.fetch_yahoo_bars("AAPL", timeframe="4h", n=400,
                                 get_json=lambda url: _payload(200))
    assert len(four_h) == len(hourly) // 4


def test_a_folded_bar_spans_the_right_amount_of_time():
    """The property that actually matters: consecutive 4h bars are four hours
    apart. A count alone would pass on wrongly-grouped data."""
    ttl_cache.clear()
    bars = yb.fetch_yahoo_bars("AAPL", timeframe="4h", n=50,
                               get_json=lambda url: _payload(200))
    gap = (bars[1].timestamp - bars[0].timestamp).total_seconds()
    assert gap == 4 * 3600


def test_a_folded_bar_preserves_open_high_low_close():
    from datetime import datetime, timezone
    from bot.types import Bar

    def bar(i, o, h, l, c, v):  # noqa: E741
        return Bar(timestamp=datetime.fromtimestamp(1700000000 + i * 3600, tz=timezone.utc),
                   open=o, high=h, low=l, close=c, volume=v)

    src = [bar(0, 10, 15, 9, 12, 100), bar(1, 12, 20, 11, 18, 200),
           bar(2, 18, 19, 8, 9, 300), bar(3, 9, 14, 7, 13, 400)]
    folded = yb._fold(src, 4)
    assert len(folded) == 1
    b = folded[0]
    assert (b.open, b.high, b.low, b.close, b.volume) == (10, 20, 7, 13, 1000)
    assert b.timestamp == src[0].timestamp        # stamped at the group's START


def test_folding_drops_a_short_trailing_group_rather_than_emitting_it():
    """A 4h bar built from one hour of trading is not a 4h bar, and a live
    strategy acts on the newest bar — so a short one is the worst to fake."""
    from datetime import datetime, timezone
    from bot.types import Bar
    src = [Bar(timestamp=datetime.fromtimestamp(1700000000 + i * 3600, tz=timezone.utc),
               open=1, high=2, low=0.5, close=1.5, volume=1) for i in range(9)]
    folded = yb._fold(src, 4)
    assert len(folded) == 2                        # 9 hours -> two whole 4h bars


def test_folding_keeps_the_newest_data_in_the_last_bar():
    """Folded from the end, so the most recent close is the most recent bar's
    close. Folding from the start would leave the newest partial group at an
    arbitrary offset."""
    from datetime import datetime, timezone
    from bot.types import Bar
    src = [Bar(timestamp=datetime.fromtimestamp(1700000000 + i * 3600, tz=timezone.utc),
               open=1, high=2, low=0.5, close=float(i), volume=1) for i in range(8)]
    assert yb._fold(src, 4)[-1].close == 7.0


def test_folding_by_one_is_the_identity():
    bars = yb._to_bars(_payload(10))
    assert yb._fold(bars, 1) == bars


def test_crypto_is_still_untouched_by_all_of_this():
    """Crypto never routes through Yahoo — it has its own Binance/CCXT feed at
    every timeframe, including the ones Yahoo cannot serve."""
    assert yb.fetch_yahoo_bars("BTCUSDT", timeframe="5m",
                               get_json=lambda url: _payload(50)) is None
    bars, src = get_bars("BTCUSDT", n=60, timeframe="5m")
    assert bars and "yahoo" not in src
