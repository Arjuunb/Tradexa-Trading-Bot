"""Multi-symbol backtest example.

Runs the same S/R + rejection strategy on three synthetic crypto-like symbols
sharing one cash account and one risk budget.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from bot.multi_backtester import MultiSymbolBacktester
from bot.risk import RiskConfig, RiskManager
from bot.strategies.support_resistance import SupportResistanceRejection
from bot.types import Bar


def _synthetic(start_price: float, n: int, seed: int) -> list[Bar]:
    rng = random.Random(seed)
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    p = start_price
    out: list[Bar] = []
    for i in range(n):
        p *= 1 + rng.uniform(-0.01, 0.01)
        hi = p * (1 + abs(rng.gauss(0, 0.004)))
        lo = p * (1 - abs(rng.gauss(0, 0.004)))
        op = p * (1 + rng.gauss(0, 0.002))
        out.append(Bar(t + timedelta(hours=i),
                       open=op, high=max(op, hi, p),
                       low=min(op, lo, p), close=p, volume=1000.0))
    return out


if __name__ == "__main__":
    bars = {
        "BTC/USDT": _synthetic(30_000, 1000, seed=1),
        "ETH/USDT": _synthetic(2_500, 1000, seed=2),
        "SOL/USDT": _synthetic(150, 1000, seed=3),
    }
    strategies = {sym: SupportResistanceRejection(sym, min_touches=1) for sym in bars}
    mb = MultiSymbolBacktester(
        strategies=strategies,
        bars=bars,
        starting_cash=50_000,
        fee_bps=5.0, slippage_bps=2.0,
        risk=RiskManager(RiskConfig(max_open_positions=2)),
        timeframe="1h", market="24_7",
    )
    res = mb.run()
    print(res.summary())
