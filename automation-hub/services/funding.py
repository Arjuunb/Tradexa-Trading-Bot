"""Funding-rate awareness (perpetual futures).

Perps charge/pay funding every 8h; extreme rates mean a crowded side and
squeeze risk, and holding against heavy funding silently bleeds P&L. This
module fetches live rates from the derivatives venue and interprets them.
Spot symbols have no funding — that is reported honestly, never faked.

``interpret`` is pure (unit-tested); ``funding_rates`` does the network fetch
via ccxt's binanceusdm and returns {"available": False} when ccxt/network is
missing.
"""
from __future__ import annotations

from typing import Optional

# Binance funding is exchanged every 8 hours; ±0.01% is the neutral baseline.
EXTREME_8H = 0.0005     # 0.05% per 8h — historically "very crowded"
ELEVATED_8H = 0.0002    # 0.02% per 8h


def interpret(rate_8h: Optional[float]) -> dict:
    """Pure: classify one 8h funding rate into signal + guidance."""
    if rate_8h is None:
        return {"level": "unknown", "note": "no funding data"}
    apr = rate_8h * 3 * 365 * 100          # 3 windows/day -> annualized %
    if rate_8h >= EXTREME_8H:
        return {"level": "extreme-long", "annualized_pct": round(apr, 1),
                "note": "Longs pay heavily — crowded long side, squeeze risk; shorts get paid to wait."}
    if rate_8h >= ELEVATED_8H:
        return {"level": "elevated-long", "annualized_pct": round(apr, 1),
                "note": "Longs pay above baseline — bullish positioning is stretched."}
    if rate_8h <= -EXTREME_8H:
        return {"level": "extreme-short", "annualized_pct": round(apr, 1),
                "note": "Shorts pay heavily — crowded short side, squeeze risk; longs get paid to hold."}
    if rate_8h <= -ELEVATED_8H:
        return {"level": "elevated-short", "annualized_pct": round(apr, 1),
                "note": "Shorts pay above baseline — bearish positioning is stretched."}
    return {"level": "neutral", "annualized_pct": round(apr, 1),
            "note": "Funding near baseline — positioning is balanced."}


def _to_perp(symbol: str) -> str:
    s = symbol.upper().replace("/", "").replace("-", "")
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if s.endswith(quote):
            return f"{s[:-len(quote)]}/{quote}:{quote}"
    return symbol


def funding_rates(symbols: list[str], exchange: str = "binanceusdm") -> dict:
    """Live funding for the given symbols from the perp venue. Missing ccxt or
    network -> {"available": False, "reason": ...} — no fabricated numbers."""
    try:
        import ccxt
    except Exception:  # noqa: BLE001
        return {"available": False, "reason": "ccxt not installed", "rates": []}
    try:
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        out = []
        for sym in symbols:
            try:
                fr = ex.fetch_funding_rate(_to_perp(sym))
                rate = fr.get("fundingRate")
                out.append({"symbol": sym.upper(),
                            "rate_8h": rate,
                            "rate_8h_pct": round(rate * 100, 4) if rate is not None else None,
                            "next_funding_time": fr.get("fundingDatetime"),
                            **interpret(rate)})
            except Exception as e:  # noqa: BLE001
                out.append({"symbol": sym.upper(), "rate_8h": None,
                            "level": "unavailable", "note": str(e)})
        got = [r for r in out if r.get("rate_8h") is not None]
        return {"available": bool(got), "exchange": exchange, "rates": out,
                **({} if got else {"reason": "no funding data returned"})}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e), "rates": []}
