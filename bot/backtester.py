"""Event-driven backtester.

Feeds bars one-by-one to the strategy, routes signals through the risk
manager, submits orders to the PaperBroker, and tracks an equity curve.
At the end it computes summary metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import math

from bot.brokers.paper import PaperBroker
from bot.risk import RiskManager
from bot.strategies.base import Strategy
from bot.types import Bar, Order, OrderType, Side, SignalType


@dataclass
class BacktestResult:
    equity_curve: list[tuple[datetime, float]]
    trades: list[dict]
    starting_equity: float
    ending_equity: float
    metrics: dict = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        lines = [
            f"Start equity:   {self.starting_equity:,.2f}",
            f"End equity:     {self.ending_equity:,.2f}",
            f"Total return:   {m.get('total_return', 0):.2%}",
            f"Trades:         {m.get('num_trades', 0)}",
            f"Win rate:       {m.get('win_rate', 0):.2%}",
            f"Avg R:          {m.get('avg_r', 0):.2f}",
            f"Sharpe (ann.):  {m.get('sharpe', 0):.2f}",
            f"Max drawdown:   {m.get('max_dd', 0):.2%}",
        ]
        return "\n".join(lines)


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        bars: list[Bar],
        starting_cash: float = 10_000.0,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        risk: RiskManager | None = None,
    ):
        self.strategy = strategy
        self.bars = bars
        self.broker = PaperBroker(starting_cash, fee_bps, slippage_bps)
        self.risk = risk or RiskManager()
        self.equity_curve: list[tuple[datetime, float]] = []
        self.trades: list[dict] = []
        self._open_trade: dict | None = None

    def run(self) -> BacktestResult:
        starting = self.broker.get_account().equity

        for bar in self.bars:
            # 1. let broker process bar (fills, SL/TP)
            fills = self.broker.on_bar(self.strategy.symbol, bar)
            for f in fills:
                self._record_fill(f, bar)

            # 2. ask strategy for a signal
            signal = self.strategy.on_bar(bar)
            if signal and signal.type in (SignalType.LONG, SignalType.SHORT):
                # ignore if already in a position
                if self.broker.get_position(self.strategy.symbol) is None:
                    account = self.broker.get_account()
                    allow, qty, reason = self.risk.evaluate(signal, account, bar.timestamp)
                    if allow:
                        side = Side.BUY if signal.type == SignalType.LONG else Side.SELL
                        order = Order(
                            symbol=signal.symbol,
                            side=side,
                            qty=qty,
                            order_type=OrderType.MARKET,
                            stop_loss=signal.stop_loss,
                            take_profit=signal.take_profit,
                        )
                        self.broker.submit_order(order)
                        self._open_trade = {
                            "entry_time": bar.timestamp,
                            "side": side.value,
                            "entry_planned": signal.entry,
                            "sl": signal.stop_loss,
                            "tp": signal.take_profit,
                            "reason": signal.reason,
                            "qty": qty,
                        }

            # 3. record equity
            self.equity_curve.append((bar.timestamp, self.broker.get_account().equity))

        ending = self.broker.get_account().equity
        result = BacktestResult(
            equity_curve=self.equity_curve,
            trades=self.trades,
            starting_equity=starting,
            ending_equity=ending,
        )
        result.metrics = self._metrics(starting, ending)
        return result

    # ------------------------------------------------------------ helpers
    def _record_fill(self, fill, bar: Bar) -> None:
        if self._open_trade is None:
            # this is an entry fill
            self._open_trade = self._open_trade or {}
            return
        # exit fill (SL/TP)
        entry_px = self._open_trade.get("entry_planned", fill.price)
        side = self._open_trade["side"]
        qty = self._open_trade["qty"]
        if side == "buy":
            pnl = (fill.price - entry_px) * qty
        else:
            pnl = (entry_px - fill.price) * qty
        risk = abs(entry_px - self._open_trade["sl"]) * qty
        r_multiple = pnl / risk if risk > 0 else 0
        self.trades.append({
            **self._open_trade,
            "exit_time": fill.timestamp,
            "exit_price": fill.price,
            "pnl": pnl,
            "r": r_multiple,
        })
        self.risk.on_trade_closed(pnl, fill.timestamp)
        self._open_trade = None

    def _metrics(self, start: float, end: float) -> dict:
        if not self.trades:
            return {"total_return": (end - start) / start, "num_trades": 0,
                    "win_rate": 0, "avg_r": 0, "sharpe": 0, "max_dd": 0}

        wins = [t for t in self.trades if t["pnl"] > 0]
        num = len(self.trades)
        win_rate = len(wins) / num
        avg_r = sum(t["r"] for t in self.trades) / num

        # Sharpe from equity curve daily returns
        eq = [v for _, v in self.equity_curve]
        rets = []
        for i in range(1, len(eq)):
            if eq[i - 1] > 0:
                rets.append((eq[i] - eq[i - 1]) / eq[i - 1])
        if rets:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = math.sqrt(var) if var > 0 else 0
            # Annualization factor — assume hourly bars by default (24*365);
            # users with different timeframes should multiply accordingly.
            sharpe = (mean / std) * math.sqrt(24 * 365) if std > 0 else 0
        else:
            sharpe = 0

        # max drawdown
        peak = eq[0] if eq else start
        max_dd = 0.0
        for v in eq:
            peak = max(peak, v)
            dd = (v - peak) / peak if peak > 0 else 0
            max_dd = min(max_dd, dd)

        return {
            "total_return": (end - start) / start,
            "num_trades": num,
            "win_rate": win_rate,
            "avg_r": avg_r,
            "sharpe": sharpe,
            "max_dd": max_dd,
        }
