"""Live performance summary — the bot's ACTUAL paper-trading track record.

Computes the same risk/performance stats as the backtest report (win rate,
profit factor, expectancy, max drawdown, longest losing streak, equity curve)
but from the real executed trades in the ledger, not a backtest. This is what a
"Strategy Performance" view should show: how the bot is actually doing.
"""
from __future__ import annotations

from typing import Optional


def summarize(trades: list[dict], starting_balance: float, recent: int = 25) -> dict:
    closed = sorted((t for t in trades if t.get("pnl") is not None),
                    key=lambda t: t.get("closed_at") or "")
    n = len(closed)
    pnls = [float(t.get("pnl") or 0.0) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    # equity curve + max drawdown (absolute and %)
    equity = starting_balance
    peak = starting_balance
    max_dd_abs = 0.0
    max_dd_pct = 0.0
    curve = [{"t": None, "equity": round(starting_balance, 2)}]
    streak = worst_streak = 0
    for t, p in zip(closed, pnls):
        equity += p
        peak = max(peak, equity)
        dd = peak - equity
        max_dd_abs = max(max_dd_abs, dd)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, dd / peak)
        streak = streak + 1 if p < 0 else 0
        worst_streak = max(worst_streak, streak)
        curve.append({"t": t.get("closed_at"), "equity": round(equity, 2)})

    realized = sum(pnls)
    gross_win = sum(wins)
    gross_loss = -sum(losses)

    def _safe(v: Optional[float]) -> float:
        return round(v, 2) if v is not None else 0.0

    return {
        "trades": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (gross_win and 99.0 or 0.0),
        "expectancy": _safe(realized / n) if n else 0.0,
        "avg_win": _safe(gross_win / len(wins)) if wins else 0.0,
        "avg_loss": _safe(sum(losses) / len(losses)) if losses else 0.0,
        "best": _safe(max(pnls)) if pnls else 0.0,
        "worst": _safe(min(pnls)) if pnls else 0.0,
        "realized_pnl": round(realized, 2),
        "starting_balance": round(starting_balance, 2),
        "balance": round(starting_balance + realized, 2),
        "max_drawdown_abs": round(max_dd_abs, 2),
        "max_drawdown_pct": round(max_dd_pct * 100, 2),
        "longest_losing_streak": worst_streak,
        "equity_curve": curve,
        "recent": list(reversed(closed[-recent:])),
    }
