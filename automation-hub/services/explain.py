"""The Explainable Trading layer: one complete Decision Report per analysis
cycle — the bot NEVER trades or skips silently.

Every report contains the narrated market analysis, a rule-by-rule strategy
checklist (PASS / FAIL / N/A, each with an explanation), a five-category
confidence score out of 100, the decision (BUY / SELL / WAIT / SKIP) with its
reasons, and a concrete recommendation. All values are computed from real bars
and the engine's real gate outcomes — the report EXPLAINS the engine, it never
invents a parallel opinion.

Score categories (each /20, deterministic formulas):
  Trend       — EMA8/33 alignment (8) + strength (6) + swing agreement (6)
  Structure   — trending state (8) + BOS aligned (8) + no CHoCH against (4)
  Supply/Dem. — zone proximity (12) + structure-side agreement (8)
  Volume      — ratio vs 20-bar average, linear 0.6→1.4 mapped to 0→20
  Risk        — reward:risk vs minimum (12) + headroom to opposing level (8)
Total ≥ 80 = "strong", 65–79 = "watchlist", < 65 = "skip-quality".
"""
from __future__ import annotations

from typing import Optional

from services.market_analysis import analyze

MIN_RR = 2.0          # checklist minimum reward:risk (brain targets 3.0)
PASS, FAIL, NA = "PASS", "FAIL", "N/A"


def _rule(name: str, status: str, explanation: str) -> dict:
    return {"name": name, "status": status, "explanation": explanation}


def _clamp(x: float, lo: float = 0.0, hi: float = 20.0) -> float:
    return max(lo, min(hi, x))


# --------------------------------------------------------------- checklist
def build_checklist(ma: dict, side: Optional[str], signal, session: tuple,
                    weekday: int, hour: int) -> list[dict]:
    """Rule-by-rule evaluation. ``side`` None (no setup) marks direction-
    dependent rules N/A rather than guessing a direction."""
    rules: list[dict] = []
    if not ma.get("available"):
        return [_rule("Market analysis", NA, ma.get("note", "insufficient data"))]

    t = ma["trend"]
    up = side == "long"
    directional = side is not None

    # 1. EMA alignment
    if directional:
        aligned = (t["ema8_vs_ema33"] == "above") == up
        rules.append(_rule("EMA alignment", PASS if aligned else FAIL,
                           f"EMA8 {t['ema8_vs_ema33']} EMA33 for a {side} setup"))
    else:
        rules.append(_rule("EMA alignment", NA,
                           f"no setup direction — EMA8 is {t['ema8_vs_ema33']} EMA33"))

    # 2. Market structure confirmed
    st = ma["structure"]
    if directional:
        ok = st["state"] == ("trending up" if up else "trending down") or \
             st["break_of_structure"] == ("bullish" if up else "bearish")
        rules.append(_rule("Market structure confirmed", PASS if ok else FAIL,
                           f"{st['state']}; BOS {st['break_of_structure']}"))
    else:
        rules.append(_rule("Market structure confirmed", NA, f"state: {st['state']}"))

    # 3. Zone valid (demand for longs / supply for shorts)
    zone = ma["zones"]["demand" if up else "supply"] if directional else None
    if directional and isinstance(zone, dict):
        near = abs(zone["distance_pct"]) <= max(1.0, 2 * ma["atr_pct"])
        rules.append(_rule(f"{'Demand' if up else 'Supply'} zone valid",
                           PASS if near else FAIL,
                           f"zone {zone['low']}–{zone['high']} is "
                           f"{zone['distance_pct']}% away (near = within "
                           f"{max(1.0, 2 * ma['atr_pct']):.2f}%)"))
    elif directional:
        rules.append(_rule("Zone valid", NA, str(zone)))
    else:
        rules.append(_rule("Zone valid", NA, "no setup direction"))

    # 4. Rejection candle
    pat = ma["last_candle"]
    if directional:
        want = "bullish" if up else "bearish"
        has = isinstance(pat, str) and pat.startswith(want)
        rules.append(_rule(f"{want.capitalize()} rejection candle",
                           PASS if has else FAIL, f"last candle: {pat}"))
    else:
        rules.append(_rule("Rejection candle", NA, f"last candle: {pat}"))

    # 5. Reward:risk
    if signal is not None and signal.stop_loss and signal.take_profit:
        risk = abs(signal.entry - signal.stop_loss)
        rew = abs(signal.take_profit - signal.entry)
        rr = rew / risk if risk > 0 else 0.0
        rules.append(_rule(f"Risk:reward ≥ {MIN_RR}", PASS if rr >= MIN_RR else FAIL,
                           f"planned RR {rr:.2f}:1 (stop {signal.stop_loss}, "
                           f"target {signal.take_profit})"))
    else:
        rules.append(_rule(f"Risk:reward ≥ {MIN_RR}", NA, "no signal / no bracket"))

    # 6. No major opposing level ahead
    opp = ma["levels"]["nearest_resistance" if up else "nearest_support"] if directional else None
    if directional and signal is not None and signal.stop_loss:
        risk = abs(signal.entry - signal.stop_loss)
        if opp is None:
            rules.append(_rule("No major level ahead", PASS,
                               f"no {'resistance' if up else 'support'} on record above/below"))
        else:
            room = abs(opp["price"] - ma["price"])
            ok = opp["kind"] != "major" or room >= risk
            rules.append(_rule("No major level ahead", PASS if ok else FAIL,
                               f"{opp['kind']} level @ {opp['price']} is "
                               f"{room:.6g} away vs risk {risk:.6g}"))
    else:
        rules.append(_rule("No major level ahead", NA, "no setup direction / bracket"))

    # 7. Volume confirmation
    v = ma["volume"]
    if v["ratio_vs_20bar"] is None:
        rules.append(_rule("Volume confirmation", NA, "no volume data"))
    else:
        rules.append(_rule("Volume confirmation",
                           PASS if v["label"] != "below average" else FAIL,
                           f"{v['label']} (×{v['ratio_vs_20bar']} vs 20-bar avg)"))

    # 8. Session allowed
    start, end, mask = session
    day_ok = ((mask >> weekday) & 1) == 1
    hour_ok = start <= hour < end if start < end else True
    rules.append(_rule("Session allowed", PASS if (day_ok and hour_ok) else FAIL,
                       f"UTC hour {hour} in window {start}–{end}; weekday bit "
                       f"{'on' if day_ok else 'off'}"))
    return rules


