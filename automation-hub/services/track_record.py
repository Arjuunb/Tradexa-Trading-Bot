"""Track record — is live paper trading matching what the backtest promised?

The bridge between backtest and money is a verified LIVE record. This compares
the bot's actual closed paper trades against the backtest expectation for the
same configuration and says, with numbers, whether reality is tracking the
promise: win rate, expectancy (R), and drawdown, plus a plain verdict.

``compare`` is pure; the endpoint feeds it the live history and a fresh
realistic-fills backtest.
"""
from __future__ import annotations

MIN_TRADES = 20         # below this, any comparison is noise — say so


def _live_stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("status", "closed") == "closed"
              and t.get("rr") is not None]
    n = len(closed)
    if n == 0:
        return {"trades": 0}
    rs = [float(t["rr"]) for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r < 0]
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": n, "win_rate": round(100 * len(wins) / n, 1),
            "expectancy_r": round(sum(rs) / n, 3), "net_r": round(sum(rs), 2),
            "max_drawdown_r": round(dd, 2),
            "avg_win_r": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss_r": round(-sum(losses) / len(losses), 2) if losses else 0.0}


def compare(live: dict, expected: dict) -> dict:
    """Pure verdict: live stats vs backtest expectation."""
    if live.get("trades", 0) < MIN_TRADES:
        return {"verdict": "insufficient-live-trades",
                "detail": (f"Only {live.get('trades', 0)} closed live trades — "
                           f"need {MIN_TRADES}+ before the comparison means anything. Keep it running.")}
    if not expected or expected.get("trades", expected.get("total_trades", 0)) == 0:
        return {"verdict": "no-backtest-baseline",
                "detail": "No backtest expectation available (no real data cached?)."}
    exp_wr = expected.get("win_rate", 0.0)
    exp_exp = expected.get("expectancy_r", 0.0)
    d_wr = round(live["win_rate"] - exp_wr, 1)
    d_exp = round(live["expectancy_r"] - exp_exp, 3)
    # tolerance: live within 12 win-rate points and 0.25R expectancy of promise
    on_track = live["expectancy_r"] > 0 and d_wr >= -12 and d_exp >= -0.25
    diverging = live["expectancy_r"] <= 0 or d_exp < -0.4
    verdict = "on-track" if on_track else ("diverging" if diverging else "watch")
    details = {
        "on-track": "Live results are consistent with the backtest — the edge is showing up in forward trading.",
        "watch": "Live results lag the backtest but are within noise for this sample size — keep watching.",
        "diverging": "Live results are materially worse than the backtest promised — do NOT scale risk; investigate fills, regime shift, or overfit.",
    }
    return {"verdict": verdict, "detail": details[verdict],
            "win_rate_delta": d_wr, "expectancy_delta_r": d_exp}


def track_record(history: list[dict], *, strategy: str = "Decision Brain",
                 symbol: str = "BTCUSDT", timeframe: str = "4h",
                 bars: int = 3000) -> dict:
    """Live record vs a fresh realistic-fills backtest of the same config."""
    from services.strategy_presets import run_simulation
    live = _live_stats(history)
    bt = run_simulation(strategy, symbol, timeframe, bars=bars, realistic=True)
    expected = {}
    if bt.get("available"):
        r = bt["results"]
        expected = {"trades": r.get("total_trades", 0), "win_rate": r.get("win_rate", 0.0),
                    "expectancy_r": r.get("expectancy_r", 0.0),
                    "profit_factor": r.get("profit_factor", 0.0),
                    "max_drawdown_pct": r.get("max_drawdown_pct", 0.0),
                    "data_source": bt.get("data_source")}
    return {"live": live, "expected": expected,
            **compare(live, expected),
            "config": {"strategy": strategy, "symbol": symbol, "timeframe": timeframe}}
