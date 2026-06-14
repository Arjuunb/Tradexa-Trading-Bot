"""Execution engine — routes orders to a broker.

Phase 1 paper runs go through the backtester's PaperBroker, so this engine is
primarily the live-path interface (Phase 5): given a connected broker it submits
orders and reconciles fills. It already accepts any ``bot.brokers.base.Broker``,
so the paper broker and the live exchange adapters are interchangeable.
"""
from __future__ import annotations

from bot.brokers.base import Broker
from bot.types import Order


class ExecutionEngine:
    def __init__(self, broker: Broker, dry_run: bool = True):
        self.broker = broker
        self.dry_run = dry_run

    def submit(self, order: Order) -> str:
        if self.dry_run:
            return f"dry-run:{order.symbol}:{order.side.value}:{order.qty}"
        return self.broker.submit_order(order)

    def cancel(self, order_id: str) -> None:
        if not self.dry_run:
            self.broker.cancel_order(order_id)
