"""Empirically-verified parameter suggestions.

The heuristic optimiser reasons about a weakness and proposes a plausible fix.
This module does something stronger: it RUNS the variant and only suggests it if
the backtest actually improved.

That inverts the usual failure mode of "AI optimisation". Nothing here is a
theory about what might help — each suggestion carries the measured result of
the change against the unmodified strategy over the identical window, so
"expected benefit" is an observation rather than a prediction.

Guards against the obvious way this goes wrong (overfitting a backtest):
  * only NEIGHBOURING values of parameters the user already chose — it tunes,
    it does not search a space the user never described;
  * a variant must clear a MATERIAL margin, not win by noise;
  * a variant that trades far less than the original is rejected, because
    "improvement" from cherry-picking a handful of trades is not improvement;
  * the count of variants tested is reported, so a user can see how much
    searching produced the winner.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

MAX_VARIANTS = 12          # bounded: each variant is a real backtest
MIN_TRADE_RATIO = 0.6      # a variant keeping <60% of the trades is not comparable
MIN_PF_GAIN = 0.15         # profit factor must improve by at least this
MIN_NET_R_GAIN = 1.0       # ...and net R by at least this

# Parameters worth nudging, with sensible neighbouring values. Only these are
# touched: they are the ones whose meaning is "how strict is this rule".
_NEIGHBOURS: dict[str, Callable[[Any], list]] = {
    "fast": lambda v: [max(2, int(v) - 5), int(v) + 5, int(v) + 10],
    "slow": lambda v: [max(5, int(v) - 10), int(v) + 10, int(v) + 20],
    "period": lambda v: [max(2, int(v) - 5), int(v) + 5, int(v) + 10],
    "lookback": lambda v: [max(5, int(v) - 10), int(v) + 10, int(v) + 20],
    "value": lambda v: [round(float(v) - 5, 2), round(float(v) + 5, 2)],
    "value_pct": lambda v: [round(float(v) - 1, 2), round(float(v) + 1, 2)],
    "mult": lambda v: [round(float(v) - 0.5, 2), round(float(v) + 0.5, 2)],
    "std": lambda v: [round(float(v) - 0.5, 2), round(float(v) + 0.5, 2)],
    "pivot": lambda v: [max(2, int(v) - 1), int(v) + 1],
    "tolerance_pct": lambda v: [round(float(v) / 2, 3), round(float(v) * 2, 3)],
}


def _rules(spec: dict) -> list[dict]:
    return [r for r in ((spec.get("entry") or {}).get("rules") or [])
            if isinstance(r, dict) and r.get("type")]


def candidates(spec: dict, *, limit: int = MAX_VARIANTS) -> list[dict]:
    """Neighbouring-value variants of the rules the user actually wrote.

    Returns [{rule_index, rule_type, param, from, to, spec}] — never a rule the
    strategy does not contain, and never a parameter outside _NEIGHBOURS."""
    out: list[dict] = []
    rules = _rules(spec)
    for i, rule in enumerate(rules):
        for param, cur in rule.items():
            if param in ("type", "dir", "op", "negate", "source", "zone"):
                continue
            gen = _NEIGHBOURS.get(param)
            if not gen or not isinstance(cur, (int, float)):
                continue
            for new in gen(cur):
                if new == cur or (isinstance(new, (int, float)) and new <= 0):
                    continue
                variant_rules = [dict(r) for r in rules]
                variant_rules[i][param] = new
                out.append({
                    "rule_index": i, "rule_type": rule["type"],
                    "param": param, "from": cur, "to": new,
                    "spec": {**spec, "entry": {**(spec.get("entry") or {}),
                                               "rules": variant_rules}},
                })
                if len(out) >= limit:
                    return out
    return out


def _score(res: Optional[dict]) -> Optional[dict]:
    if not res or not res.get("trades"):
        return None
    return {"trades": res.get("total_trades") or 0,
            "net_r": float(res.get("net_r") or 0.0),
            "profit_factor": float(res.get("profit_factor") or 0.0),
            "win_rate": float(res.get("win_rate") or 0.0),
            "max_drawdown_r": float(res.get("max_drawdown_r") or 0.0),
            "expectancy_r": float(res.get("expectancy_r") or 0.0)}


def _improved(base: dict, var: dict) -> bool:
    """A variant must beat the original by a MATERIAL margin on both profit
    factor and net R, while still trading a comparable number of times."""
    if base["trades"] and var["trades"] / base["trades"] < MIN_TRADE_RATIO:
        return False
    return (var["profit_factor"] - base["profit_factor"] >= MIN_PF_GAIN
            and var["net_r"] - base["net_r"] >= MIN_NET_R_GAIN)


def tune(spec: dict, runner: Callable[[dict], Optional[dict]], *,
         limit: int = MAX_VARIANTS) -> dict:
    """Test parameter variants and return only those that MEASURABLY improved.

    ``runner(spec) -> results | None`` runs a real backtest (injected so this
    module stays pure and testable)."""
    base_res = runner(spec)
    base = _score(base_res)
    if not base:
        return {"available": False, "tested": 0, "suggestions": [],
                "note": "No baseline backtest to compare against."}

    cands = candidates(spec, limit=limit)
    tested = 0
    wins: list[dict] = []
    for c in cands:
        try:
            var = _score(runner(c["spec"]))
        except Exception:  # noqa: BLE001 — one bad variant must not kill tuning
            continue
        tested += 1
        if not var or not _improved(base, var):
            continue
        wins.append({
            "id": f"tune_{c['rule_type']}_{c['param']}_{c['to']}",
            "title": (f"Change {c['rule_type']} {c['param']} "
                      f"from {c['from']} to {c['to']}"),
            "reason": (f"Tested on the same data: profit factor "
                       f"{base['profit_factor']} -> {var['profit_factor']}, "
                       f"net {base['net_r']}R -> {var['net_r']}R."),
            "evidence": [
                {"stat": "profit factor (before -> after)",
                 "value": f"{base['profit_factor']} -> {var['profit_factor']}"},
                {"stat": "net R (before -> after)",
                 "value": f"{base['net_r']} -> {var['net_r']}"},
                {"stat": "trades (before -> after)",
                 "value": f"{base['trades']} -> {var['trades']}"},
                {"stat": "max drawdown R (before -> after)",
                 "value": f"{base['max_drawdown_r']} -> {var['max_drawdown_r']}"},
            ],
            "expected_benefit": (f"Measured, not predicted: +{round(var['net_r'] - base['net_r'], 2)}R "
                                 f"and +{round(var['profit_factor'] - base['profit_factor'], 2)} "
                                 "profit factor on this window."),
            "tradeoffs": ("This is one historical window. A parameter that wins here can "
                          "be curve-fitted — re-test on a different range before trusting it."),
            "confidence": "medium",     # measured, but single-window: never "high"
            "patch": {"entry": c["spec"]["entry"]},
            "measured": {"before": base, "after": var},
        })

    wins.sort(key=lambda w: w["measured"]["after"]["net_r"], reverse=True)
    return {
        "available": True,
        "tested": tested,
        "baseline": base,
        "suggestions": wins,
        "note": (None if wins else
                 f"Tested {tested} parameter variants; none beat the current "
                 "settings by a material margin. The strategy's parameters look "
                 "reasonable for this window."),
    }


def make_runner(bars_for_range, range_key: str):
    """Default runner: the shared spec runner, so a tuned variant is measured by
    exactly the engine wiring the baseline used."""
    from services.spec_runner import make_runner as _shared
    return _shared(bars_for_range, range_key)