# ------------------------------------------------------------------ scores
def build_scores(ma: dict, side: Optional[str], signal, verdict) -> dict:
    if not ma.get("available"):
        return {"available": False, "total": 0, "label": "no-data"}
    t, st = ma["trend"], ma["structure"]
    up = side == "long"
    directional = side is not None

    # Trend /20
    s_align = 8.0 if not directional else (8.0 if (t["ema8_vs_ema33"] == "above") == up else 0.0)
    s_strength = _clamp(t["strength"] * 6.0, 0, 6)
    swings_agree = (t["swing_highs"] == "Higher High") == (up if directional else t["ema8_vs_ema33"] == "above")
    s_swings = 6.0 if swings_agree else 0.0
    trend_score = _clamp(s_align + s_strength + s_swings)

    # Structure /20
    trending = st["state"].startswith("trending")
    bos_aligned = (not directional and st["break_of_structure"] != "none") or \
                  (directional and st["break_of_structure"] == ("bullish" if up else "bearish"))
    structure_score = _clamp((8.0 if trending else 0.0)
                             + (8.0 if bos_aligned else 0.0)
                             + (0.0 if st["change_of_character"] else 4.0))

    # Supply/Demand /20 — proximity to the entry-side zone
    zone = ma["zones"]["demand" if (up or not directional) else "supply"]
    if isinstance(zone, dict):
        near_lim = max(1.0, 2 * ma["atr_pct"])
        prox = _clamp(12.0 * (1 - min(abs(zone["distance_pct"]) / (2 * near_lim), 1.0)), 0, 12)
    else:
        prox = 0.0
    sd_score = _clamp(prox + (8.0 if bos_aligned or trending else 0.0))

    # Volume /20 — ×0.6 → 0 pts, ×1.4 → 20 pts (linear)
    ratio = ma["volume"]["ratio_vs_20bar"]
    volume_score = 10.0 if ratio is None else _clamp((ratio - 0.6) / 0.8 * 20.0)

    # Risk /20
    if signal is not None and signal.stop_loss and signal.take_profit:
        risk = abs(signal.entry - signal.stop_loss)
        rr = abs(signal.take_profit - signal.entry) / risk if risk > 0 else 0.0
        s_rr = _clamp(rr / 3.0 * 12.0, 0, 12)
        opp = ma["levels"]["nearest_resistance" if up else "nearest_support"]
        room_ok = opp is None or abs(opp["price"] - ma["price"]) >= risk
        risk_score = _clamp(s_rr + (8.0 if room_ok else 0.0))
    else:
        risk_score = 0.0 if directional else 10.0   # neutral when nothing is proposed

    total = round(trend_score + structure_score + sd_score + volume_score + risk_score)
    label = "strong" if total >= 80 else "watchlist" if total >= 65 else "skip-quality"
    return {
        "available": True,
        "trend": round(trend_score), "structure": round(structure_score),
        "supply_demand": round(sd_score), "volume": round(volume_score),
        "risk": round(risk_score), "total": total, "label": label,
        "engine_score": (verdict.score if verdict is not None else None),
        "note": "categories are deterministic reads of the analysis above; "
                "'engine_score' is the Decision Brain's own 0–100 gate",
    }


