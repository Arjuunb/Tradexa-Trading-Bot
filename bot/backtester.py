"""Event-driven backtester.

Feeds bars one-by-one to the strategy, routes signals through the risk
manager, submits orders to the PaperBroker, and tracks an equity curve.
At the end it computes summary metrics.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bot.brokers.paper import PaperBroker
from bot.risk import RiskManager
from bot.strategies.base import Strategy
from bot.types import Bar, Fill, Order, OrderType, Side, SignalType


# Annualization factors keyed by timeframe label.
_BARS_PER_YEAR = {
    "1m": 60 * 24 * 365,
    "5m": 12 * 24 * 365,
    "15m": 4 * 24 * 365,
    "30m": 2 * 24 * 365,
    "1h": 24 * 365,
    "4h": 6 * 365,
    "1d": 252,            # trading days for equities; for 24/7 crypto use 365
}


@dataclass
class BacktestResult:
    equity_curve: list[tuple[datetime, float]]
    trades: list[dict]
    starting_equity: float
    ending_equity: float
    metrics: dict = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        return "\n".join([
            f"Start equity:   {self.starting_equity:,.2f}",
            f"End equity:     {self.ending_equity:,.2f}",
            f"Total return:   {m.get('total_return', 0):.2%}",
            f"Trades:         {m.get('num_trades', 0)}",
            f"Win rate:       {m.get('win_rate', 0):.2%}",
            f"Avg R:          {m.get('avg_r', 0):.2f}",
            f"Sharpe (ann.):  {m.get('sharpe', 0):.2f}",
            f"Max drawdown:   {m.get('max_dd', 0):.2%}",
        ])


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        bars: list[Bar],
        starting_cash: float = 10_000.0,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        risk: RiskManager | None = None,
        timeframe: str = "1h",
    ):
        self.strategy = strategy
        self.bars = bars
        self.broker = PaperBroker(starting_cash, fee_bps, slippage_bps)
        self.risk = risk or RiskManager()
        self.timeframe = timeframe
        self.equity_curve: list[tuple[datetime, float]] = []
        self.trades: list[dict] = []
        self._pending_trade: Optional[dict] = None      # signal -> awaits entry fill
        self._open_trade: Optional[dict] = None         # entry filled, awaiting exit

    def run(self) -> BacktestResult:
        starting = self.broker.get_account().equity

        for bar in self.bars:
            # 1. Process bar through broker — fills, SL/TP triggers
            fills = self.broker.on_bar(self.strategy.symbol, bar)
            for f in fills:
                self._handle_fill(f)

            # 2. Strategy signal
            signal = self.strategy.on_bar(bar)
            if signal and signal.type in (SignalType.LONG, SignalType.SHORT):
                # Only enter if flat and no entry already pending
                in_position = self.broker.get_position(self.strategy.symbol) is not None
                if not in_position and self._pending_trade is None and self._open_trade is None:
                    account = self.broker.get_account()
                    allow, qty, reason = self.risk.evaluate(signal, account, bar.timestamp)
                    if allow and qty > 0:
                        side = Side.BUY if signal.type == SignalType.LONG else Side.SELL
                        order = Order(
                            symbol=signal.symbol, side=side, qty=qty,
                            order_type=OrderType.MARKET,
                            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                        )
                        self.broker.submit_order(order)
                        # Trade is *pending* — actual entry price determined by next bar's fill
                        self._pending_trade = {
                            "signal_time": bar.timestamp,
                            "side": side.value,
                            "planned_entry": signal.entry,
                            "planned_sl": signal.stop_loss,
                            "planned_tp": signal.take_profit,
                            "reason": signal.reason,
                            "qty": qty,
                        }

            # 3. Equity snapshot
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
    def _handle_fill(self, fill: Fill) -> None:
        role = self.broker.fill_role(fill)
        if role == "entry":
            if self._pending_trade is None:
                return        # entry without a pending trade (shouldn't happen)
            self._open_trade = {
                **self._pending_trade,
                "entry_time": fill.timestamp,
                "entry_price": fill.price,
                "entry_fee": fill.fee,
            }
            self._pending_trade = None
            return

        # exit fill
        if self._open_trade is None:
            return
        entry_px = self._open_trade["entry_price"]
        qty = self._open_trade["qty"]
        side = self._open_trade["side"]
        if side == "buy":
            gross = (fill.price - entry_px) * qty
        else:
            gross = (entry_px - fill.price) * qty
        pnl = gross - self._open_trade["entry_fee"] - fill.fee
        sl = self._open_trade["planned_sl"]
        risk_per_unit = abs(entry_px - sl)
        risk_dollars = risk_per_unit * qty
        r_multiple = pnl / risk_dollars if risk_dollars > 0 else 0.0
        self.trades.append({
            **self._open_trade,
            "exit_time": fill.timestamp,
            "exit_price": fill.price,
            "exit_fee": fill.fee,
            "pnl": pnl,
            "r": r_multiple,
        })
        self.risk.on_trade_closed(pnl, fill.timestamp)
        self._open_trade = None

    def _metrics(self, start: float, end: float) -> dict:
        eq = [v for _, v in self.equity_curve]

        # Drawdown — always computable from equity curve.
        max_dd = 0.0
        if eq:
            peak = eq[0]
            for v in eq:
                if v > peak:
                    peak = v
                if peak > 0:
                    dd = (v - peak) / peak
                    if dd < max_dd:
                        max_dd = dd

        # Sharpe — use timeframe-aware annualization factor.
        rets = []
        for i in range(1, len(eq)):
            if eq[i - 1] > 0:
                rets.append((eq[i] - eq[i - 1]) / eq[i - 1])
        if rets:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = math.sqrt(var) if var > 0 else 0.0
            ann = _BARS_PER_YEAR.get(self.timeframe, 24 * 365)
            sharpe = (mean / std) * math.sqrt(ann) if std > 0 else 0.0
        else:
            sharpe = 0.0

        if not self.trades:
            return {
                "total_return": (end - start) / start if start else 0,
                "num_trades": 0, "win_rate": 0.0, "avg_r": 0.0,
                "sharpe": sharpe, "max_dd": max_dd,
            }

        wins = [t for t in self.trades if t["pnl"] > 0]
        num = len(self.trades)
        return {
            "total_return": (end - start) / start if start else 0,
            "num_trades": num,
            "win_rate": len(wins) / num,
            "avg_r": sum(t["r"] for t in self.trades) / num,
            "sharpe": sharpe,
            "max_dd": max_dd,
        }
