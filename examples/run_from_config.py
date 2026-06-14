"""Run the bot driven entirely by a YAML config.

Usage:
    python -m examples.run_from_config configs/example.yaml
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone

from bot.config import build_from_config, load_yaml


def main(path: str) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = load_yaml(path)
    broker, strategy, risk, meta = build_from_config(cfg)
    mode = meta["mode"]

    if mode == "backtest":
        from bot.backtester import Backtester

        # Paper broker doesn't supply data; pull from a real source if configured,
        # otherwise fall back to synthetic data for a smoke run.
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=cfg.get("backtest_days", 60))
            bars = broker.get_historical_bars(
                meta["symbol"], meta["timeframe"], start=start, end=end,
            )
        except NotImplementedError:
            from examples.run_backtest import synthetic_bars
            bars = synthetic_bars(2000)

        bt = Backtester(
            strategy=strategy, bars=bars,
            starting_cash=cfg.get("starting_cash", 10_000.0),
            risk=risk,
            timeframe=meta["timeframe"],
            market=meta["market"],
        )
        print(bt.run().summary())
        return

    # Paper/live trading
    from bot.live import LiveRunner
    LiveRunner(
        broker=broker, strategy=strategy,
        timeframe=meta["timeframe"], warmup_bars=meta["warmup_bars"],
        risk=risk, dry_run=meta["dry_run"],
    ).run()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "configs/example.yaml")
