"""AI Trading Coach + Explainable-AI + Performance Attribution.

Turns a real replay's trades into a mentor-style review (why trades won / lost,
the recurring mistakes, the conditions to avoid, and what to do next), a
performance attribution breakdown (which session / regime / setup / side made or
lost money), and per-trade explanations (why / why-not / why-trust).

Pure functions over the replay ``trades`` list — fully unit-testable.
"""
from __future__ import annotations

from collections import Counter

from strategies.diagnosis import _hour, _session


def _setup_tag(entry_reasons) -> str:
    """Collapse a trade's entry reasons into one primary setup label."""
    blob = " ".join(entry_reasons or []).lower()
    if "sweep" in blob:
        return "Liquidity sweep"
    if "structure" in blob or "bos" in blob or "choch" in blob:
        return "Structure shift"
    if "fair-value" in blob or "fvg" in blob:
        return "Fair-value gap"
    if "ema" in blob or "cross" in blob:
        return "EMA cross"
    if "pullback" in blob or "retest" in blob:
        return "Pullback / retest"
    if "aligned" in blob or "bullish" in blob or "bearish" in blob:
        return "Trend alignment"
    return "Other confluence"


def _closed(trades) -> list:
    return [t for t in trades if t.get("rr") is not None]


def _bucket(trades, keyfn) -> list:
    """Group closed trades by ``keyfn`` → per-bucket trades / net R / win rate."""
    groups: dict = {}
    for t in trades:
        k = keyfn(t)
        groups.setdefault(k, []).append(t["rr"])
    out = []
    for k, rs in groups.items():
        wins = [r for r in rs if r > 0]
        out.append({
            "key": k, "trades": len(rs),
            "net_r": round(sum(rs), 2),
            "win_rate": round(len(wins) / len(rs) * 100, 1) if rs else 0.0,
            "avg_r": round(sum(rs) / len(rs), 3) if rs else 0.0,
        })
    out.sort(key=lambda b: b["net_r"], reverse=True)
    return out


def attribution(trades: list) -> dict:
    """Performance attribution: which session / regime / setup / side / symbol
    made money (#17)."""
    cl = _closed(trades)
    return {
        "by_session": _bucket(cl, lambda t: _session(_hour(t.get("entry_time", "")))),
        "by_regime": _bucket(cl, lambda t: t.get("regime", "—")),
        "by_setup": _bucket(cl, lambda t: _setup_tag(t.get("entry_reasons"))),
        "by_side": _bucket(cl, lambda t: t.get("side", "—")),
        "by_symbol": _bucket(cl, lambda t: t.get("symbol", "—")),
    }


def explain_trade(trade: dict) -> dict:
    """Explainable AI — every trade answers why / why-not / why-trust (#16)."""
    reasons = trade.get("entry_reasons") or []
    score = trade.get("score", 0)
    mtf = (trade.get("mtf") or {}).get("reason")
    why = f"Entered {trade.get('side')} at score {score}/100 — " + (", ".join(reasons[:3]) or "confluence met") + "."
    won = (trade.get("rr") or 0) > 0
    if won:
        why_not = "Nothing material — target reached before the stop."
    else:
        why_not = trade.get("loss_analysis") or trade.get("exit_reason") or "Setup invalidated into the stop."
    factors = len(reasons)
    aligned = (trade.get("mtf") or {}).get("aligned")
    why_trust = (f"Score {score}/100 from {factors} confluence factor(s)"
                 + (", higher-timeframe aligned" if aligned else "")
                 + (f" ({mtf})" if mtf else "")
                 + ". Always validate out-of-sample before sizing up.")
    return {"id": trade.get("id"), "result": trade.get("result"), "rr": trade.get("rr"),
            "why": why, "why_not": why_not, "why_trust": why_trust}


def _top_mistakes(losers) -> list:
    """Most common loss reasons across losing trades."""
    c = Counter(t.get("loss_analysis") for t in losers if t.get("loss_analysis"))
    return [{"mistake": m, "count": n} for m, n in c.most_common(3)]


