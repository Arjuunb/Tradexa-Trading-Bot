"""Live / paper-trade runner.

Same loop as the backtester, but driven by real broker bars and orders.

Key safety behaviors
--------------------
1. Per-bar housekeeping: ``risk.on_bar(equity, bar_time)`` is called every bar
   so cooldown is measured in bars, not signals.
2. Position reconciliation: before acting on a signal, the runner refreshes
   ``broker.get_position()`` and aborts if its internal view disagrees with
   the broker's view (e.g. out-of-band manual closes, liquidations).
3. Partial-fill aware: after submitting an entry, the runner waits briefly,
   queries fills, and re-uses the **actually filled** quantity rather than
   the requested one. SL/TP have already been attached by the broker as a
   bracket — we just record what was filled.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from bot.brokers.base import Broker
from bot.risk import RiskManager
from bot.strategies.base import Strategy
from bot.types import Order, OrderType, Position, Side, SignalType

log = logging.getLogger("bot.live")


class LiveRunner:
    def __init__(
        self,
        broker: Broker,
        strategy: Strategy,
        timeframe: str = "1h",
        warmup_bars: int = 200,
        risk: RiskManager | None = None,
        dry_run: bool = False,
        fill_wait_seconds: float = 5.0,
    ):
        self.broker = broker
        self.strategy = strategy
        self.timeframe = timeframe
        self.warmup_bars = warmup_bars
        self.risk = risk or RiskManager()
        self.dry_run = dry_run
        self.fill_wait_seconds = fill_wait_seconds
        # Internal mirror of "do we believe we are in a position?"
        self._internal_in_position: bool = False

    def _warmup(self) -> None:
        log.info("Warming up with %d historical bars...", self.warmup_bars)
        end = datetime.now(timezone.utc)
        bars = self.broker.get_historical_bars(
            symbol=self.strategy.symbol, timeframe=self.timeframe,
            start=datetime(2000, 1, 1, tzinfo=timezone.utc),
            end=end, limit=self.warmup_bars,
        )
        for b in bars[-self.warmup_bars:]:
            self.strategy.on_bar(b)
        log.info("Warmup complete (%d bars loaded).", len(bars))

    # ---------------------------------------------------- reconciliation
    def _reconcile(self) -> tuple[bool, Optional[Position]]:
        """Refresh broker view of position and compare to internal mirror.

        Returns (is_consistent, broker_position). Logs and returns False on
        any mismatch so the caller can refuse to trade.
        """
        broker_pos = self.broker.get_position(self.strategy.symbol)
        broker_in_pos = broker_pos is not None and broker_pos.qty != 0
        if broker_in_pos != self._internal_in_position:
            log.warning(
                "Position desync: internal=%s broker=%s (qty=%s). "
                "Refusing to trade this bar; syncing internal view.",
                self._internal_in_position, broker_in_pos,
                broker_pos.qty if broker_pos else None,
            )
            self._internal_in_position = broker_in_pos
            return False, broker_pos
        return True, broker_pos

    # ----------------------------------------------------------- main loop
    def run(self) -> None:
        self._warmup()
        log.info("Starting live loop on %s via %s",
                 self.strategy.symbol, self.broker.name)
        for bar in self.broker.stream_bars(self.strategy.symbol, self.timeframe):
            # Per-bar housekeeping (cooldown + daily-loss anchor).
            try:
                acct = self.broker.get_account()
                self.risk.on_bar(acct.equity, bar.timestamp)
            except Exception as e:
                log.warning("Account fetch failed: %s", e)
                continue

            signal = self.strategy.on_bar(bar)
            if not signal or signal.type == SignalType.FLAT:
                continue

            consistent, broker_pos = self._reconcile()
            if not consistent:
                continue
            if broker_pos is not None:
                log.info("Skipping signal — already in a position.")
                continue

            allow, qty, reason = self.risk.evaluate(signal, acct, bar.timestamp)
            if not allow:
                log.info("Risk blocked trade: %s", reason)
                continue

            side = Side.BUY if signal.type == SignalType.LONG else Side.SELL
            order = Order(
                symbol=signal.symbol, side=side, qty=qty,
                order_type=OrderType.MARKET,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            )
            if self.dry_run:
                log.info("[DRY] Would submit: %s", order)
                continue

            try:
                oid = self.broker.submit_order(order)
            except Exception:
                log.exception("submit_order failed")
                continue

            # Give the venue a moment, then verify the fill.
            time.sleep(self.fill_wait_seconds)
            filled_qty = self._verify_fill(oid, qty, since=bar.timestamp)
            if filled_qty <= 0:
                log.warning("Order %s did not fill (filled_qty=0).", oid)
                continue
            if filled_qty < qty:
                log.warning(
                    "Order %s only partially filled: requested=%.6f filled=%.6f. "
                    "SL/TP attached by broker remain sized to the original request — "
                    "monitor manually if your venue does not re-size brackets.",
                    oid, qty, filled_qty,
                )

            self._internal_in_position = True
            log.info(
                "Filled %s %s qty=%.6f SL=%.4f TP=%.4f (%s)",
                oid, side.value, filled_qty,
                signal.stop_loss, signal.take_profit, signal.reason,
            )

    def _verify_fill(self, order_id: str, requested_qty: float,
                     since: datetime) -> float:
        """Return total filled qty for ``order_id``."""
        try:
            fills = self.broker.get_fills(since=since)
        except Exception as e:
            log.warning("get_fills failed: %s", e)
            return 0.0
        total = 0.0
        for f in fills:
            if f.order_id == order_id:
                total += f.qty
        return total
