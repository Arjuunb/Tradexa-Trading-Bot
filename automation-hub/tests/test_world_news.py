"""World & market news: keyless RSS aggregation, market tagging, real
snapshot, honest empties."""
from datetime import datetime, timedelta, timezone

import pytest

from services.news import (market_snapshot, parse_rss, tag_markets, world_news)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item><title>Fed holds rates steady as inflation cools</title>
  <link>https://x/1</link><pubDate>Thu, 02 Jul 2026 15:00:00 GMT</pubDate></item>
<item><title>Bitcoin ETF inflows hit record high</title>
  <link>https://x/2</link><pubDate>Thu, 02 Jul 2026 14:00:00 GMT</pubDate></item>
<item><title>Nvidia earnings crush estimates, shares jump</title>
  <link>https://x/3</link><pubDate>Thu, 02 Jul 2026 13:00:00 GMT</pubDate></item>
</channel></rss>"""


# ─────────────────────────── parsing + tagging ───────────────────────────
def test_parse_rss_extracts_items_with_utc_times():
    items = parse_rss(RSS, "TestFeed", "stocks")
    assert len(items) == 3
    assert items[0]["title"].startswith("Fed holds")
    assert items[0]["source"] == "TestFeed"
    assert items[0]["published"].startswith("2026-07-02T15:00")


def test_parse_rss_handles_garbage():
    assert parse_rss("<not xml", "X", "crypto") == []


def test_market_tagging_is_transparent():
    assert "macro" in tag_markets("Fed signals rate cut in September", "stocks")
    assert "crypto" in tag_markets("Ethereum upgrade ships", "stocks")
    assert "stocks" in tag_markets("Nasdaq closes at record", "crypto")
    # multi-market headline gets multiple tags
    tags = tag_markets("Bitcoin falls as Fed hints at rate hike", "crypto")
    assert "crypto" in tags and "macro" in tags
    # nothing matched -> the feed's own market
    assert tag_markets("Weather is nice today", "stocks") == ["stocks"]


# ─────────────────────────── aggregation ───────────────────────────
def test_world_news_aggregates_dedupes_and_reports_dead_feeds():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return RSS if "coindesk" in url or "cnbc" in url else None

    out = world_news(fetch=fake_fetch)
    assert out["available"] is True
    assert len(out["headlines"]) == 3                # duplicates collapsed
    assert set(out["sources_ok"]) == {"CoinDesk", "CNBC Markets"}
    assert "Cointelegraph" in out["sources_down"]
    # newest first
    times = [h["published"] for h in out["headlines"]]
    assert times == sorted(times, reverse=True)


def test_world_news_honest_when_everything_is_down():
    out = world_news(fetch=lambda url: None)
    assert out["available"] is False and out["headlines"] == []
    assert "fabricat" in out["note"]


# ─────────────────────────── market snapshot ───────────────────────────
def test_snapshot_uses_local_btc_and_yahoo_indices(monkeypatch, tmp_path):
    import config
    from data.historical import HistoricalStore
    monkeypatch.setattr(config.settings, "market_db", str(tmp_path / "m.db"))
    store = HistoricalStore(config.settings.market_db)
    t0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i, close in enumerate([100000, 103000]):
        ms = int((t0 + timedelta(days=i)).timestamp() * 1000)
        store.upsert("BTCUSDT", "1d", [(ms, close, close, close, close, 1)])

    def fake_json(url):
        if "GSPC" in url:
            return {"chart": {"result": [{"indicators": {"quote": [
                {"close": [6000.0, 6060.0]}]}}]}}
        return None

    snap = market_snapshot(get_json=fake_json)
    assert snap["BTC"]["available"] and snap["BTC"]["change_pct"] == 3.0
    assert snap["S&P 500"]["available"] and snap["S&P 500"]["change_pct"] == 1.0
    assert snap["Nasdaq"]["available"] is False     # honest per-market failure


# ─────────────────────────── endpoint ───────────────────────────
def test_news_world_endpoint():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    body = client.get("/news/world").json()
    assert "available" in body and "headlines" in body and "snapshot" in body