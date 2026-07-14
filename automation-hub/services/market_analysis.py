"""Narrated market analysis for the Explainable Trading layer.

Pure, deterministic reads computed from the engine's own bar history — the
"what does the market look like" half of every cycle's Decision Report. Every
field is either computed from real bars or honestly reported as unavailable
("insufficient data") — nothing is ever guessed.

Definitions (stated so the numbers are auditable):
- Pivots: swing high/low with ``k`` bars on each side strictly lower/higher.
- HH/HL etc.: comparison of the last two pivot highs / last two pivot lows.
- BOS: latest close beyond the most recent pivot high (bull) / low (bear).
- CHoCH: a BOS against the direction of the previous structure label.
- S/R levels: pivot prices clustered within 0.3×ATR; strength = touch count;
  "major" = 2+ touches, otherwise "minor".
- Demand/Supply zone: a band around the most recent pivot low/high, half an
  ATR deep. Distance is measured from the current close, in %.
- Equal highs/lows: two pivot highs/lows within 0.15×ATR of each other.
- Liquidity sweep: within the last 5 bars, a wick trades through an equal-
  high/low level but the bar closes back on the other side.
- Volume: last bar vs its 20-bar average (±10% band = "average").
- Volatility: ATR as % of price — <0.6% low, <1.6% medium, else high.
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import atr, ema


def _pivots(bars, k: int = 3) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """(pivot_highs, pivot_lows) as (index, price), oldest first."""
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for i in range(k, len(bars) - k):
        h = bars[i].high
        l = bars[i].low
        if all(bars[j].high < h for j in range(i - k, i + k + 1) if j != i):
            highs.append((i, h))
        if all(bars[j].low > l for j in range(i - k, i + k + 1) if j != i):
            lows.append((i, l))
    return highs, lows


def _swing_labels(ph: list[tuple[int, float]], pl: list[tuple[int, float]]) -> dict:
    """HH/LH from the last two pivot highs; HL/LL from the last two lows."""
    out = {"highs": None, "lows": None}
    if len(ph) >= 2:
        out["highs"] = "Higher High" if ph[-1][1] > ph[-2][1] else "Lower High"
    if len(pl) >= 2:
        out["lows"] = "Higher Low" if pl[-1][1] > pl[-2][1] else "Lower Low"
    return out


def _cluster_levels(levels: list[float], tol: float) -> list[dict]:
    """Cluster nearby pivot prices into S/R levels with touch counts."""
    out: list[dict] = []
    for price in sorted(levels):
        if out and abs(price - out[-1]["price"]) <= tol:
            n = out[-1]["touches"] + 1
            out[-1]["price"] = (out[-1]["price"] * out[-1]["touches"] + price) / n
            out[-1]["touches"] = n
        else:
            out.append({"price": price, "touches": 1})
    for lv in out:
        lv["price"] = round(lv["price"], 6)
        lv["kind"] = "major" if lv["touches"] >= 2 else "minor"
    return out


def _candle_pattern(bars) -> Optional[str]:
    """Simple, honest last-candle read: engulfing or pin bar, else None."""
    if len(bars) < 2:
        return None
    a, b = bars[-2], bars[-1]
    body = abs(b.close - b.open)
    rng = max(b.high - b.low, 1e-12)
    up_wick = b.high - max(b.open, b.close)
    dn_wick = min(b.open, b.close) - b.low
    if b.close > b.open and a.close < a.open and b.close >= a.open and b.open <= a.close:
        return "bullish engulfing"
    if b.close < b.open and a.close > a.open and b.close <= a.open and b.open >= a.close:
        return "bearish engulfing"
    if body / rng < 0.35 and dn_wick >= 2 * body and dn_wick > up_wick:
        return "bullish pin (long lower wick)"
    if body / rng < 0.35 and up_wick >= 2 * body and up_wick > dn_wick:
        return "bearish pin (long upper wick)"
    return None


def analyze(bars) -> dict:
    """Full narrated analysis of one symbol's bar history. Needs ≥ 40 bars for
    every read; below that each section states what's missing."""
    n = len(bars)
    if n < 40:
        return {"available": False,
                "note": f"insufficient history ({n} bars; need ≥ 40 for honest reads)"}

    closes = [b.close for b in bars]
    price = closes[-1]
    a = atr(bars, 14)
    atr_pct = (a / price * 100) if price else 0.0

    e8 = ema(closes, 8)[-1]
    e33 = ema(closes, 33)[-1]
    # trend strength: normalised EMA separation (1.0 ≈ separation of 1 ATR)
    strength = abs(e8 - e33) / a if a > 0 else 0.0
    strength_label = "strong" if strength >= 1.0 else "moderate" if strength >= 0.4 else "weak"

    ph, pl = _pivots(bars, k=3)
    swings = _swing_labels(ph, pl)

    # ---- structure ---------------------------------------------------------
    bos = None
    if ph and price > ph[-1][1]:
        bos = "bullish"
    elif pl and price < pl[-1][1]:
        bos = "bearish"
    up_swings = swings["highs"] == "Higher High" and swings["lows"] == "Higher Low"
    dn_swings = swings["highs"] == "Lower High" and swings["lows"] == "Lower Low"
    prior = "up" if up_swings else "down" if dn_swings else None
    choch = (bos == "bearish" and prior == "up") or (bos == "bullish" and prior == "down")
    recent_range = (max(b.high for b in bars[-20:]) - min(b.low for b in bars[-20:]))
    consolidating = a > 0 and recent_range < 3.0 * a and strength < 0.4
    structure_state = ("consolidation" if consolidating
                       else "trending up" if (up_swings or bos == "bullish")
                       else "trending down" if (dn_swings or bos == "bearish")
                       else "transitional")

    # ---- bias (majority of three honest votes) -----------------------------
    votes = [1 if e8 > e33 else -1,
             1 if price > e33 else -1,
             1 if up_swings else -1 if dn_swings else 0]
    total = sum(votes)
    bias = "Bullish" if total >= 2 else "Bearish" if total <= -2 else "Neutral"

    # ---- supply / demand zones ---------------------------------------------
    demand = supply = None
    if pl:
        lo = pl[-1][1]
        demand = {"low": round(lo, 6), "high": round(lo + 0.5 * a, 6),
                  "distance_pct": round((price - lo) / price * 100, 3)}
    if ph:
        hi = ph[-1][1]
        supply = {"low": round(hi - 0.5 * a, 6), "high": round(hi, 6),
                  "distance_pct": round((hi - price) / price * 100, 3)}

    # ---- support / resistance ----------------------------------------------
    levels = _cluster_levels([p for _, p in ph] + [p for _, p in pl], tol=0.3 * a)
    supports = [lv for lv in levels if lv["price"] < price][-3:]
    resistances = [lv for lv in levels if lv["price"] > price][:3]
    nearest_res = resistances[0] if resistances else None
    nearest_sup = supports[-1] if supports else None

    # ---- volume -------------------------------------------------------------
    vols = [b.volume for b in bars[-21:-1]]
    avg_vol = sum(vols) / len(vols) if vols else 0.0
    v_ratio = (bars[-1].volume / avg_vol) if avg_vol > 0 else None
    volume_label = (None if v_ratio is None
                    else "above average" if v_ratio > 1.1
                    else "below average" if v_ratio < 0.9 else "average")

    # ---- volatility ----------------------------------------------------------
    vol_label = "low" if atr_pct < 0.6 else "medium" if atr_pct < 1.6 else "high"

    # ---- liquidity -----------------------------------------------------------
    eq_tol = 0.15 * a
    eq_highs = [round((x + y) / 2, 6) for (_, x), (_, y) in zip(ph, ph[1:]) if abs(x - y) <= eq_tol]
    eq_lows = [round((x + y) / 2, 6) for (_, x), (_, y) in zip(pl, pl[1:]) if abs(x - y) <= eq_tol]
    sweep = None
    for b in bars[-5:]:
        for lvl in eq_highs[-2:]:
            if b.high > lvl and b.close < lvl:
                sweep = f"swept equal highs @ {lvl} (wick above, close back below)"
        for lvl in eq_lows[-2:]:
            if b.low < lvl and b.close > lvl:
                sweep = f"swept equal lows @ {lvl} (wick below, close back above)"

    return {
        "available": True,
        "price": round(price, 6),
        "atr": round(a, 6),
        "atr_pct": round(atr_pct, 3),
        "bias": bias,
        "trend": {
            "ema8": round(e8, 6), "ema33": round(e33, 6),
            "ema8_vs_ema33": "above" if e8 > e33 else "below",
            "price_vs_ema33": "above" if price > e33 else "below",
            "strength": round(strength, 2), "strength_label": strength_label,
            "swing_highs": swings["highs"] or "insufficient pivots",
            "swing_lows": swings["lows"] or "insufficient pivots",
        },
        "structure": {
            "state": structure_state,
            "break_of_structure": bos or "none",
            "change_of_character": bool(choch),
        },
        "zones": {
            "demand": demand or "no pivot low found",
            "supply": supply or "no pivot high found",
        },
        "levels": {
            "supports": supports, "resistances": resistances,
            "nearest_support": nearest_sup, "nearest_resistance": nearest_res,
        },
        "volume": {"label": volume_label or "no volume data",
                   "ratio_vs_20bar": round(v_ratio, 2) if v_ratio is not None else None},
        "volatility": {"label": vol_label, "atr_pct": round(atr_pct, 3)},
        "liquidity": {
            "equal_highs": eq_highs[-3:], "equal_lows": eq_lows[-3:],
            "sweep": sweep or "none detected",
        },
        "last_candle": _candle_pattern(bars) or "no notable pattern",
    }
