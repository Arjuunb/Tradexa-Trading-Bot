"""Event-driven backtester.

Feeds bars one at a time to the strategy, routes signals through the risk
manager, submits orders to the PaperBroker, tracks an equity curve, and
finally computes summary metrics.

Assumptions documented in the README
------------------------------------
* A signal generated on bar N can only fill at bar N+1's open (no look-ahead).
* When a bar's range spans BOTH the stop loss and the take profit, the
  ``sl_first`` parameter decides which fills (default True — conservative).
* Trade PnL is reported NET of entry and exit fees.
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


# Bars-per-year by timeframe. 24/7 markets (crypto/FX) use 365 days; equities use 252.
_BARS_PER_YEAR_24_7 = {
    "1m": 60 * 24 * 365,
    "5m": 12 * 24 * 365,
    "15m": 4 * 24 * 365,
    "30m": 2 * 24 * 365,
    "1h": 24 * 365,
    "4h": 6 * 365,
    "1d": 365,
}
_BARS_PER_YEAR_RTH = {        # regular trading hours (US equities, ~6.5h/day, 252d/yr)
    "1m": 60 * 6.5 * 252,
    "5m": 12 * 6.5 * 252,
    "15m": 4 * 6.5 * 252,
    "30m": 2 * 6.5 * 252,
    "1h": 6.5 * 252,
    "1d": 252,
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
        market: str = "24_7",          # "24_7" (crypto/fx) or "rth" (equities)
        sl_first: bool = True,         # conservative same-bar tie-break
    ):
        if starting_cash <= 0:
            raise ValueError("starting_cash must be > 0")
        self.strategy = strategy
        self.bars = bars
        self.broker = PaperBroker(
            starting_cash=starting_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            sl_first=sl_first,
        )
        self.risk = risk or RiskManager()
        self.timeframe = timeframe
        self.market = market
        self.equity_curve: list[tuple[datetime, float]] = []
        self.trades: list[dict] = []
        self._pending_trade: Optional[dict] = None
        self._open_trade: Optional[dict] = None

    # ------------------------------------------------------------------- run
    def run(self) -> BacktestResult:
        starting = self.broker.get_account().equity

        for bar in self.bars:
            # 0. Per-bar risk housekeeping (cooldown decrement, day rollover).
            self.risk.on_bar(self.broker.get_account().equity, bar.timestamp)

            # 1. Broker processes the bar (fills any pending orders + SL/TP).
            for fill in self.broker.on_bar(self.strategy.symbol, bar):
                self._handle_fill(fill)

            # 2. Strategy signal.
            signal = self.strategy.on_bar(bar)
            if signal and signal.type in (SignalType.LONG, SignalType.SHORT):
                in_pos = self.broker.get_position(self.strategy.symbol) is not None
                if not in_pos and self._pending_trade is None and self._open_trade is None:
                    account = self.broker.get_account()
                    allow, qty, _ = self.risk.evaluate(signal, account, bar.timestamp)
                    if allow and qty > 0:
                        side = Side.BUY if signal.type == SignalType.LONG else Side.SELL
                        order = Order(
                            symbol=signal.symbol, side=side, qty=qty,
                            order_type=OrderType.MARKET,
                            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                        )
                        self.broker.submit_order(order)
                        self._pending_trade = {
                            "signal_time": bar.timestamp,
                            "side": side.value,
                            "planned_entry": signal.entry,
                            "planned_sl": signal.stop_loss,
                            "planned_tp": signal.take_profit,
                            "reason": signal.reason,
                            "qty": qty,
                        }

            # 3. Equity snapshot.
            self.equity_curve.append((bar.timestamp, self.broker.get_account().equity))

        # End-of-run: force close any still-open trade at last close.
        self._force_close_at_end()

        ending = self.broker.get_account().equity
        result = BacktestResult(
            equity_curve=self.equity_curve,
            trades=self.trades,
            starting_equity=starting,
            ending_equity=ending,
        )
        result.metrics = self._metrics(starting, ending)
        return result

    # ----------------------------------------------------------- helpers
    def _handle_fill(self, fill: Fill) -> None:
        role = self.broker.fill_role(fill)
        if role == "entry":
            if self._pending_trade is None:
                return
            self._open_trade = {
                **self._pending_trade,
                "entry_time": fill.timestamp,
                "entry_price": fill.price,
                "entry_fee": fill.fee,
            }
            self._pending_trade = None
            return

        # exit
        if self._open_trade is None:
            return
        entry_px = self._open_trade["entry_price"]
        qty = self._open_trade["qty"]
        side = self._open_trade["side"]
        gross = (fill.price - entry_px) * qty if side == "buy" else (entry_px - fill.price) * qty
        net_pnl = gross - self._open_trade["entry_fee"] - fill.fee
        sl = self._open_trade["planned_sl"]
        risk_dollars = abs(entry_px - sl) * qty
        r_multiple = net_pnl / risk_dollars if risk_dollars > 0 else 0.0
        self.trades.append({
            **self._open_trade,
            "exit_time": fill.timestamp,
            "exit_price": fill.price,
            "exit_fee": fill.fee,
            "gross_pnl": gross,
            "pnl": net_pnl,                  # NET of fees
            "r": r_multiple,
        })
        self.risk.on_trade_closed(net_pnl, fill.timestamp)
        self._open_trade = None

    def _force_close_at_end(self) -> None:
        """If a position is still open after the last bar, close it at last close."""
        if not self.bars or self._open_trade is None:
            return
        last_bar = self.bars[-1]
        sym = self.strategy.symbol
        pos = self.broker.get_position(sym)
        if pos is None:
            return
        exit_side = Side.SELL if pos.qty > 0 else Side.BUY
        close_order = Order(symbol=sym, side=exit_side, qty=abs(pos.qty),
                            order_type=OrderType.MARKET)
        self.broker.submit_order(close_order)
        # Inject a synthetic "next bar" with open = last close so it fills here.
        synthetic = Bar(last_bar.timestamp, last_bar.close, last_bar.close,
                        last_bar.close, last_bar.close, 0.0)
        for fill in self.broker.on_bar(sym, synthetic):
            self._handle_fill(fill)
        # Update last equity point so the final equity reflects the close.
        if self.equity_curve:
            self.equity_curve[-1] = (last_bar.timestamp,
                                     self.broker.get_account().equity)

    def _metrics(self, start: float, end: float) -> dict:
        eq = [v for _, v in self.equity_curve]

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

        rets = []
        for i in range(1, len(eq)):
            if eq[i - 1] > 0:
                rets.append((eq[i] - eq[i - 1]) / eq[i - 1])
        if rets:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = math.sqrt(var) if var > 0 else 0.0
            table = _BARS_PER_YEAR_RTH if self.market == "rth" else _BARS_PER_YEAR_24_7
            ann = table.get(self.timeframe, 24 * 365)
            sharpe = (mean / std) * math.sqrt(ann) if std > 0 else 0.0
        else:
            sharpe = 0.0

        base = {
            "total_return": (end - start) / start if start else 0.0,
            "max_dd": max_dd,
            "sharpe": sharpe,
            "annualization_factor": (
                _BARS_PER_YEAR_RTH if self.market == "rth" else _BARS_PER_YEAR_24_7
            ).get(self.timeframe, 24 * 365),
        }
        if not self.trades:
            return {**base, "num_trades": 0, "win_rate": 0.0, "avg_r": 0.0}

        wins = [t for t in self.trades if t["pnl"] > 0]
        num = len(self.trades)
        return {
            **base,
            "num_trades": num,
            "win_rate": len(wins) / num,
            "avg_r": sum(t["r"] for t in self.trades) / num,
        }
