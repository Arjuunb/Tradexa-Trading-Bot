"""Growth Journey — the bot's performance MEMORY, summarised.

Pure computation over the permanent trade-memory rows: lifetime record,
expectancy, streaks, month-by-month progress, and per-strategy / per-symbol
splits. Everything is derived from remembered trades only — no market data,
no projections, and an honest empty state until the first trade is remembered.
Small samples are labelled as such rather than presented as an edge.
"""
from __future__ import annotations

from collections import defaultdict


def _r(x, nd=2):
    return round(float(x), nd)


def build_growth(rows: list[dict]) -> dict:
    """Summarise remembered trades (any order; sorted internally by close)."""
    closed = [t for t in rows if t.get("result") in ("win", "loss", "breakeven")]
    if not closed:
        return {"available": False,
                "note": "The journey starts with the first remembered trade."}

    closed.sort(key=lambda t: t.get("closed_at") or "")
    wins = [t for t in closed if t["result"] == "win"]
    losses = [t for t in closed if t["result"] == "loss"]
    rr = [float(t.get("actual_rr") or 0.0) for t in closed]
    pnl = [float(t.get("pnl") or 0.0) for t in closed]
    win_r = [float(t.get("actual_rr") or 0.0) for t in wins]
    loss_r = [float(t.get("actual_rr") or 0.0) for t in losses]
    gross_win = sum(x for x in rr if x > 0)
    gross_loss = -sum(x for x in rr if x < 0)

    # streaks (chronological)
    cur = longest_w = longest_l = run = 0
    last = None
    for t in closed:
        r = t["result"]
        if r == "breakeven":
            continue
        run = run + 1 if r == last else 1
        last = r
        if r == "win":
            longest_w = max(longest_w, run)
        else:
            longest_l = max(longest_l, run)
    if last is not None:
        cur = run if last == "win" else -run

    # month buckets (YYYY-MM from closed_at)
    months: dict[str, dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "net_r": 0.0})
    for t in closed:
        key = str(t.get("closed_at") or "")[:7]
        if len(key) != 7:
            continue
        m = months[key]
        m["trades"] += 1
        m["wins"] += 1 if t["result"] == "win" else 0
        m["net_r"] += float(t.get("actual_rr") or 0.0)
    monthly = [{"month": k, "trades": v["trades"], "net_r": _r(v["net_r"]),
                "win_rate": _r(100 * v["wins"] / v["trades"], 1)}
               for k, v in sorted(months.items())][-12:]

    def split(key: str) -> list[dict]:
        groups: dict[str, dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "net_r": 0.0})
        for t in closed:
            name = str(t.get(key) or "—")
            g = groups[name]
            g["trades"] += 1
            g["wins"] += 1 if t["result"] == "win" else 0
            g["net_r"] += float(t.get("actual_rr") or 0.0)
        out = [{"name": k, "trades": v["trades"], "net_r": _r(v["net_r"]),
                "win_rate": _r(100 * v["wins"] / v["trades"], 1)}
               for k, v in groups.items()]
        return sorted(out, key=lambda x: -x["net_r"])[:6]

    grades: dict[str, int] = defaultdict(int)
    for t in closed:
        g = str(t.get("grade") or "").strip().upper()[:1]
        if g:
            grades[g] += 1

    n = len(closed)
    return {
        "available": True,
        "totals": {
            "trades": n, "wins": len(wins), "losses": len(losses),
            "breakeven": n - len(wins) - len(losses),
            "win_rate": _r(100 * len(wins) / n, 1),
            "net_pnl": _r(sum(pnl)), "net_r": _r(sum(rr)),
            "expectancy_r": _r(sum(rr) / n, 3),
            "best_r": _r(max(rr)), "worst_r": _r(min(rr)),
            "avg_win_r": _r(sum(win_r) / len(win_r), 2) if win_r else 0.0,
            "avg_loss_r": _r(sum(loss_r) / len(loss_r), 2) if loss_r else 0.0,
            "profit_factor": _r(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        },
        "streaks": {"current": cur, "longest_win": longest_w, "longest_loss": longest_l},
        "span": {"first": closed[0].get("closed_at"), "last": closed[-1].get("closed_at")},
        "monthly": monthly,
        "by_strategy": split("strategy"),
        "by_symbol": split("symbol"),
        "grades": dict(sorted(grades.items())),
        "sample_note": ("early sample — fewer than 30 remembered trades; "
                        "treat every number as provisional" if n < 30 else
                        "meaningful sample (30+ remembered trades)"),
    }
