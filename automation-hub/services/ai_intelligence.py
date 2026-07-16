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


def daily_coach(insights: dict) -> dict:
    """AI coach summary over the real closed trades — trade count, win rate, the
    main recurring mistake, one actionable suggestion, and a risk-discipline
    read. Reuses the trade-memory insights (coaching + mistake library); nothing
    invented, honest on a thin sample."""
    ins = insights or {}
    overall = ins.get("overall") or {}
    n = overall.get("trades") or ins.get("sample") or 0
    mistakes = ins.get("mistakes") or []
    coaching = ins.get("coaching") or []

    main_mistake = None
    for m in mistakes:
        if isinstance(m, dict) and m.get("mistake"):
            main_mistake = m["mistake"]
            break

    suggestion = None
    for c in coaching:
        if isinstance(c, dict) and c.get("stage") not in (None, "insufficient-data") and c.get("statement"):
            suggestion = c["statement"]
            break
    if not suggestion:
        suggestion = (f"Cut out “{main_mistake}” — it's your most frequent error."
                      if main_mistake else "Keep taking only your highest-quality setups.")

    risk_terms = ("moved stop", "stop loss", "oversiz", "over-siz", "overtrad", "poor rr", "poor r:r", "chased", "risk")
    risk_flag = any(isinstance(m, dict) and any(t in (m.get("mistake", "") or "").lower() for t in risk_terms)
                    for m in mistakes)
    risk_discipline = "Needs work" if risk_flag else ("Excellent" if n else "—")

    wr = overall.get("win_rate")
    exp = overall.get("expectancy_r") if overall.get("expectancy_r") is not None else overall.get("expectancy")
    if n == 0:
        headline = "No closed trades yet — the coach starts once you've taken some."
    else:
        headline = (f"You've taken {n} trades" + (f" at a {wr}% win rate" if wr is not None else "") + ".")

    return {
        "sample": n, "ready": n >= 1,
        "trades": n, "win_rate": wr, "expectancy_r": exp,
        "avg_hold_seconds": ins.get("avg_hold_seconds"),
        "main_mistake": main_mistake,
        "suggestion": suggestion,
        "risk_discipline": risk_discipline,
        "best_session": _bucket_name(ins.get("best_session")) if ins.get("best_session") else None,
        "worst_setup": _bucket_name(ins.get("worst_setup")) if ins.get("worst_setup") else None,
        "headline": headline,
    }


