"""Market Awareness + Sentiment engine.

Pulls real-world market context from OFFICIAL, public, no-auth APIs and labels
the market mood. Used only as a FILTER on trade confidence — never as the sole
reason to trade. Every fetch fails closed: if the network/API is unavailable it
returns ``available=False`` rather than fabricating a value (no fake sentiment).

Sources used (free, legal, no scraping):
    * Crypto Fear & Greed Index   — api.alternative.me/fng
    * Global crypto stats         — api.coingecko.com/api/v3/global
Social sources (X/Twitter, Reddit) are only attempted when API credentials are
present in the environment; otherwise they are reported as "not configured".
We never scrape private/restricted platforms.
"""
from __future__ import annotations

import os
from typing import Optional

_TIMEOUT = 4


def _get_json(url: str):
    try:
        import requests
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "automation-hub/1.0"})
        r.raise_for_status()
        return r.json()
    except Exception:  # noqa: BLE001 — any failure -> None (fail closed, never fake)
        return None


def fetch_fear_greed() -> Optional[dict]:
    """Crypto Fear & Greed Index (0..100). None if unavailable."""
    data = _get_json("https://api.alternative.me/fng/?limit=1")
    try:
        d = data["data"][0]
        return {"value": int(d["value"]), "classification": d.get("value_classification", "")}
    except Exception:  # noqa: BLE001
        return None


def fetch_global() -> Optional[dict]:
    """BTC dominance + total market cap. Tries CoinGecko, then CoinPaprika,
    then Coinlore — all free and keyless. The chain matters because each one
    rate-limits or blocks cloud-host IPs at different times; one of the three
    is almost always reachable. None only when ALL are down (never fake)."""
    data = _get_json("https://api.coingecko.com/api/v3/global")
    try:
        d = data["data"]
        return {"btc_dominance": round(d["market_cap_percentage"]["btc"], 1),
                "total_mcap_usd": round(d["total_market_cap"]["usd"], 0),
                "source": "coingecko"}
    except Exception:  # noqa: BLE001
        pass
    data = _get_json("https://api.coinpaprika.com/v1/global")
    try:
        return {"btc_dominance": round(float(data["bitcoin_dominance_percentage"]), 1),
                "total_mcap_usd": round(float(data["market_cap_usd"]), 0),
                "source": "coinpaprika"}
    except Exception:  # noqa: BLE001
        pass
    data = _get_json("https://api.coinlore.net/api/global/")
    try:
        g = data[0]
        return {"btc_dominance": round(float(g["btc_d"]), 1),
                "total_mcap_usd": round(float(g["total_mcap"]), 0),
                "source": "coinlore"}
    except Exception:  # noqa: BLE001
        return None


def label_mood(fg_value: int) -> str:
    """Map a 0..100 Fear & Greed value to a mood label."""
    if fg_value <= 10:
        return "Panic"
    if fg_value <= 25:
        return "Extreme Fear"
    if fg_value <= 45:
        return "Fear"
    if fg_value <= 55:
        return "Neutral"
    if fg_value <= 74:
        return "Greed"
    if fg_value <= 89:
        return "Extreme Greed"
    return "Euphoria"


def risk_mode(mood: str) -> str:
    """How the bot should size/filter given the mood (advisory only)."""
    return {
        "Panic": "Defensive — fade extremes only, reduce size",
        "Extreme Fear": "Cautious — contrarian longs favoured, reduce size",
        "Fear": "Normal — slight long bias",
        "Neutral": "Normal",
        "Greed": "Normal — slight caution on new longs",
        "Extreme Greed": "Cautious — reduce long confidence (overextension risk)",
        "Euphoria": "Defensive — avoid chasing longs, reduce size",
    }.get(mood, "Normal")


def confidence_filter(mood: str) -> dict:
    """Multipliers applied to trade confidence by side. 1.0 = unchanged.
    Sentiment trims confidence at extremes; it never forces a trade."""
    if mood in ("Extreme Greed", "Euphoria"):
        return {"long": 0.7, "short": 1.0, "note": "Overextended greed — long confidence reduced."}
    if mood in ("Extreme Fear", "Panic"):
        return {"long": 1.0, "short": 0.7, "note": "Extreme fear — short confidence reduced (snap-back risk)."}
    return {"long": 1.0, "short": 1.0, "note": "Sentiment neutral — no confidence adjustment."}


def _social_status() -> dict:
    """Report social-API availability honestly (only if creds are configured)."""
    return {
        "x_twitter": "configured" if os.environ.get("TWITTER_BEARER_TOKEN") else "not configured",
        "reddit": "configured" if os.environ.get("REDDIT_CLIENT_ID") else "not configured",
        "note": "Social sentiment requires official API credentials; no scraping is performed.",
    }


def market_sentiment() -> dict:
    """Aggregate market mood. Always returns a dict; ``available`` reflects whether
    any real source responded (never fabricated)."""
    fg = fetch_fear_greed()
    glob = fetch_global()
    if fg is None:
        return {
            "available": False,
            "note": "Live sentiment sources unavailable (no network/API). Not faking a value.",
            "mood": None, "risk_mode": "Normal", "fear_greed": None,
            "confidence": {"long": 1.0, "short": 1.0, "note": "sentiment unavailable"},
            "btc_dominance": (glob or {}).get("btc_dominance"),
            "total_mcap_usd": (glob or {}).get("total_mcap_usd"),
            "social": _social_status(),
        }
    mood = label_mood(fg["value"])
    return {
        "available": True,
        "fear_greed": fg["value"],
        "fear_greed_label": fg["classification"],
        "mood": mood,
        "risk_mode": risk_mode(mood),
        "confidence": confidence_filter(mood),
        "btc_dominance": (glob or {}).get("btc_dominance"),
        "total_mcap_usd": (glob or {}).get("total_mcap_usd"),
        "social": _social_status(),
        "note": "Sentiment is a filter on confidence, not a trade trigger.",
    }
