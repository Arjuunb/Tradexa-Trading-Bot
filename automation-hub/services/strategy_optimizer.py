"""Evidence-based optimisation suggestions.

Each suggestion is DERIVED from a measurable weakness in the backtest — a losing
session bucket, a losing side, a streak, a drawdown ratio — and carries:

    reason · evidence[] · expected_benefit · tradeoffs · confidence · patch

The ``patch`` is a machine-applicable diff onto the spec, so the user can accept
it in one click and immediately re-run. Nothing is ever applied automatically,
and no suggestion is emitted without a statistic behind it: if the data shows no
addressable weakness, the list comes back empty rather than padded with generic
trading advice.

Suggestions only propose changes the ENGINE can actually execute (session
window, side, risk %, stop type, target RR, risk-gate limits, or an extra rule
from the real block palette) — never a knob that does not exist.
"""
from __future__ import annotations

from typing import Any, Optional

from services.strategy_review import (
    exit_reason_breakdown, regime_breakdown, session_breakdown,
)
from services.strategy_builder import CONFIG

_MIN_SAMPLE = 8          # a bucket needs this many trades to justify a change
_HIGH = "high"
_MED = "medium"
_LOW = "low"


_SAMPLE = 12       # affected-trade examples returned per suggestion


def _ev(stat: str, value: Any) -> dict:
    return {"stat": stat, "value": value}


def _trade_row(t: dict) -> dict:
    """The fields a user needs to recognise a trade in the review."""
    return {k: t.get(k) for k in
            ("side", "entry", "exit", "r", "result", "exit_reason",
             "entry_time", "exit_time", "bars_held", "regime")}


def _affected(trades: list[dict], pred) -> dict:
    """The REAL trades a suggestion would have changed — count, their net R, and
    a sample. Never a description of trades: the actual rows."""
    rows = [t for t in trades if pred(t)]
    net = round(sum(float(t.get("r") or 0.0) for t in rows), 2)
    return {"count": len(rows), "net_r": net,
            "sample": [_trade_row(t) for t in rows[:_SAMPLE]]}


def _session_by_label(label: str) -> Optional[dict]:
    for s in CONFIG.get("sessions", []):
        if s.get("label") == label:
            return s
    return None


def _in_session_pred(label: str):
    """Match trades whose real entry hour falls inside a named session."""
    from services.strategy_review import _hour
    preset = _session_by_label(label) or {}
    start, end = int(preset.get("start", 0)), int(preset.get("end", 24))
    def _p(t):
        h = _hour(t.get("entry_time"))
        return h is not None and start <= h < end
    return _p


