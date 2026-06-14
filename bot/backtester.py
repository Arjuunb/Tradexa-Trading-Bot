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

import uuid

from bot.brokers.paper import PaperBroker
from bot.data.indicators import atr as compute_atr
from bot.events import (
    EventBus, ev_bar, ev_fill, ev_order, ev_risk_block, ev_run_finished,
    ev_run_started, ev_signal, ev_trade_closed,
)
from bot.metrics import expand_metrics
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

    def summary(self, ascii_chart: bool = False, width: int = 60, height: int = 10) -> str:
        m = self.metrics
        lines = [
            f"Start equity:   {self.starting_equity:,.2f}",
            f"End equity:     {self.ending_equity:,.2f}",
            f"Total return:   {m.get('total_return', 0):.2%}",
            f"CAGR:           {m.get('cagr', 0):.2%}",
            f"Trades:         {m.get('num_trades', 0)}",
            f"Win rate:       {m.get('win_rate', 0):.2%}",
            f"Avg R:          {m.get('avg_r', 0):.2f}",
            f"Profit factor:  {m.get('profit_factor', 0):.2f}",
            f"Expectancy:     {m.get('expectancy', 0):,.4f}",
            f"Sharpe (ann.):  {m.get('sharpe', 0):.2f}",
            f"Sortino (ann.): {m.get('sortino', 0):.2f}",
            f"Calmar:         {m.get('calmar', 0):.2f}",
            f"Max drawdown:   {m.get('max_dd', 0):.2%}",
        ]
        if ascii_chart and self.equity_curve:
            lines.append("")
            lines.append(self.ascii_equity_chart(width=width, height=height))
        return "\n".join(lines)

    def ascii_equity_chart(self, width: int = 60, height: int = 10) -> str:
        """Tiny stdlib-only equity sparkline. Useful when running headless."""
        eq = [v for _, v in self.equity_curve]
        if not eq or width < 4 or height < 2:
            return ""
        n = len(eq)
        if n <= width:
            sample = eq
        else:
            step = n / width
            sample = [eq[int(i * step)] for i in range(width)]
        lo, hi = min(sample), max(sample)
        if hi == lo:
            hi = lo + 1.0
        rows = []
        for r in range(height, 0, -1):
            threshold = lo + (hi - lo) * (r - 0.5) / height
            row = "".join("#" if v >= threshold else " " for v in sample)
            rows.append(f"{threshold:10.2f} │ {row}")
        rows.append(" " * 10 + " └" + "─" * len(sample))
        return "\n".join(rows)

    def export_equity_csv(self, path: str) -> None:
        """Write the equity curve as CSV (timestamp,equity)."""
        import csv
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "equity"])
            for ts, v in self.equity_curve:
                w.writerow([ts.isoformat(), v])

    def export_trades_jsonl(self, path: str) -> None:
        """Write trades as JSONL."""
        import json
        from datetime import datetime as _dt
        from pathlib import Path

        def _default(o):
            if isinstance(o, _dt):
                return o.isoformat()
            raise TypeError(f"not serialisable: {type(o)}")

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for t in self.trades:
                f.write(json.dumps(t, default=_default) + "\n")


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
        bus: EventBus | None = None,
        run_id: str | None = None,
        # ----- v0.3 trade-management knobs (default OFF) -----
        breakeven_after_r: float = 0.0,     # T3: move stop to entry once +N*R
        partial_tp_r: float = 0.0,          # T3: take partial profit at +N*R
        partial_tp_frac: float = 0.5,       # fraction of position to close
        max_hold_bars: int = 0,             # T4: force-close after N bars
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
        self.starting_cash = starting_cash
        self.bus = bus
        self.run_id = run_id or uuid.uuid4().hex[:12]
        if breakeven_after_r < 0:
            raise ValueError("breakeven_after_r must be >= 0")
        if partial_tp_r < 0:
            raise ValueError("partial_tp_r must be >= 0")
        if not (0.0 < partial_tp_frac < 1.0) and partial_tp_r > 0:
            raise ValueError("partial_tp_frac must be in (0, 1) when partial TP is enabled")
        if max_hold_bars < 0:
            raise ValueError("max_hold_bars must be >= 0")
        self.breakeven_after_r = breakeven_after_r
        self.partial_tp_r = partial_tp_r
        self.partial_tp_frac = partial_tp_frac
        self.max_hold_bars = max_hold_bars
        self.equity_curve: list[tuple[datetime, float]] = []
        self.trades: list[dict] = []
        self._pending_trade: Optional[dict] = None
        self._open_trade: Optional[dict] = None
        self._partial_done: bool = False
        self._breakeven_done: bool = False
        self._bars_held: int = 0

    # ------------------------------------------------------------------- run
    def _emit(self, ev: dict) -> None:
        if self.bus is not None:
            self.bus.publish(ev)

    def run(self) -> BacktestResult:
        starting = self.broker.get_account().equity
        self._emit(ev_run_started(
            self.run_id, "backtest", [self.strategy.symbol], starting,
        ))

        bar_history: list[Bar] = []
        atr_period = self.risk.cfg.atr_period
        atr_enabled = self.risk.cfg.atr_stop_mult > 0

        for bar in self.bars:
            # 0. Per-bar risk housekeeping (cooldown decrement, day rollover).
            self.risk.on_bar(self.broker.get_account().equity, bar.timestamp)
            bar_history.append(bar)
            if atr_enabled and len(bar_history) > atr_period:
                self.risk.update_atr(compute_atr(bar_history, atr_period))

            # 1. Broker processes the bar (fills any pending orders + SL/TP).
            for fill in self.broker.on_bar(self.strategy.symbol, bar):
                self._handle_fill(fill, bar)

            # 1b. Trade management (T3 breakeven + partial TP, T4 time exit).
            self._manage_open_trade(bar)

            # 2. Strategy signal.
            signal = self.strategy.on_bar(bar)
            if signal and signal.type in (SignalType.LONG, SignalType.SHORT):
                side_str = "buy" if signal.type == SignalType.LONG else "sell"
                self._emit(ev_signal(
                    signal.symbol, side_str, signal.entry,
                    signal.stop_loss, signal.take_profit,
                    signal.reason, bar.timestamp,
                ))
                in_pos = self.broker.get_position(self.strategy.symbol) is not None
                if not in_pos and self._pending_trade is None and self._open_trade is None:
                    account = self.broker.get_account()
                    allow, qty, block_reason = self.risk.evaluate(signal, account, bar.timestamp)
                    if allow and qty > 0:
                        side = Side.BUY if signal.type == SignalType.LONG else Side.SELL
                        order = Order(
                            symbol=signal.symbol, side=side, qty=qty,
                            order_type=OrderType.MARKET,
                            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                        )
                        order_id = self.broker.submit_order(order)
                        self._emit(ev_order(
                            str(order_id), signal.symbol, side.value, qty,
                        ))
                        self._pending_trade = {
                            "signal_time": bar.timestamp,
                            "side": side.value,
                            "planned_entry": signal.entry,
                            "planned_sl": signal.stop_loss,
                            "planned_tp": signal.take_profit,
                            "reason": signal.reason,
                            "qty": qty,
                            "symbol": signal.symbol,
                        }
                    else:
                        self._emit(ev_risk_block(
                            signal.symbol,
                            block_reason or "qty<=0",
                            bar.timestamp,
                        ))

            # 3. Equity snapshot.
            eq_now = self.broker.get_account().equity
            self.equity_curve.append((bar.timestamp, eq_now))
            self._emit(ev_bar(self.strategy.symbol, bar.timestamp, bar.close, eq_now))

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
        self._emit(ev_run_finished(self.run_id, ending, result.metrics))
        return result

    # ----------------------------------------------------------- helpers
    def _manage_open_trade(self, bar: Bar) -> None:
        """Per-bar trade management (T3 breakeven + partial TP, T4 time exit).

        Operates only on a fully filled trade. Safe to call when no trade is
        open (no-op).
        """
        if self._open_trade is None:
            return
        self._bars_held += 1
        entry = self._open_trade["entry_price"]
        sl = self._open_trade["planned_sl"]
        side = self._open_trade["side"]
        qty = self._open_trade["qty"]
        risk_per_unit = abs(entry - sl)
        if risk_per_unit <= 0:
            return

        # Current favorable excursion in R units (uses bar.close as mark).
        if side == "buy":
            r_now = (bar.close - entry) / risk_per_unit
        else:
            r_now = (entry - bar.close) / risk_per_unit

        # T3a: partial take profit at +partial_tp_r R.
        if (
            self.partial_tp_r > 0
            and not self._partial_done
            and r_now >= self.partial_tp_r
        ):
            close_qty = qty * self.partial_tp_frac
            fill = self.broker.partial_close(self.strategy.symbol, close_qty, bar)
            if fill is not None:
                self._partial_done = True
                gross = (
                    (fill.price - entry) * close_qty if side == "buy"
                    else (entry - fill.price) * close_qty
                )
                entry_fee_share = self._open_trade["entry_fee"] * (
                    close_qty / self._open_trade["qty"]
                )
                partial_pnl = gross - entry_fee_share - fill.fee
                partial_trade = {
                    "symbol": self._open_trade.get("symbol", self.strategy.symbol),
                    "signal_time": self._open_trade["signal_time"],
                    "entry_time": self._open_trade["entry_time"],
                    "entry_price": entry,
                    "entry_fee": entry_fee_share,
                    "exit_time": fill.timestamp,
                    "exit_price": fill.price,
                    "exit_fee": fill.fee,
                    "side": side,
                    "qty": close_qty,
                    "planned_entry": self._open_trade["planned_entry"],
                    "planned_sl": sl,
                    "planned_tp": self._open_trade["planned_tp"],
                    "reason": self._open_trade["reason"] + " | partial_tp",
                    "gross_pnl": gross,
                    "pnl": partial_pnl,
                    "r": (
                        partial_pnl / (risk_per_unit * close_qty)
                        if risk_per_unit > 0 else 0.0
                    ),
                    "is_partial": True,
                }
                self.trades.append(partial_trade)
                # Reduce remaining open trade size + entry fee.
                self._open_trade["qty"] = qty - close_qty
                self._open_trade["entry_fee"] = (
                    self._open_trade["entry_fee"] - entry_fee_share
                )
                self._emit(ev_trade_closed(
                    partial_trade["symbol"], side, entry, fill.price,
                    close_qty, partial_pnl, partial_trade["r"], fill.timestamp,
                ))

        # T3b: move stop to breakeven once +breakeven_after_r R.
        if (
            self.breakeven_after_r > 0
            and not self._breakeven_done
            and r_now >= self.breakeven_after_r
        ):
            if self.broker.modify_stop(self.strategy.symbol, entry):
                self._open_trade["planned_sl"] = entry
                self._breakeven_done = True

        # T4: hard time-based exit.
        if self.max_hold_bars > 0 and self._bars_held >= self.max_hold_bars:
            pos = self.broker.get_position(self.strategy.symbol)
            if pos is not None:
                exit_side = Side.SELL if pos.qty > 0 else Side.BUY
                close_order = Order(
                    symbol=self.strategy.symbol, side=exit_side,
                    qty=abs(pos.qty), order_type=OrderType.MARKET,
                )
                self.broker.submit_order(close_order)
                synthetic = Bar(bar.timestamp, bar.close, bar.close,
                                bar.close, bar.close, 0.0)
                for fill in self.broker.on_bar(self.strategy.symbol, synthetic):
                    self._handle_fill(fill, synthetic)

    def _handle_fill(self, fill: Fill, bar: Bar | None = None) -> None:
        role = self.broker.fill_role(fill)
        self._emit(ev_fill(
            getattr(fill, "order_id", ""), fill.symbol,
            fill.side.value if hasattr(fill.side, "value") else str(fill.side),
            fill.qty, fill.price, fill.fee, role, fill.timestamp,
        ))
        # Partial exits are booked in _manage_open_trade; ignore here.
        if role == "partial_exit":
            return
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
            self._bars_held = 0
            self._partial_done = False
            self._breakeven_done = False
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
        trade = {
            **self._open_trade,
            "exit_time": fill.timestamp,
            "exit_price": fill.price,
            "exit_fee": fill.fee,
            "gross_pnl": gross,
            "pnl": net_pnl,                  # NET of fees
            "r": r_multiple,
        }
        trade.setdefault("symbol", self.strategy.symbol)
        self.trades.append(trade)
        self._emit(ev_trade_closed(
            trade["symbol"], side, entry_px, fill.price,
            qty, net_pnl, r_multiple, fill.timestamp,
        ))
        self.risk.on_trade_closed(net_pnl, fill.timestamp)
        self._open_trade = None
        self._bars_held = 0
        self._partial_done = False
        self._breakeven_done = False

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
            self._handle_fill(fill, synthetic)
        # Update last equity point so the final equity reflects the close.
        if self.equity_curve:
            self.equity_curve[-1] = (last_bar.timestamp,
                                     self.broker.get_account().equity)

    def _metrics(self, start: float, end: float) -> dict:
        table = _BARS_PER_YEAR_RTH if self.market == "rth" else _BARS_PER_YEAR_24_7
        ann = table.get(self.timeframe, 24 * 365)
        return expand_metrics(start, end, self.equity_curve, self.trades, ann)
