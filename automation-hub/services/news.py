"""World & market news — keyless, multi-market, honest.

Aggregates public RSS feeds from major crypto AND stock/macro outlets (no API
keys, no scraping tricks — plain RSS), tags every headline with the markets it
touches (crypto / stocks / macro) via transparent keyword rules, and pairs the
feed with a REAL market snapshot (S&P 500, Nasdaq, BTC daily moves) so impact
is shown with numbers instead of invented narratives.

Feeds fail independently: one dead outlet never empties the page, and when
everything is unreachable the endpoint says so — it never fabricates news.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree import ElementTree

_TIMEOUT = 8

# (source label, url, default market tag)
FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    ("Cointelegraph", "https://cointelegraph.com/rss", "crypto"),
    ("CNBC Markets", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "stocks"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/", "stocks"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex", "stocks"),
]

# transparent keyword tagging — a headline can touch several markets
_TAGS = {
    "crypto": ("bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "xrp",
               "binance", "coinbase", "stablecoin", "defi", "etf inflow", "altcoin"),
    "stocks": ("stocks", "s&p", "nasdaq", "dow", "earnings", "shares", "equit",
               "wall street", "ipo", "nyse", "tesla", "nvidia", "apple", "microsoft"),
    "macro": ("fed", "fomc", "rate", "inflation", "cpi", "jobs report", "payroll",
              "tariff", "war", "opec", "oil", "treasury", "recession", "gdp",
              "central bank", "dollar", "election", "sanction", "trade deal"),
}


def _fetch(url: str) -> Optional[str]:
    try:
        import requests
        r = requests.get(url, timeout=_TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0 (automation-hub)"})
        r.raise_for_status()
        return r.text
    except Exception:  # noqa: BLE001 — a dead feed is skipped, never faked
        return None


def parse_rss(xml_text: str, source: str, default_market: str, limit: int = 10) -> list[dict]:
    """Parse RSS 2.0 items -> headline dicts. Malformed feeds return []."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        published = ""
        raw = item.findtext("pubDate") or ""
        try:
            published = parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            pass
        out.append({"title": title, "url": (item.findtext("link") or "").strip(),
                    "source": source, "published": published,
                    "markets": tag_markets(title, default_market)})
        if len(out) >= limit:
            break
    return out


def tag_markets(title: str, default_market: str) -> list[str]:
    t = title.lower()
    tags = [m for m, words in _TAGS.items() if any(w in t for w in words)]
    if not tags:
        tags = [default_market]
    return tags


def world_news(fetch=_fetch, limit: int = 30) -> dict:
    """Aggregate all feeds, newest first, deduped by title."""
    headlines: list[dict] = []
    sources_ok, sources_down = [], []
    for source, url, market in FEEDS:
        xml_text = fetch(url)
        items = parse_rss(xml_text, source, market) if xml_text else []
        (sources_ok if items else sources_down).append(source)
        headlines.extend(items)
    seen: set[str] = set()
    unique = []
    for h in sorted(headlines, key=lambda x: x["published"] or "", reverse=True):
        key = h["title"].lower()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return {"available": bool(unique), "headlines": unique[:limit],
            "sources_ok": sources_ok, "sources_down": sources_down,
            **({} if unique else {"note": "No news feed reachable right now — nothing is fabricated."})}


# ------------------------------------------------------- market snapshot
_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"
_INDICES = [("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Gold", "GC=F")]


def _yahoo_change(sym: str, get_json) -> Optional[dict]:
    d = get_json(_YAHOO.format(sym=sym))
    try:
        res = d["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        last, prev = closes[-1], closes[-2]
        return {"last": round(last, 2), "change_pct": round((last - prev) / prev * 100, 2)}
    except Exception:  # noqa: BLE001
        return None


def _btc_change() -> Optional[dict]:
    """BTC daily move from OUR OWN cached candles (real, zero extra network)."""
    try:
        from config import settings
        from data.historical import HistoricalStore
        bars = HistoricalStore(settings.market_db).get_bars("BTCUSDT", "1d", n=2)
        if len(bars) >= 2:
            last, prev = bars[-1].close, bars[-2].close
            return {"last": round(last, 2), "change_pct": round((last - prev) / prev * 100, 2)}
    except Exception:  # noqa: BLE001
        pass
    return None


def market_snapshot(get_json=None) -> dict:
    """Real daily moves for the markets the news affects. Every unavailable
    market is reported as such — no placeholders."""
    if get_json is None:
        from services.sentiment import _get_json as get_json  # type: ignore
    out = {}
    btc = _btc_change()
    out["BTC"] = ({"available": True, **btc} if btc
                  else {"available": False, "note": "no cached candles — run the data load"})
    for label, sym in _INDICES:
        q = _yahoo_change(sym, get_json)
        out[label] = ({"available": True, **q} if q
                      else {"available": False, "note": "quote source unreachable"})
    return out


# ------------------------------------------------------------ small cache
_cache_lock = threading.Lock()
_cache: dict = {}


def cached_world_news(ttl: float = 300.0) -> dict:
    with _cache_lock:
        hit = _cache.get("news")
        if hit and time.time() - hit[0] < ttl and hit[1].get("available"):
            return hit[1]
    fresh = {"news": world_news(), "snapshot": market_snapshot(),
             "updated": datetime.now(timezone.utc).isoformat()}
    merged = {**fresh["news"], "snapshot": fresh["snapshot"], "updated": fresh["updated"]}
    with _cache_lock:
        _cache["news"] = (time.time(), merged)
    return merged
