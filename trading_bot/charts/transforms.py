"""Pure data transforms for charts (no plotting libs — fully testable)."""
from __future__ import annotations


def equity_values(curve) -> list:
    if not curve:
        return []
    pts = curve.get("points", []) if isinstance(curve, dict) else curve
    return [p.get("equity", 0.0) for p in pts]


def drawdown_series(equity: list) -> list:
    peak = None
    out = []
    for y in equity:
        peak = y if peak is None else max(peak, y)
        out.append(round(y - peak, 2))
    return out


def max_drawdown_pct(equity: list) -> float:
    peak = None
    mdd = 0.0
    for y in equity:
        peak = y if peak is None else max(peak, y)
        if peak:
            mdd = max(mdd, (peak - y) / peak)
    return round(mdd * 100, 2)


def win_loss_counts(trades: list) -> tuple:
    w = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
    loss = sum(1 for t in trades if (t.get("pnl") or 0) < 0)
    be = len(trades) - w - loss
    return w, loss, be


def allocation_from_positions(positions: list) -> tuple:
    labels, vals = [], []
    for p in positions:
        labels.append(p.get("symbol", "?"))
        vals.append(round((p.get("size", 0) or 0) * (p.get("entry", 0) or 0), 2))
    return labels, vals


def daily_pnl(trades: list) -> tuple:
    agg: dict = {}
    for t in trades:
        d = (t.get("closed_at") or "")[:10]
        if d:
            agg[d] = agg.get(d, 0.0) + (t.get("pnl") or 0.0)
    days = sorted(agg)
    return days, [round(agg[d], 2) for d in days]


def trade_r_distribution(trades: list, bins: int = 9) -> tuple:
    rs = [t.get("rr") for t in trades if t.get("rr") is not None]
    if not rs:
        return [], []
    lo, hi = min(rs), max(rs)
    if lo == hi:
        return [f"{lo:.1f}"], [len(rs)]
    width = (hi - lo) / bins
    labels = [f"{lo + i * width:.1f}" for i in range(bins)]
    counts = [0] * bins
    for r in rs:
        idx = min(int((r - lo) / width), bins - 1)
        counts[idx] += 1
    return labels, counts
