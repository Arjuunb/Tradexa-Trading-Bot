"""Live / paper-trade runner — same loop, real broker.

Usage:
    from bot.brokers import get_broker
    from bot.strategies import SupportResistanceRejection
    from bot.live import LiveRunner

    broker = get_broker("ccxt", exchange_id="binance",
                       api_key=..., api_secret=..., sandbox=True)
    strat  = SupportResistanceRejection("BTC/USDT")
    LiveRunner(broker, strat, timeframe="1h").run()
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from bot.brokers.base import Broker
from bot.risk import RiskManager
from bot.strategies.base import Strategy
from bot.types import Order, OrderType, Side, SignalType

log = logging.getLogger("bot.live")


class LiveRunner:
    def __init__(
        self,
        broker: Broker,
        strategy: Strategy,
        timeframe: str = "1h",
        warmup_bars: int = 200,
        risk: RiskManager | None = None,
        dry_run: bool = False,        # print orders instead of submitting
    ):
        self.broker = broker
        self.strategy = strategy
        self.timeframe = timeframe
        self.warmup_bars = warmup_bars
        self.risk = risk or RiskManager()
        self.dry_run = dry_run

    def _warmup(self) -> None:
        log.info("Warming up with %d historical bars...", self.warmup_bars)
        end = datetime.now(timezone.utc)
        # crude: ask for a large lookback period and let the broker limit it
        bars = self.broker.get_historical_bars(
            symbol=self.strategy.symbol,
            timeframe=self.timeframe,
            start=datetime(2000, 1, 1, tzinfo=timezone.utc),
            end=end,
            limit=self.warmup_bars,
        )
        for b in bars[-self.warmup_bars:]:
            self.strategy.on_bar(b)
        log.info("Warmup complete (%d bars loaded).", len(bars))

    def run(self) -> None:
        self._warmup()
        log.info("Starting live loop on %s via %s", self.strategy.symbol, self.broker.name)
        for bar in self.broker.stream_bars(self.strategy.symbol, self.timeframe):
            signal = self.strategy.on_bar(bar)
            if not signal or signal.type == SignalType.FLAT:
                continue
            if self.broker.get_position(self.strategy.symbol) is not None:
                log.info("Skipping signal — already in a position.")
                continue

            account = self.broker.get_account()
            allow, qty, reason = self.risk.evaluate(signal, account, bar.timestamp)
            if not allow:
                log.info("Risk blocked trade: %s", reason)
                continue

            side = Side.BUY if signal.type == SignalType.LONG else Side.SELL
            order = Order(
                symbol=signal.symbol,
                side=side,
                qty=qty,
                order_type=OrderType.MARKET,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
            )
            if self.dry_run:
                log.info("[DRY] Would submit: %s", order)
            else:
                oid = self.broker.submit_order(order)
                log.info("Submitted order %s — %s qty=%.6f SL=%.4f TP=%.4f (%s)",
                         oid, side.value, qty, signal.stop_loss, signal.take_profit,
                         signal.reason)