def coach_review(trades: list, stats: dict, *, symbol: str, strategy: str) -> dict:
    """Mentor-style review of a simulation (#6)."""
    cl = _closed(trades)
    n = len(cl)
    if n == 0:
        return {"symbol": symbol, "strategy": strategy, "trades": 0,
                "headline": "No trades to review — the filters blocked every setup this run.",
                "why_won": [], "why_lost": [], "common_mistakes": [],
                "weak_conditions": [], "suggestions": [
                    "Loosen the minimum quality score or widen the date range to get a sample."],
                "confidence_score": 0, "stability_score": 0, "attribution": attribution(trades)}

    attr = attribution(trades)
    winners = [t for t in cl if t["rr"] > 0]
    losers = [t for t in cl if t["rr"] < 0]
    net = round(sum(t["rr"] for t in cl), 2)
    pf = stats.get("profit_factor", 0)
    wr = stats.get("win_rate", 0)

    def _pos(bucket):  # best contributor with a meaningful sample
        top = [b for b in bucket if b["net_r"] > 0 and b["trades"] >= 2]
        return top[0] if top else None

    def _neg(bucket):
        bad = [b for b in bucket if b["net_r"] < 0 and b["trades"] >= 2]
        return bad[-1] if bad else None

    why_won, why_lost, weak = [], [], []
    for label, bucket in (("session", attr["by_session"]), ("regime", attr["by_regime"]),
                          ("setup", attr["by_setup"]), ("side", attr["by_side"])):
        g = _pos(bucket)
        if g:
            why_won.append(f"{g['key']} {label} carried the edge — {g['trades']} trades, "
                           f"{g['win_rate']}% win, net {g['net_r']:+}R.")
        b = _neg(bucket)
        if b:
            why_lost.append(f"{b['key']} {label} bled — {b['trades']} trades, "
                            f"{b['win_rate']}% win, net {b['net_r']:+}R.")
            if label in ("regime", "session"):
                weak.append(f"{b['key']} ({label})")

    mistakes = _top_mistakes(losers)
    # suggestions from the real evidence-based lessons engine
    from services.lessons import lessons_from_results
    bundle = {"trades": [{**t, "r": t["rr"]} for t in cl], "total_trades": n,
              "win_rate": wr, "profit_factor": pf,
              "max_drawdown_pct": stats.get("max_drawdown_r", 0), "span_days": 30}
    suggestions = [ls["suggested_fix"] for ls in lessons_from_results(bundle, symbol=symbol, strategy=strategy)][:4]
    if not suggestions:
        suggestions = ["Solid run — keep the sample size growing and validate out-of-sample before sizing up."
                       if net >= 0 else "Tighten entries: raise the minimum quality score and skip the weak conditions above."]

    # scores
    consistency = min(1.0, (pf / 2.0)) if pf else 0.0
    sample = min(1.0, n / 30.0)
    confidence = int(round(100 * (0.6 * consistency + 0.4 * sample)))
    dd = abs(stats.get("max_drawdown_r", 0))
    stability = int(round(100 * max(0.0, 1.0 - dd / max(abs(net) + dd, 1e-9)))) if n else 0

    grade = "winning" if net > 0 and pf >= 1 else "break-even" if abs(net) < 1 else "losing"
    headline = (f"This {strategy} run on {symbol} is {grade}: {n} trades, {wr}% win rate, "
                f"profit factor {pf}, net {net:+}R.")

    return {
        "symbol": symbol, "strategy": strategy, "trades": n, "net_r": net,
        "headline": headline,
        "why_won": why_won or ["Winners were spread thin — no single condition dominated."],
        "why_lost": why_lost or (["No condition stood out as a consistent drain."] if losers else []),
        "common_mistakes": mistakes,
        "weak_conditions": weak,
        "suggestions": suggestions,
        "confidence_score": confidence, "stability_score": stability,
        "attribution": attr,
        "sample_explanations": [explain_trade(t) for t in (winners[:1] + losers[:2])],
    }