# --------------------------------------------------------- recommendation
def _recommend(decision: str, checklist: list[dict], ma: dict) -> str:
    fails = [r for r in checklist if r["status"] == FAIL]
    if decision in ("BUY", "SELL"):
        return "Trade placed — manage per plan; the stop and target do the work."
    if not ma.get("available"):
        return "Let more candles accumulate before judging this market."
    for r in fails:
        if "Risk:reward" in r["name"]:
            return "Wait for a pullback toward the zone — a closer entry improves the RR."
        if "level ahead" in r["name"]:
            return "Wait for a break and retest of the level ahead before committing."
        if "Volume" in r["name"]:
            return "Wait for volume to confirm before trusting this move."
        if "structure" in r["name"].lower():
            return "Stand aside until structure resolves (a clean BOS in one direction)."
        if "Session" in r["name"]:
            return "Outside the configured trading window — the engine resumes in-session."
    if ma["bias"] == "Neutral":
        return "No edge while bias is neutral — wait for the market to pick a side."
    return f"Bias is {ma['bias'].lower()} — wait for a qualifying setup in that direction."


# ------------------------------------------------------------- the report
def build_cycle_report(*, symbol: str, timeframe: str, bars, signal, outcome,
                       position, session: tuple) -> dict:
    """One complete Decision Report for one closed candle of one symbol."""
    ma = analyze(bars)
    ts = bars[-1].timestamp
    side = None
    if signal is not None:
        side = "long" if signal.type.name == "LONG" else "short"
    elif position is not None:
        side = position.get("side")

    checklist = build_checklist(ma, side, signal, session,
                                weekday=ts.weekday(), hour=ts.hour)
    verdict = (outcome or {}).get("verdict")
    scores = build_scores(ma, side, signal, verdict)

    kind = (outcome or {}).get("kind")
    reasons: list[str] = []
    if signal is None:
        if position is not None:
            decision = "WAIT"
            reasons.append(f"Holding an open {position['side']} position — "
                           "no new signal this candle; exits are managed by stop/target.")
        else:
            decision = "WAIT"
            reasons.append("No qualifying setup this candle — the strategy's "
                           "conviction threshold was not met.")
            if ma.get("available"):
                reasons.append(f"Bias {ma['bias']}; structure {ma['structure']['state']}; "
                               f"volume {ma['volume']['label']}.")
    elif kind == "hold":
        decision = "WAIT"
        reasons.append(f"Signal re-affirms the open {side} position — no action needed.")
    elif kind in ("opened", "pending"):
        decision = "BUY" if side == "long" else "SELL"
        reasons.append(getattr(signal, "reason", "") or "Strategy signal fired.")
        if kind == "pending":
            reasons.append("Resting limit order placed at the signal price "
                           "(maker entry) — fills if price trades through it.")
        d = (outcome or {}).get("decision") or {}
        if d.get("reason"):
            reasons.append(f"Quality gate: {d['reason']}")
    elif kind == "closed":
        decision = "SELL" if side == "long" else "BUY"
        reasons.append("Opposite signal — closed the open position "
                       "(the engine never holds against its own view).")
    elif kind == "rejected":
        decision = "SKIP"
        stage = (outcome or {}).get("stage", "gate")
        reasons.append(f"Blocked at the {stage} gate: {(outcome or {}).get('reason', '')}")
        d = (outcome or {}).get("decision") or {}
        for f in (d.get("failed_rules") or [])[:4]:
            reasons.append(f"❌ {f}")
    else:
        decision = "SKIP"
        reasons.append((outcome or {}).get("reason") or "Signal did not result in a trade.")

    return {
        "ts": ts.isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "price": ma.get("price") if ma.get("available") else (bars[-1].close if bars else None),
        "decision": decision,
        "side": side,
        "score": scores.get("total", 0),
        "market_analysis": ma,
        "checklist": checklist,
        "scores": scores,
        "reasons": [r for r in reasons if r],
        "recommendation": _recommend(decision, checklist, ma),
        "links": {
            "decision_id": ((outcome or {}).get("decision") or {}).get("id"),
            "signal_confidence": getattr(signal, "confidence", None) if signal else None,
        },
    }
