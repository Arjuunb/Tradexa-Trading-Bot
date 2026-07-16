"""Live quotes for non-crypto assets via Yahoo Finance (no API key).

Crypto keeps its own candle feed; this fills in stocks / ETFs / indices / forex /
commodities so their prices stop reading "unavailable". Reuses the Yahoo chart
endpoint the news module already calls, and the same fail-closed fetcher — if
Yahoo is unreachable (or a cloud IP is blocked) the quote is simply None and the
caller reports it as unavailable, never fabricated.
"""
from __future__ import annotations

from typing import Optional

_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"

# explicit Yahoo tickers where the catalog symbol differs
_INDEX_MAP = {
    "SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "UKX": "^FTSE", "DAX": "^GDAXI",
    "NKY": "^N225", "RUT": "^RUT", "VIX": "^VIX",
}
_COMMODITY_MAP = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "WTIUSD": "CL=F", "BCOUSD": "BZ=F",
    "NGUSD": "NG=F", "XPTUSD": "PL=F", "HGUSD": "HG=F",
}


def yahoo_symbol(record: dict) -> Optional[str]:
    """Map a symbol-universe record to a Yahoo Finance ticker (None for crypto)."""
    ac = record.get("asset_class")
    ticker = record.get("ticker", "")
    if ac == "crypto":
        return None
    if ac in ("stock", "etf"):
        return f"{ticker}.L" if record.get("exchange") == "LSE" else ticker
    if ac == "index":
        return _INDEX_MAP.get(ticker, f"^{ticker}")
    if ac == "forex":
        base, quote = record.get("base"), record.get("quote")
        return f"{base}{quote}=X" if base and quote else None
    if ac == "commodity":
        return _COMMODITY_MAP.get(ticker)
    return None


def _extract(d: dict) -> Optional[dict]:
    try:
        res = d["chart"]["result"][0]
        meta = res.get("meta", {}) or {}
        quote = (res.get("indicators", {}).get("quote", [{}]) or [{}])[0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        price = meta.get("regularMarketPrice")
        if price is None and closes:
            price = closes[-1]
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if prev is None and len(closes) >= 2:
            prev = closes[-2]
        if price is None or not prev:
            return None
        vols = [v for v in (quote.get("volume") or []) if v is not None]
        volume = meta.get("regularMarketVolume") or (vols[-1] if vols else None)
        return {
            "price": round(float(price), 6),
            "change_24h_pct": round((float(price) - float(prev)) / float(prev) * 100, 2),
            "volume_24h": round(float(volume), 2) if volume else None,
            "source": "yahoo",
        }
    except Exception:  # noqa: BLE001 — malformed payload -> unavailable, never faked
        return None


def quote(record: dict, *, get_json=None, ttl: float = 60.0) -> Optional[dict]:
    """Live quote for one non-crypto symbol, cached briefly. None when the
    symbol has no Yahoo mapping or the source is unreachable."""
    ysym = yahoo_symbol(record)
    if not ysym:
        return None
    if get_json is None:
        from services.sentiment import _get_json as get_json  # fail-closed fetcher

    from services.ttl_cache import cached
    key = f"quote:{ysym}"

    def _run() -> dict:
        d = get_json(_YAHOO.format(sym=ysym))
        q = _extract(d) if d else None
        # ttl_cache only stores truthy/available results; wrap so None retries
        return q or {"available": False}

    out = cached(key, ttl, _run)
    return None if out.get("available") is False else out
