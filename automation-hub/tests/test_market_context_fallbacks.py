"""Market-context tiles must WORK, not decorate: keyless fallback chains for
dominance/mcap (CoinGecko→CoinPaprika→Coinlore), funding + open interest
(Binance→Bybit→OKX), and ETH/BTC computed from our own cached real candles."""
from datetime import datetime, timedelta, timezone

import services.market_context as mc
import services.sentiment as sent
from services.market_context import fetch_eth_btc, fetch_funding_rate, fetch_open_interest
from services.sentiment import fetch_global


def _mock(monkeypatch, responses: dict):
    """Dispatch _get_json by URL substring; None for anything unmatched."""
    def fake(url: str):
        for frag, payload in responses.items():
            if frag in url:
                return payload
        return None
    monkeypatch.setattr(sent, "_get_json", fake)
    monkeypatch.setattr(mc, "_get_json", fake)


# ─────────────────── dominance / market cap ───────────────────
def test_global_falls_back_to_coinpaprika(monkeypatch):
    _mock(monkeypatch, {"coinpaprika.com/v1/global":
                        {"bitcoin_dominance_percentage": 52.34, "market_cap_usd": 2.41e12}})
    g = fetch_global()
    assert g["source"] == "coinpaprika" and g["btc_dominance"] == 52.3
    assert g["total_mcap_usd"] == 2.41e12


def test_global_falls_back_to_coinlore_then_none(monkeypatch):
    _mock(monkeypatch, {"coinlore.net/api/global":
                        [{"btc_d": "51.9", "total_mcap": 2.2e12}]})
    g = fetch_global()
    assert g["source"] == "coinlore" and g["btc_dominance"] == 51.9
    _mock(monkeypatch, {})
    assert fetch_global() is None            # every source down -> honest None


def test_global_prefers_coingecko(monkeypatch):
    _mock(monkeypatch, {"coingecko.com/api/v3/global":
                        {"data": {"market_cap_percentage": {"btc": 53.77},
                                  "total_market_cap": {"usd": 2.5e12}}}})
    assert fetch_global()["source"] == "coingecko"


# ─────────────────── funding / open interest ───────────────────
def test_funding_falls_back_to_bybit_then_okx(monkeypatch):
    _mock(monkeypatch, {"api.bybit.com":
                        {"result": {"list": [{"fundingRate": "0.0001", "openInterest": "83214.5"}]}}})
    f = fetch_funding_rate("BTCUSDT")
    assert f["available"] and f["source"] == "bybit" and f["value"] == 0.01
    _mock(monkeypatch, {"okx.com/api/v5/public/funding-rate":
                        {"data": [{"fundingRate": "-0.0002"}]}})
    f2 = fetch_funding_rate("BTCUSDT")
    assert f2["source"] == "okx" and f2["value"] == -0.02
    _mock(monkeypatch, {})
    off = fetch_funding_rate("BTCUSDT")
    assert off["available"] is False and "No perp venue" in off["note"]


def test_open_interest_fallbacks(monkeypatch):
    _mock(monkeypatch, {"api.bybit.com":
                        {"result": {"list": [{"fundingRate": "0.0001", "openInterest": "83214.55"}]}}})
    oi = fetch_open_interest("BTCUSDT")
    assert oi["source"] == "bybit" and oi["value"] == 83214.6
    _mock(monkeypatch, {"okx.com/api/v5/public/open-interest":
                        {"data": [{"oi": "999", "oiCcy": "71234.22"}]}})
    oi2 = fetch_open_interest("BTCUSDT")
    assert oi2["source"] == "okx" and oi2["value"] == 71234.2


# ─────────────────── ETH/BTC from our own candles ───────────────────
def test_eth_btc_prefers_local_real_candles(monkeypatch, tmp_path):
    import config
    from data.historical import HistoricalStore
    monkeypatch.setattr(config.settings, "market_db", str(tmp_path / "m.db"))
    store = HistoricalStore(config.settings.market_db)
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for i in range(31):
        ms = int((t0 + timedelta(days=i)).timestamp() * 1000)
        store.upsert("BTCUSDT", "1d", [(ms, 100000, 101000, 99000, 100000, 1)])
        # ETH rallies vs BTC over the window: ratio 0.03 -> ~0.036
        eth = 3000 + i * 20
        store.upsert("ETHUSDT", "1d", [(ms, eth, eth + 10, eth - 10, eth, 1)])
    _mock(monkeypatch, {})                    # no network at all
    r = fetch_eth_btc()
    assert r["available"] and r["source"] == "local candles (real)"
    assert r["trend"] == "Bullish" and r["change_30d_pct"] > 1


def test_eth_btc_network_fallback_and_honest_none(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config.settings, "market_db", str(tmp_path / "empty.db"))
    _mock(monkeypatch, {"coingecko.com/api/v3/coins/ethereum":
                        {"prices": [[0, 0.030], [1, 0.031], [2, 0.0329]]}})
    r = fetch_eth_btc()
    assert r["available"] and r["source"] == "coingecko" and r["trend"] == "Bullish"
    _mock(monkeypatch, {})
    off = fetch_eth_btc()
    assert off["available"] is False and "backfill" in off["note"]