def _base(symbol: str) -> str:
    """Human ticker: BTC/USDT or BTCUSDT -> BTC."""
    s = symbol.replace("/", "")
    for q in ("USDT", "USD", "USDC", "BTC"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def market_insights(reads: list[dict]) -> list[dict]:
    """Live, natural-language market insights from the analysis reads — trend,
    volume shifts, liquidity sweeps, reversals, and volatility. Each is a real
    read of the bars (never invented); returns [] when nothing notable."""
    out: list[dict] = []
    for r in reads or []:
        sym = r.get("symbol", "")
        ma = r.get("ma") or {}
        if not ma.get("available"):
            continue
        base = _base(sym)
        bias = (ma.get("bias") or "").lower()
        trend = ma.get("trend") or {}
        strength = (trend.get("strength_label") or "").lower()
        structure = ma.get("structure") or {}
        vol = (ma.get("volume") or {}).get("label") or ""
        vola = (ma.get("volatility") or {}).get("label") or ""
        sweep = (ma.get("liquidity") or {}).get("sweep")

        if bias in ("bullish", "bearish") and strength in ("strong", "very strong"):
            out.append({"symbol": sym, "kind": "trend", "tone": "green" if bias == "bullish" else "red",
                        "text": f"{base} is trending strongly ({bias})."})
        if structure.get("change_of_character"):
            out.append({"symbol": sym, "kind": "reversal", "tone": "amber",
                        "text": f"Possible reversal forming on {base} — change of character."})
        elif structure.get("break_of_structure") not in (None, "none", "None"):
            out.append({"symbol": sym, "kind": "structure", "tone": "default",
                        "text": f"{base} broke structure ({structure.get('break_of_structure')})."})
        if sweep and str(sweep).lower() not in ("none", "none detected"):
            out.append({"symbol": sym, "kind": "liquidity", "tone": "amber",
                        "text": f"Liquidity sweep detected on {base}."})
        if vol == "below average":
            out.append({"symbol": sym, "kind": "volume", "tone": "default",
                        "text": f"{base} volume is decreasing (below its 20-bar average)."})
        elif vol == "above average":
            out.append({"symbol": sym, "kind": "volume", "tone": "default",
                        "text": f"{base} volume is rising (above its 20-bar average)."})
        if "high" in vola.lower():
            out.append({"symbol": sym, "kind": "volatility", "tone": "red",
                        "text": f"High volatility warning on {base}."})
    return out


def _alert(type_: str, severity: str, title: str, detail: str, symbol: str = "") -> dict:
    return {"type": type_, "severity": severity, "title": title, "detail": detail, "symbol": symbol}


def evaluate_alerts(analyses: list[dict], risk: dict, *, in_session: bool = True,
                    session_window: str = "", high_impact_news: Optional[list] = None,
                    strong_score: int = 75, min_score: int = 60) -> list[dict]:
    """The AI alert feed — the spec's six alert types, each derived from real
    state (never fabricated). Ordered most-severe first."""
    alerts: list[dict] = []
    risk = risk or {}

    for a in analyses or []:
        if not a.get("available", True):
            continue
        sym = a.get("symbol", "")
        score = a.get("overall_score", 0)
        if a.get("allowed") and score >= strong_score:
            alerts.append(_alert("strong_setup", "success", f"Strong setup — {sym}",
                                 f"{a.get('decision')} at score {score}/100 "
                                 f"({a.get('confidence_level')} confidence).", sym))
        elif a.get("decision") == "SKIP" and score < min_score:
            alerts.append(_alert("weak_setup", "info", f"Weak setup skipped — {sym}",
                                 f"Score {score}/100 is below the {min_score} minimum — no trade.", sym))
        ra = a.get("risk_analysis") or {}
        if ra.get("excessive"):
            alerts.append(_alert("risk_exceeds_limit", "warning", f"Risk exceeds limit — {sym}",
                                 ra.get("warning") or "The proposed risk is above your limit.", sym))

    # portfolio-level exposure
    exp, lim = risk.get("exposure_pct"), risk.get("exposure_limit_pct")
    if exp is not None and lim and exp > lim:
        alerts.append(_alert("risk_exceeds_limit", "warning", "Portfolio exposure over limit",
                             f"Exposure {exp * 100:.0f}% exceeds the {lim * 100:.0f}% limit."))

    # max daily loss / halt
    if risk.get("auto_halted"):
        alerts.append(_alert("max_daily_loss", "critical", "Trading halted",
                             risk.get("halt_reason") or "A risk limit (e.g. max daily loss) was hit."))
    elif (risk.get("trading_state") or "").lower() not in ("active", ""):
        alerts.append(_alert("max_daily_loss", "warning", f"Trading {risk.get('trading_state')}",
                             "New entries are paused by a risk control."))

    # outside preferred session
    if not in_session:
        alerts.append(_alert("outside_session", "info", "Outside trading session",
                             f"Now outside the preferred window{f' ({session_window})' if session_window else ''} "
                             "— new entries are held until in-session."))

    # high-impact news (only when a source actually reports it)
    for n in high_impact_news or []:
        title = n.get("title") if isinstance(n, dict) else str(n)
        alerts.append(_alert("news", "warning", "High-impact news approaching", title))

    sev_rank = {"critical": 0, "warning": 1, "success": 2, "info": 3}
    alerts.sort(key=lambda x: sev_rank.get(x["severity"], 4))
    return alerts


def _mem_confidence(row: dict) -> Optional[float]:
    """A closed trade's pre-trade confidence as a 0–100 score. Prefers the
    Decision Brain score; falls back to a stored 0–1 confidence."""
    bs = row.get("brain_score")
    if bs is not None:
        return float(bs)
    c = row.get("confidence")
    if c is not None:
        return float(c) * 100 if float(c) <= 1.0 else float(c)
    return None


def confidence_accuracy(rows: list[dict]) -> dict:
    """Was the AI's pre-trade confidence borne out? Buckets closed trades by
    their confidence band and reports the realized win rate / expectancy of each
    — the calibration feedback loop. 'Calibrated' means higher-confidence setups
    actually won more often. Pure; honest about small samples."""
    graded = [(lvl, r) for r in rows
              if (r.get("result") in ("win", "loss", "breakeven"))
              and (_mem_confidence(r) is not None)
              for lvl in [confidence_level(_mem_confidence(r))]]
    order = ["Very High", "High", "Medium", "Low", "Very Low"]
    buckets = {lvl: [] for lvl in order}
    for lvl, r in graded:
        buckets[lvl].append(r)

    def _stat(rs: list[dict]) -> dict:
        n = len(rs)
        wins = sum(1 for r in rs if r.get("result") == "win")
        rr = [float(r["actual_rr"]) for r in rs if r.get("actual_rr") is not None]
        pnl = [float(r["pnl"]) for r in rs if r.get("pnl") is not None]
        return {"trades": n, "wins": wins,
                "win_rate": round(wins / n * 100, 1) if n else 0.0,
                "avg_rr": round(sum(rr) / len(rr), 2) if rr else None,
                "avg_pnl": round(sum(pnl) / len(pnl), 2) if pnl else None}

    by_conf = [{"level": lvl, **_stat(buckets[lvl])} for lvl in order]
    sample = len(graded)

    high = [r for lvl in ("Very High", "High") for r in buckets[lvl]]
    low = [r for lvl in ("Low", "Very Low") for r in buckets[lvl]]
    hi_wr = _stat(high)["win_rate"] if high else None
    lo_wr = _stat(low)["win_rate"] if low else None
    spread = round(hi_wr - lo_wr, 1) if (hi_wr is not None and lo_wr is not None) else None
    calibrated = spread is not None and spread > 0

    if sample < 10 or spread is None:
        verdict = f"Only {sample} graded trades — calibration firms up past ~10 with a spread of confidence."
    elif calibrated:
        verdict = (f"Well calibrated: high-confidence setups win {hi_wr}% vs {lo_wr}% for "
                   f"low-confidence (+{spread} pts).")
    else:
        verdict = (f"Miscalibrated: high-confidence setups win {hi_wr}% vs {lo_wr}% for "
                   f"low-confidence ({spread} pts) — the score isn't separating winners yet.")

    return {"sample": sample, "ready": sample >= 10, "by_confidence": by_conf,
            "high_conf_win_rate": hi_wr, "low_conf_win_rate": lo_wr,
            "spread_pts": spread, "calibrated": bool(calibrated), "verdict": verdict}


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
