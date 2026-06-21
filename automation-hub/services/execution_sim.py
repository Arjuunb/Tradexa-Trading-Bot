"""Execution realism layer (#9).

The core simulator already books fees + slippage. This adds the rest of real-
world execution friction — spread, latency, partial fills and order rejection —
as a NON-INVASIVE post-processing step over a run's trades, so it never disturbs
the core simulate() path (or the tests that depend on it).

Pure + seed-deterministic.
"""
from __future__ import annotations

import random
from typing import Optional

DEFAULTS = {
    "spread_pct": 0.0002,        # half-spread paid each side
    "slippage_pct": 0.0003,      # market-impact slippage each side
    "latency_pct": 0.0001,       # adverse move while the order is in flight
    "partial_fill_prob": 0.10,   # chance an order only partially fills
    "partial_fraction": 0.6,     # how much fills when partial
    "reject_prob": 0.02,         # chance the order is rejected outright
    "seed": 1,
}


def _risk(t) -> Optional[float]:
    entry, stop = t.get("entry"), t.get("sl") if t.get("sl") is not None else t.get("stop")
    if entry and stop:
        d = abs(float(entry) - float(stop))
        return d if d > 0 else None
    return None


def apply_execution_realism(trades: list, **cfg) -> dict:
    """Re-price a run's trades with realistic execution and return ideal-vs-real
    stats plus the per-trade adjustments."""
    c = {**DEFAULTS, **{k: v for k, v in cfg.items() if v is not None}}
    rnd = random.Random(int(c["seed"]))
    cost_pct = float(c["spread_pct"]) + float(c["slippage_pct"]) + float(c["latency_pct"])
    adj, rejected, partials = [], 0, 0
    for t in trades:
        r = t.get("rr")
        if r is None:
            continue
        if rnd.random() < float(c["reject_prob"]):
            rejected += 1
            continue
        risk = _risk(t)
        cost_r = (cost_pct * float(t.get("entry", 0)) * 2 / risk) if risk else cost_pct * 4
        weight = 1.0
        if rnd.random() < float(c["partial_fill_prob"]):
            weight = float(c["partial_fraction"])
            partials += 1
        adj.append({"rr_ideal": r, "rr": round((r - cost_r) * weight, 3),
                    "cost_r": round(cost_r, 3), "filled": weight})
    ideal = _stats([t["rr"] for t in trades if t.get("rr") is not None])
    real = _stats([t["rr"] for t in adj])
    return {
        "config": c, "trades": len(adj), "rejected": rejected, "partial_fills": partials,
        "ideal": ideal, "realistic": real,
        "slippage_cost_r": round(ideal["net_r"] - real["net_r"], 2),
        "edge_survives": real["net_r"] > 0 and real["profit_factor"] >= 1,
    }


def _stats(rs: list) -> dict:
    n = len(rs)
    if n == 0:
        return {"trades": 0, "net_r": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
                "expectancy_r": 0.0, "max_drawdown_r": 0.0}
    wins = [r for r in rs if r > 0]
    gp, gl = sum(wins), -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "trades": n, "net_r": round(sum(rs), 2),
        "win_rate": round(len(wins) / n * 100, 1),
        "profit_factor": round(gp / gl, 2) if gl else (99.0 if gp else 0.0),
        "expectancy_r": round(sum(rs) / n, 3), "max_drawdown_r": round(dd, 2),
    }
