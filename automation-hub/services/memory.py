"""Market Memory (#12) + Strategy DNA (#13).

The bot remembers, per strategy, the conditions where it performs best and worst
— best/worst regime, session and symbol — by mining REAL replay results. That
memory becomes a DNA profile (preferred market / volatility / session / trend /
symbols) and a live filter so a strategy isn't forced into markets it's bad at.

Builds on services.backtest_lab.sliced_performance (regime/session/symbol
buckets). Pure aside from that real-data load.
"""
from __future__ import annotations

# regime -> coarse volatility + trend descriptors for the DNA card
_VOL = {"High volatility": "high", "Extreme Volatility": "high", "Low volatility": "low",
        "Bull trend": "normal", "Bear trend": "normal", "Range": "low", "Choppy market": "high",
        "Trending": "normal", "Ranging": "low"}
_TREND = {"Bull trend": "uptrend", "Bear trend": "downtrend", "Trending": "trending",
          "Range": "ranging", "Ranging": "ranging", "Choppy market": "choppy"}
_MIN = 3   # minimum trades in a bucket to trust it


def _best_worst(buckets, key="key"):
    good = [b for b in buckets if b["trades"] >= _MIN]
    if not good:
        return None, None
    best = max(good, key=lambda b: b["net_r"])
    worst = min(good, key=lambda b: b["net_r"])
    return best, worst


def build_memory(strategy: str, timeframe: str = "15m", *,
                 symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"), limit: int = 800,
                 sliced=None) -> dict:
    """Mine real results into a memory + DNA profile for one strategy."""
    if sliced is None:
        from services.backtest_lab import sliced_performance
        sliced = sliced_performance(strategy, timeframe, symbols=symbols, limit=limit)

    reg_best, reg_worst = _best_worst(sliced["by_regime"])
    ses_best, ses_worst = _best_worst(sliced["by_session"])
    sym_best, sym_worst = _best_worst(sliced["by_symbol"])

    # preferred symbols = positive-expectancy symbols with enough trades
    pref_symbols = [b["key"] for b in sliced["by_symbol"] if b["trades"] >= _MIN and b["net_r"] > 0]
    avoid_symbols = [b["key"] for b in sliced["by_symbol"] if b["trades"] >= _MIN and b["net_r"] < 0]

    reg = reg_best["key"] if reg_best else None
    dna = {
        "preferred_market": reg or "—",
        "preferred_volatility": _VOL.get(reg, "any") if reg else "any",
        "preferred_trend": _TREND.get(reg, "any") if reg else "any",
        "preferred_session": ses_best["key"] if ses_best else "any",
        "preferred_symbols": pref_symbols,
        "avoid_symbols": avoid_symbols,
    }
    sample = sliced["total_trades"]
    return {
        "strategy": strategy, "timeframe": timeframe, "sample": sample,
        "confidence": "high" if sample >= 40 else "medium" if sample >= 15 else "low",
        "memory": {
            "best_regime": reg_best, "worst_regime": reg_worst,
            "best_session": ses_best, "worst_session": ses_worst,
            "best_symbol": sym_best, "worst_symbol": sym_worst,
        },
        "dna": dna,
        "by_regime": sliced["by_regime"], "by_session": sliced["by_session"],
        "by_symbol": sliced["by_symbol"],
    }


def dna_match(dna: dict, context: dict) -> dict:
    """Score how well the current context fits a strategy's DNA and recommend
    whether to trade it here (a live filter built from memory)."""
    reasons, score = [], 0
    sym = (context.get("symbol") or "").upper()
    reg = context.get("market_regime") or context.get("regime")
    ses = context.get("session")

    if sym:
        if sym in (dna.get("avoid_symbols") or []):
            score -= 40
            reasons.append(f"{sym} is a weak symbol for this strategy")
        elif sym in (dna.get("preferred_symbols") or []):
            score += 30
            reasons.append(f"{sym} is a preferred symbol")
    if reg and dna.get("preferred_market") not in ("—", None):
        if reg == dna["preferred_market"]:
            score += 35
            reasons.append(f"{reg} is the strategy's best regime")
        else:
            score -= 10
            reasons.append(f"current regime {reg} is not its best ({dna['preferred_market']})")
    if ses and dna.get("preferred_session") not in ("any", None):
        if ses == dna["preferred_session"]:
            score += 20
            reasons.append(f"{ses} session is preferred")
        else:
            score -= 8
    verdict = "favorable" if score >= 25 else "unfavorable" if score <= -25 else "neutral"
    return {"fit_score": max(-100, min(100, score)), "verdict": verdict,
            "trade_here": score > -25, "reasons": reasons}
