"""Run a backtest of the Support/Resistance + rejection strategy.

By default this generates synthetic OHLCV data so you can run it without any
API keys. To use real crypto data, install ccxt and set USE_LIVE_DATA = True.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from bot.backtester import Backtester
from bot.risk import RiskConfig, RiskManager
from bot.strategies import SupportResistanceRejection
from bot.types import Bar


USE_LIVE_DATA = False        # flip to True if ccxt is installed
SYMBOL = "BTC/USDT"


def synthetic_bars(n: int = 2000, seed: int = 42) -> list[Bar]:
    """Generate trending + mean-reverting synthetic OHLCV bars."""
    rng = random.Random(seed)
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    price = 30_000.0
    bars: list[Bar] = []
    for i in range(n):
        # gentle sinusoidal regime + noise => creates revisits = zones
        drift = math.sin(i / 60) * 80
        noise = rng.gauss(0, 60)
        new_price = max(1.0, price + drift + noise)
        high = max(price, new_price) + abs(rng.gauss(0, 30))
        low = min(price, new_price) - abs(rng.gauss(0, 30))
        bars.append(Bar(t, price, high, low, new_price, rng.uniform(50, 200)))
        price = new_price
        t += timedelta(hours=1)
    return bars


def main() -> None:
    if USE_LIVE_DATA:
        from bot.brokers import get_broker
        b = get_broker("ccxt", exchange_id="binance", sandbox=False)
        bars = b.get_historical_bars(
            SYMBOL, "1h",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    else:
        bars = synthetic_bars()

    strategy = SupportResistanceRejection(SYMBOL, pivot=3, min_touches=2, rr_target=2.0)
    risk = RiskManager(RiskConfig(risk_per_trade_pct=0.01, max_open_positions=1))
    bt = Backtester(strategy, bars, starting_cash=10_000, risk=risk)
    result = bt.run()
    print(result.summary())
    print(f"\nFirst 5 trades:")
    for t in result.trades[:5]:
        print(t)


if __name__ == "__main__":
    main()
