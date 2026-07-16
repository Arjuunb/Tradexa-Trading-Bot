"""AI Trading Intelligence — the on-demand decision layer.

This does NOT replace any trading logic. It COMPOSES the engine's existing
intelligence into one pre-trade verdict you can request for any symbol at any
time (the engine already runs the same reads per candle inside auto_engine;
this exposes them on demand):

    market_analysis.analyze   → trend / structure / BOS / CHoCH / order-blocks
                                 (supply-demand) / S&R / EMA / volume / volatility
                                 / liquidity sweeps  (the full pre-trade read)
    explain.build_scores      → the five-category /100 setup score
    explain.build_checklist   → the PASS / FAIL / N/A rule-by-rule explanation
    strategies.brain.TradeBrain → the 0–100 quality gate + hard blocks
    risk.position_sizing      → position size, and from it the risk analysis

On top it adds the two things that were missing: a human **confidence level**
(Very High … Very Low) and a full **risk analysis** (max loss, expected profit,
risk %, reward:risk, exposure, and — when leverage is supplied — margin and
liquidation price). Pure and testable; the router fetches the bars.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional, Sequence

from database.models import RiskRules
from risk.position_sizing import size_position
from services import market_analysis
from services.explain import FAIL, PASS, build_checklist, build_scores, _recommend

# score → human confidence level (the spec's five bands)
_CONF_BANDS = [(85, "Very High"), (70, "High"), (55, "Medium"), (40, "Low"), (0, "Very Low")]
# maintenance-margin rate used for the (approximate) isolated liquidation price
_MAINT_MARGIN = 0.005


def confidence_level(score: float) -> str:
    for threshold, label in _CONF_BANDS:
        if score >= threshold:
            return label
    return "Very Low"


def _bucket_name(b) -> str:
    if isinstance(b, dict):
        return str(b.get("name") or b.get("key") or b.get("label") or b.get("session") or b.get("symbol") or "?")
    return str(b)


def trader_profile(insights: dict) -> dict:
    """Distil a personal trading profile (strengths / weaknesses) from the
    existing trade-memory insights — reuses the pattern-recognition output, does
    not recompute it. Honest: says so when the sample is too small."""
    ins = insights or {}
    sample = ins.get("sample") or (ins.get("overall") or {}).get("trades") or 0
    strengths: list[str] = []
    weaknesses: list[str] = []

    def _exp(b):
        return (b or {}).get("expectancy", 0.0) if isinstance(b, dict) else 0.0

    bs, ws = ins.get("best_session"), ins.get("worst_session")
    if isinstance(bs, dict) and _exp(bs) > 0:
        strengths.append(f"Best in the {_bucket_name(bs)} session (+{_exp(bs):.2f}R expectancy).")
    if isinstance(ws, dict) and _exp(ws) < 0:
        weaknesses.append(f"Loses in the {_bucket_name(ws)} session ({_exp(ws):.2f}R expectancy).")

    for b in (ins.get("by_symbol") or [])[:1]:
        if _exp(b) > 0:
            strengths.append(f"{_bucket_name(b)} is your strongest symbol (+{_exp(b):.2f}R).")
    for b in reversed(ins.get("by_symbol") or []):
        if _exp(b) < 0:
            weaknesses.append(f"{_bucket_name(b)} is a losing symbol ({_exp(b):.2f}R).")
            break
    for b in (ins.get("by_strategy") or [])[:1]:
        if _exp(b) > 0:
            strengths.append(f"Most profitable strategy: {_bucket_name(b)} (+{_exp(b):.2f}R).")
    for pat in (ins.get("winning_patterns") or [])[:2]:
        strengths.append(f"Repeatable edge: {_bucket_name(pat)}.")
    for m in (ins.get("mistakes") or [])[:3]:
        name = m.get("mistake") or m.get("pattern") or _bucket_name(m) if isinstance(m, dict) else str(m)
        cnt = m.get("count") if isinstance(m, dict) else None
        weaknesses.append(f"Repeated mistake: {name}" + (f" (×{cnt})" if cnt else ""))

    return {
        "sample": sample,
        "ready": sample >= 10,
        "strengths": strengths or (["Clean, disciplined reads so far — keep the sample growing."]
                                   if sample else []),
        "weaknesses": weaknesses,
        "avg_hold_seconds": ins.get("avg_hold_seconds"),
        "sharpe_ratio": ins.get("sharpe_ratio"),
        "win_rate": (ins.get("overall") or {}).get("win_rate"),
        "expectancy_r": (ins.get("overall") or {}).get("expectancy_r") or (ins.get("overall") or {}).get("expectancy"),
        "note": ("Profile updates automatically as trades close."
                 if sample >= 10 else
                 f"Only {sample} closed trades — the profile firms up past ~10."),
    }


def _liquidation_price(side: str, entry: float, leverage: float) -> Optional[float]:
    """Approximate isolated-margin liquidation price. None below 1x (spot)."""
    if not leverage or leverage <= 1 or not entry:
        return None
    if side == "long":
        return round(entry * (1 - 1 / leverage + _MAINT_MARGIN), 8)
    return round(entry * (1 + 1 / leverage - _MAINT_MARGIN), 8)


def _risk_analysis(*, side: str, entry: float, stop: float, target: float,
                   equity: float, risk_pct: float, leverage: float) -> dict:
    """Concrete pre-trade risk numbers for the proposed setup."""
    risk_per_unit = abs(entry - stop)
    reward_per_unit = abs(target - entry)
    size = size_position(equity, entry, stop, RiskRules(risk_per_trade_pct=risk_pct))
    notional = size * entry
    max_loss = size * risk_per_unit
    expected_profit = size * reward_per_unit
    rr = (reward_per_unit / risk_per_unit) if risk_per_unit > 0 else 0.0
    lev = max(1.0, float(leverage or 1.0))
    realized_risk_pct = (max_loss / equity * 100) if equity else 0.0
    exposure_pct = (notional / equity * 100) if equity else 0.0
    # excessive if the CONFIGURED per-trade risk is unsane (>5%), the REALIZED
    # loss would exceed 5% of equity, or exposure runs past 1x the account.
    excessive = risk_pct > 0.05 or realized_risk_pct > 5.0 or exposure_pct > 100.0
    warning = None
    if risk_pct > 0.05:
        warning = f"Per-trade risk is set to {risk_pct * 100:.0f}% — well above a safe 1–2%."
    elif realized_risk_pct > 5.0:
        warning = f"This trade risks {realized_risk_pct:.1f}% of the account in one position."
    elif exposure_pct > 100.0:
        warning = f"Exposure is {exposure_pct:.0f}% of equity — reduce size or leverage."
    return {
        "position_size": round(size, 8),
        "notional": round(notional, 2),
        "max_loss": round(max_loss, 2),
        "expected_profit": round(expected_profit, 2),
        "risk_pct": round((max_loss / equity * 100) if equity else 0.0, 3),
        "risk_reward": round(rr, 2),
        "margin_used": round(notional / lev, 2),
        "leverage": lev,
        "liquidation_price": _liquidation_price(side, entry, lev),
        "portfolio_exposure_pct": round(exposure_pct, 2),
        "excessive": bool(excessive),
        "warning": warning,
    }


def _proposed_side(ma: dict, requested: Optional[str]) -> Optional[str]:
    if requested in ("long", "short"):
        return requested
    if not ma.get("available"):
        return None
    bias = ma["bias"].lower()
    return "long" if bias == "bullish" else "short" if bias == "bearish" else None


def analyze_setup(*, symbol: str, timeframe: str, bars: Sequence, side: Optional[str] = None,
                  equity: float = 10_000.0, risk_pct: float = 0.01, min_score: int = 60,
                  leverage: float = 1.0, rr_target: float = 2.0, atr_mult: float = 1.5) -> dict:
    """Full on-demand AI pre-trade analysis for one symbol.

    Returns the market read, the five-category score, a confidence level, a
    BUY/SELL/WAIT/SKIP decision with reasons, and the risk analysis — all
    composed from the engine's existing intelligence (never a parallel opinion).
    """
    ma = market_analysis.analyze(bars)
    price = ma.get("price") if ma.get("available") else (bars[-1].close if bars else None)
    side = _proposed_side(ma, side)

    # Synthesize the candidate setup so the scorer / risk math have inputs: entry
    # at price, stop an ATR-multiple away, target at the configured reward:risk.
    atr = ma.get("atr") or (price * 0.01 if price else 0.0)
    risk_unit = max(atr * atr_mult, (price or 0) * 0.0008)
    entry = stop = target = None
    if side and price and risk_unit > 0:
        entry = price
        if side == "long":
            stop, target = price - risk_unit, price + rr_target * risk_unit
        else:
            stop, target = price + risk_unit, price - rr_target * risk_unit
    signal = SimpleNamespace(entry=entry, stop_loss=stop, take_profit=target) if entry else None

    # the Decision Brain's own 0–100 gate + hard blocks (parity with the engine)
    verdict = None
    if side and entry and len(bars) >= 60:
        try:
            from strategies.brain import TradeBrain
            verdict = TradeBrain().evaluate(bars, len(bars) - 1, side=side,
                                            entry=entry, stop=stop, target=target,
                                            reversal=False)
        except Exception:  # noqa: BLE001 — the brain must never break analysis
            verdict = None

    scores = build_scores(ma, side, signal, verdict)
    ts = bars[-1].timestamp if bars else None
    session = (0, 24, 0b1111111)                 # on-demand: analyse in any session (all hours/days)
    checklist = build_checklist(ma, side, signal, session,
                                weekday=ts.weekday() if ts else 0,
                                hour=ts.hour if ts else 12)

    total = scores.get("total", 0)
    level = confidence_level(total)
    blocked = verdict is not None and not verdict.allowed

    if not side or not ma.get("available"):
        decision = "WAIT"
    elif blocked or total < min_score:
        decision = "SKIP"
    else:
        decision = "BUY" if side == "long" else "SELL"

    risk = None
    if entry and stop and target:
        risk = _risk_analysis(side=side, entry=entry, stop=stop, target=target,
                              equity=equity, risk_pct=risk_pct, leverage=leverage)

    reasons = [r["explanation"] for r in checklist if r["status"] == PASS][:6]
    if blocked and verdict is not None:
        reasons = [f"Blocked: {b}" for b in verdict.blocks[:3]] or reasons
    fails = [r["name"] for r in checklist if r["status"] == FAIL]

    # map to the spec's five presentation categories (same underlying values)
    breakdown = [
        {"category": "Trend", "score": scores.get("trend", 0), "max": 20},
        {"category": "Market Structure", "score": scores.get("structure", 0), "max": 20},
        {"category": "Volume", "score": scores.get("volume", 0), "max": 20},
        {"category": "Risk Management", "score": scores.get("risk", 0), "max": 20},
        {"category": "Confirmation", "score": scores.get("supply_demand", 0), "max": 20},
    ] if scores.get("available") else []

    return {
        "symbol": symbol, "timeframe": timeframe,
        "ts": ts.isoformat() if ts else None,
        "price": price,
        "decision": decision, "side": side,
        "overall_score": total,
        "confidence_level": level,
        "confidence_pct": total,
        "engine_score": scores.get("engine_score"),
        "allowed": (decision in ("BUY", "SELL")),
        "min_score": min_score,
        "score_breakdown": breakdown,
        "reasons": reasons,
        "failed_checks": fails,
        "recommendation": _recommend(decision, checklist, ma),
        "risk_analysis": risk,
        "setup": ({"entry": round(entry, 8), "stop": round(stop, 8),
                   "target": round(target, 8)} if entry else None),
        "market_analysis": ma,
        "checklist": checklist,
    }
