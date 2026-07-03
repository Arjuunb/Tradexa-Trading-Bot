"""Real-data validation — does the edge survive real candles?

Everything tuned on synthetic data must re-prove itself on real market
history before it deserves trust. This runner takes the REAL cached candles
(deep-backfilled from Binance), refuses to run on gappy/corrupt or synthetic
data, and puts the strategy through the honest gauntlet per symbol:

    integrity      the candle series itself must pass verification
    walk-forward   optimise on each train block, score ONLY unseen blocks
    realistic fills the full-history run must survive spread+slippage+latency

The verdict is per-symbol and overall, with the exact numbers shown — if the
edge does not hold on real data, this says so plainly.
"""
from __future__ import annotations


def validate_symbol(strategy: str, symbol: str, timeframe: str, *, bars: int = 4000) -> dict:
    from data.integrity import verify
    from data.market_data import get_bars
    from services.backtest_lab import walk_forward
    from services.strategy_presets import run_simulation

    rows, source = get_bars(symbol, n=bars, timeframe=timeframe, require_real=True)
    if not rows:
        return {"symbol": symbol, "verdict": "no-data",
                "detail": "No real candles cached — run POST /data/backfill first."}
    integrity = verify(rows, timeframe)
    if integrity["verdict"] == "bad":
        return {"symbol": symbol, "verdict": "bad-data", "data_source": source,
                "integrity": integrity,
                "detail": "Candle series failed integrity checks — re-backfill before trusting any result."}

    wf = walk_forward(strategy, symbol, timeframe, bars=bars)
    real = run_simulation(strategy, symbol, timeframe, bars=bars, realistic=True)
    if not real.get("available"):
        return {"symbol": symbol, "verdict": "no-data", "detail": real.get("error", "")}

    r = real["results"]
    oos = wf.get("aggregate", {}) if wf.get("available") else {}
    oos_net = oos.get("net_r")
    trades = r.get("total_trades", 0)
    edge = (trades >= 10
            and r.get("net_r", 0) > 0 and r.get("profit_factor", 0) > 1.0
            and (oos_net is None or oos_net > 0))
    verdict = "edge-holds" if edge else ("insufficient-trades" if trades < 10 else "edge-does-not-hold")
    return {"symbol": symbol, "timeframe": timeframe, "verdict": verdict,
            "data_source": source, "candles": len(rows),
            "integrity": {k: integrity[k] for k in ("verdict", "missing_pct", "duplicates", "bad_candles")},
            "realistic_full_run": {"trades": trades, "net_r": r.get("net_r"),
                                   "profit_factor": r.get("profit_factor"),
                                   "win_rate": r.get("win_rate"),
                                   "max_drawdown_pct": r.get("max_drawdown_pct")},
            "walk_forward_oos": oos or {"note": wf.get("error", "walk-forward unavailable")}}


def validate_real(strategy: str = "Decision Brain", symbols=None,
                  timeframe: str = "4h", bars: int = 4000) -> dict:
    """Validate a strategy on REAL cached data across symbols. The overall
    verdict is honest: 'validated' only when a majority of symbols with data
    hold their edge out-of-sample AND under realistic fills."""
    symbols = list(symbols or ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"))
    per = [validate_symbol(strategy, s, timeframe, bars=bars) for s in symbols]
    with_data = [p for p in per if p["verdict"] not in ("no-data", "bad-data")]
    holds = [p for p in with_data if p["verdict"] == "edge-holds"]
    if not with_data:
        overall = "no-real-data"
        detail = "No symbol has enough real candles. Run POST /data/backfill on the deployed host, then retry."
    elif len(holds) * 2 >= len(with_data):
        overall = "validated"
        detail = (f"{len(holds)}/{len(with_data)} symbols hold their edge on real data "
                  f"(walk-forward out-of-sample + realistic fills).")
    else:
        overall = "not-validated"
        detail = (f"Only {len(holds)}/{len(with_data)} symbols hold their edge on real data. "
                  f"Do not scale up risk; consider retuning on real history.")
    return {"strategy": strategy, "timeframe": timeframe, "overall": overall,
            "detail": detail, "symbols": per}
