"""Real candles for non-crypto assets via Yahoo Finance (no API key).

Crypto keeps its Binance/CCXT feed; this gives stocks / ETFs / indices / forex /
commodities real OHLCV bars so the AI analysis, replay and Bot Terminal work on
every asset class the Symbol Explorer lists. Same fail-closed philosophy as the
quote provider: unreachable → None, the caller reports "unavailable" — bars are
never synthesized for non-crypto symbols.

The symbol → Yahoo-ticker mapping is resolved from data/symbol_catalog.json
directly (a local file), so this module stays dependency-free and adds no
network call to the lookup path.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bot.types import Bar

_CATALOG = Path(__file__).resolve().parent / "symbol_catalog.json"
_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={iv}"

_INDEX_MAP = {"SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "UKX": "^FTSE",
              "DAX": "^GDAXI", "NKY": "^N225", "RUT": "^RUT", "VIX": "^VIX"}
_COMMODITY_MAP = {"XAUUSD": "GC=F", "XAGUSD": "SI=F", "WTIUSD": "CL=F", "BCOUSD": "BZ=F",
                  "NGUSD": "NG=F", "XPTUSD": "PL=F", "HGUSD": "HG=F"}
# Yahoo interval + a range wide enough for a few hundred bars of that interval,
# plus how many of those to fold into one returned bar.
#
# Yahoo caps intraday history hard (1m: 7 days, anything finer than 1h: 60 days),
# so the ranges here are the widest that actually return data rather than the
# widest we would like.
#
# The `fold` column is what keeps a timeframe HONEST. Yahoo has no 4h bar, and
# the previous version answered a 4h request with raw 1h bars — a strategy would
# compute a 4h Supertrend from hourly candles and never know. Where Yahoo lacks
# the interval we request the next one down and aggregate, so a "4h" bar really
# spans four hours.
_INTERVALS = {
    "1m":  ("1m",  "5d",  1),
    "5m":  ("5m",  "1mo", 1),
    "15m": ("15m", "1mo", 1),
    "30m": ("30m", "1mo", 1),
    "1h":  ("1h",  "3mo", 1),
    "2h":  ("1h",  "6mo", 2),    # aggregated — Yahoo has no 2h
    "4h":  ("1h",  "6mo", 4),    # aggregated — Yahoo has no 4h
    "1d":  ("1d",  "2y",  1),
    "1w":  ("1wk", "5y",  1),
}

_lookup: Optional[dict] = None


def _build_lookup() -> dict:
    """ticker -> yahoo symbol for every non-crypto catalog entry."""
    out: dict[str, str] = {}
    try:
        raw = json.loads(_CATALOG.read_text())
    except Exception:  # noqa: BLE001 — missing/corrupt catalog -> no non-crypto symbols
        return out
    for s in raw.get("stocks", []):
        out[s["ticker"].upper()] = f"{s['ticker']}.L" if s.get("exchange") == "LSE" else s["ticker"]
    for s in raw.get("etf", []):
        out[s["ticker"].upper()] = s["ticker"]
    for s in raw.get("index", []):
        out[s["ticker"].upper()] = _INDEX_MAP.get(s["ticker"], f"^{s['ticker']}")
    for s in raw.get("forex", []):
        out[f"{s['base']}{s['quote']}".upper()] = f"{s['base']}{s['quote']}=X"
    for s in raw.get("commodity", []):
        y = _COMMODITY_MAP.get(s["ticker"])
        if y:
            out[s["ticker"].upper()] = y
    return out


def yahoo_symbol_for(symbol: str) -> Optional[str]:
    """The Yahoo ticker for a NON-crypto catalog symbol, else None (crypto and
    unknown symbols fall through to the existing candle pipeline)."""
    global _lookup
    if _lookup is None:
        _lookup = _build_lookup()
    return _lookup.get(symbol.upper().replace("/", ""))


def _to_bars(payload: dict) -> Optional[list[Bar]]:
    try:
        res = payload["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = (res.get("indicators", {}).get("quote", [{}]) or [{}])[0]
        opens, highs = q.get("open") or [], q.get("high") or []
        lows, closes, vols = q.get("low") or [], q.get("close") or [], q.get("volume") or []
        bars: list[Bar] = []
        for i, t in enumerate(ts):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]  # noqa: E741
            if None in (o, h, l, c):
                continue                                   # Yahoo pads gaps with nulls
            bars.append(Bar(timestamp=datetime.fromtimestamp(t, tz=timezone.utc),
                            open=float(o), high=float(h), low=float(l), close=float(c),
                            volume=float(vols[i] or 0.0) if i < len(vols) else 0.0))
        return bars or None
    except Exception:  # noqa: BLE001 — malformed payload -> unavailable, never faked
        return None


def _fold(bars: list[Bar], factor: int) -> list[Bar]:
    """Aggregate ``factor`` consecutive bars into one — open first, close last,
    high/low the extremes, volume summed.

    Folded from the END so the most recent bar is the one that closes on the
    latest data. Folding from the start would leave the newest (partial) group
    at an arbitrary offset, and the newest bar is the one a live strategy acts
    on. A trailing group with fewer than ``factor`` bars is dropped rather than
    emitted short: a 4h bar built from one hour of trading is not a 4h bar.
    """
    if factor <= 1 or not bars:
        return bars
    out: list[Bar] = []
    # Walk backwards in whole groups, then restore chronological order.
    for end in range(len(bars), factor - 1, -factor):
        group = bars[end - factor:end]
        out.append(Bar(timestamp=group[0].timestamp,
                       open=group[0].open,
                       high=max(b.high for b in group),
                       low=min(b.low for b in group),
                       close=group[-1].close,
                       volume=sum(b.volume for b in group)))
    out.reverse()
    return out


def supported_timeframes() -> tuple[str, ...]:
    """Timeframes this source can serve honestly. Anything else is refused."""
    return tuple(_INTERVALS)


def fetch_yahoo_bars(symbol: str, timeframe: str = "1d", n: int = 500,
                     *, get_json=None) -> Optional[list[Bar]]:
    """Real OHLCV bars for a non-crypto symbol, newest last, trimmed to ``n``.

    None when the symbol isn't a non-crypto catalog entry, the timeframe cannot
    be served, or Yahoo is unreachable. Cached ~5 min so repeated analyses don't
    hammer the source.

    An unknown timeframe returns None rather than falling back to daily. The
    fallback was the more dangerous behaviour by a wide margin: a 5m engine
    silently received DAILY candles and ran its strategy on them, reporting the
    timeframe it asked for. Nothing downstream could detect the substitution —
    the bars were real, just not the ones requested. Refusing is loud; a wrong
    timeframe is silent, and this module already refuses rather than invents
    everywhere else.
    """
    ysym = yahoo_symbol_for(symbol)
    if not ysym:
        return None
    spec = _INTERVALS.get(timeframe)
    if spec is None:
        return None
    iv, rng, fold = spec
    if get_json is None:
        from services.sentiment import _get_json as get_json  # fail-closed fetcher

    from services.ttl_cache import cached
    key = f"ybars:{ysym}:{iv}:{rng}"

    def _run() -> dict:
        d = get_json(_YAHOO.format(sym=ysym, rng=rng, iv=iv))
        bars = _to_bars(d) if d else None
        return {"bars": bars} if bars else {"available": False}

    out = cached(key, 300.0, _run)
    bars = out.get("bars")
    if not bars:
        return None
    # Fold AFTER the cache, so 1h / 2h / 4h all share one upstream request.
    # Trim after folding — `n` is a count of the bars the caller asked for, not
    # of the raw ones they were built from.
    bars = _fold(bars, fold)
    return bars[-n:] if bars else None