def suggestions(spec: dict, results: Optional[dict]) -> list[dict]:
    """Ranked list of evidence-backed changes. Empty when nothing is supported."""
    if not results or not results.get("trades"):
        return []
    trades = list(results["trades"])
    out: list[dict] = []
    n = len(trades)

    # 1. A trading session that loses money -> restrict to the best one.
    if not spec.get("session"):
        sess = session_breakdown(trades)
        losers = [s for s in sess if s["net_r"] < 0 and s["trades"] >= _MIN_SAMPLE]
        best = next((s for s in sess if s["trades"] >= _MIN_SAMPLE), None)
        if losers and best and best["net_r"] > 0:
            worst = min(losers, key=lambda s: s["net_r"])
            preset = _session_by_label(best["session"])
            if preset:
                out.append({
                    "id": "restrict_session",
                    "title": f"Trade only the {best['session']} session",
                    "reason": (f"{worst['session']} lost {abs(worst['net_r'])}R across "
                               f"{worst['trades']} trades while {best['session']} made "
                               f"{best['net_r']}R."),
                    "evidence": [_ev(f"{worst['session']} net R", worst["net_r"]),
                                 _ev(f"{worst['session']} trades", worst["trades"]),
                                 _ev(f"{best['session']} net R", best["net_r"])],
                    "expected_benefit": f"Removes the {abs(worst['net_r'])}R lost in {worst['session']}.",
                    "tradeoffs": ("Fewer trades overall, and the sample in the kept session "
                                  "becomes smaller — the edge may not hold out of sample."),
                    "confidence": _HIGH if worst["trades"] >= 15 else _MED,
                    "patch": {"session": {"start": preset["start"], "end": preset["end"]}},
                    "affected": _affected(trades, _in_session_pred(worst["session"])),
                })

    # 2. One side loses while the other pays -> trade the profitable side only.
    lnr, snr = results.get("long_net_r"), results.get("short_net_r")
    lt, st = results.get("long_trades") or 0, results.get("short_trades") or 0
    if lt >= _MIN_SAMPLE and st >= _MIN_SAMPLE and isinstance(lnr, (int, float)) \
            and isinstance(snr, (int, float)):
        if lnr > 0 > snr or snr > 0 > lnr:
            keep, drop = ("long", "short") if lnr > snr else ("short", "long")
            kv, dv = (lnr, snr) if keep == "long" else (snr, lnr)
            out.append({
                "id": "restrict_side",
                "title": f"Trade {keep} only",
                "reason": f"{keep.title()} trades made {kv}R while {drop} lost {abs(dv)}R.",
                "evidence": [_ev(f"{keep} net R", kv), _ev(f"{drop} net R", dv),
                             _ev(f"{drop} trades", st if drop == "short" else lt)],
                "expected_benefit": f"Removes the {abs(dv)}R lost on the {drop} side.",
                "tradeoffs": "Halves the opportunity set and gives up any hedging effect.",
                "confidence": _HIGH,
                "patch": {"side": keep},
                "affected": _affected(trades, lambda t: str(t.get("side")) == drop),
            })

    # 3. Drawdown large relative to return -> size down.
    net, dd = results.get("net_r"), results.get("max_drawdown_r")
    risk_pct = spec.get("risk_per_trade_pct")
    if all(isinstance(v, (int, float)) for v in (net, dd, risk_pct)) and dd:
        ratio = abs(net / dd)
        if ratio < 1.5 and risk_pct > 0.005:
            new = round(max(0.005, risk_pct / 2), 4)
            out.append({
                "id": "reduce_risk",
                "title": f"Cut risk per trade to {new * 100:g}%",
                "reason": (f"Return is only {round(ratio, 2)}x the worst drawdown, so the "
                           "equity curve is paying a lot of pain per unit of profit."),
                "evidence": [_ev("net R", net), _ev("max drawdown R", dd),
                             _ev("net R / drawdown R", round(ratio, 2)),
                             _ev("current risk per trade", risk_pct)],
                "expected_benefit": "Halves drawdown depth in account terms.",
                "tradeoffs": "Halves returns too — this improves survivability, not profit.",
                "confidence": _MED,
                "patch": {"risk_per_trade_pct": new},
            })

    # 4. Long losing streaks -> arm the risk gate that already exists.
    streak = results.get("max_consecutive_losses")
    if isinstance(streak, (int, float)) and streak >= 6 and not spec.get("max_consecutive_losses"):
        out.append({
            "id": "streak_guard",
            "title": f"Pause after {int(streak) - 2} consecutive losses",
            "reason": f"The strategy lost {int(streak)} trades in a row at its worst.",
            "evidence": [_ev("max consecutive losses", int(streak)),
                         _ev("total trades", n)],
            "expected_benefit": "Stops the bleed during the conditions that produce streaks.",
            "tradeoffs": ("Trading pauses after a bad run, so it can sit out the recovery "
                          "that often follows."),
            "confidence": _MED,
            "patch": {"max_consecutive_losses": max(3, int(streak) - 2)},
            "affected": _affected(trades, lambda t: float(t.get("r") or 0) <= 0),
        })

    # 5. Fixed-% stop while volatility varies -> ATR stop.
    stop = spec.get("stop") or {}
    if stop.get("type") == "pct":
        regimes = regime_breakdown(trades)
        volatile = [r for r in regimes if "volat" in r["regime"].lower()]
        if volatile:
            v = volatile[0]
            out.append({
                "id": "atr_stop",
                "title": "Use an ATR stop instead of a fixed percentage",
                "reason": (f"{v['trades']} trades ran in {v['regime']} conditions, where a "
                           "fixed-% stop is too tight in fast markets and too wide in slow ones."),
                "evidence": [_ev(f"{v['regime']} trades", v["trades"]),
                             _ev(f"{v['regime']} net R", v["net_r"]),
                             _ev("current stop", stop)],
                "expected_benefit": "Stop distance adapts to the volatility actually present.",
                "tradeoffs": "Position size varies more between trades; R stays constant.",
                "confidence": _MED,
                "patch": {"stop": {"type": "atr", "mult": 1.5, "period": 14}},
            })

    # 6. Winners barely beat losers -> ask for more reward per unit of risk.
    target = spec.get("target") or {}
    avg_rr = results.get("avg_rr")
    if target.get("type") == "rr" and isinstance(avg_rr, (int, float)) \
            and isinstance(target.get("rr"), (int, float)) and avg_rr < 1.2 and target["rr"] < 3:
        new_rr = round(min(3.0, target["rr"] + 1), 2)
        out.append({
            "id": "raise_target",
            "title": f"Raise the target to {new_rr}R",
            "reason": f"Average realised reward-to-risk is only {avg_rr}, so winners are "
                      "not paying for the losers.",
            "evidence": [_ev("avg RR", avg_rr), _ev("current target R", target["rr"]),
                         _ev("win rate %", results.get("win_rate"))],
            "expected_benefit": "Each winner covers more losers.",
            "tradeoffs": "Win rate will fall — more trades will miss the further target.",
            "confidence": _LOW if (results.get("win_rate") or 0) < 40 else _MED,
            "patch": {"target": {"type": "rr", "rr": new_rr}},
        })

    # 7. Most damage from one exit type -> surface it (no safe auto-patch).
    exits = exit_reason_breakdown(trades)
    bad = [e for e in exits if e["net_r"] < 0 and e["trades"] >= _MIN_SAMPLE]
    if bad:
        w = min(bad, key=lambda e: e["net_r"])
        out.append({
            "id": "exit_pattern",
            "title": f"Investigate exits by '{w['exit_reason']}'",
            "reason": f"{w['trades']} trades exited via {w['exit_reason']} for {w['net_r']}R.",
            "evidence": [_ev("exit reason", w["exit_reason"]), _ev("trades", w["trades"]),
                         _ev("net R", w["net_r"]), _ev("win rate %", w["win_rate"])],
            "expected_benefit": "Identifies where the losses concentrate.",
            "tradeoffs": ("No automatic change is proposed — the right fix depends on why "
                          "those exits happen, so this one is for you to judge."),
            "confidence": _MED,
            "patch": None,          # deliberately not auto-applicable
            "affected": _affected(
                trades, lambda t: str(t.get("exit_reason")) == w["exit_reason"]),
        })

    for sug in out:
        sug.setdefault("affected", {"count": 0, "net_r": 0.0, "sample": []})
    order = {_HIGH: 0, _MED: 1, _LOW: 2}
    return sorted(out, key=lambda s: order.get(s["confidence"], 3))


def apply_patch(spec: dict, patch: Optional[dict]) -> dict:
    """Return a COPY of ``spec`` with ``patch`` merged in. Never mutates the
    original — the user's strategy is only ever changed by their own action."""
    if not patch:
        return dict(spec)
    out = dict(spec)
    for k, v in patch.items():
        out[k] = v
    return out


def compare(before: dict, after: dict) -> dict:
    """Side-by-side diff of two backtest result sets, for original vs optimised."""
    keys = ("total_trades", "win_rate", "profit_factor", "net_r", "net_pct",
            "max_drawdown_r", "max_drawdown_pct", "expectancy_r", "avg_rr", "sharpe")
    rows = []
    for k in keys:
        a, b = before.get(k), after.get(k)
        delta = (round(b - a, 3) if isinstance(a, (int, float))
                 and isinstance(b, (int, float)) else None)
        rows.append({"metric": k, "before": a, "after": b, "delta": delta})
    return {"rows": rows}
