"""Multi-symbol backtester.

Feeds one PaperBroker many symbols' bars in strict chronological order, with
one Strategy per symbol. Risk limits (open-positions cap, daily-loss kill
switch, cooldown) are applied **across the whole portfolio**, so two symbols
share the same risk budget.

Design notes
------------
- All trades share one cash account \u2014 you cannot blow up symbol A's PnL
  without it affecting symbol B's risk envelope. That's the whole point of a
  portfolio simulation.
- Bars from different symbols may share a timestamp. We process them in stable
  order (the order the symbols appear in the constructor dict).
- The interleaver is a heap so it works in O(N log K) over total bars,
  K = number of symbols.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bot.brokers.paper import PaperBroker
from bot.data.indicators import atr as compute_atr
from bot.metrics import expand_metrics
from bot.risk import RiskManager
from bot.strategies.base import Strategy
from bot.types import Bar, Fill, Order, OrderType, Side, SignalType


_BARS_PER_YEAR_24_7 = {
    "1m": 60 * 24 * 365,
    "5m": 12 * 24 * 365,
    "15m": 4 * 24 * 365,
    "30m": 2 * 24 * 365,
    "1h": 24 * 365,
    "4h": 6 * 365,
    "1d": 365,
}
_BARS_PER_YEAR_RTH = {
    "1m": 60 * 6.5 * 252,
    "5m": 12 * 6.5 * 252,
    "15m": 4 * 6.5 * 252,
    "30m": 2 * 6.5 * 252,
    "1h": 6.5 * 252,
    "1d": 252,
}


@dataclass
class MultiBacktestResult:
    equity_curve: list[tuple[datetime, float]]
    trades: list[dict]
    starting_equity: float
    ending_equity: float
    metrics: dict = field(default_factory=dict)
    per_symbol: dict[str, dict] = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        out = [
            f"Symbols:        {', '.join(sorted(self.per_symbol.keys()))}",
            f"Start equity:   {self.starting_equity:,.2f}",
            f"End equity:     {self.ending_equity:,.2f}",
            f"Total return:   {m.get('total_return', 0):.2%}",
            f"CAGR:           {m.get('cagr', 0):.2%}",
            f"Trades:         {m.get('num_trades', 0)}",
            f"Win rate:       {m.get('win_rate', 0):.2%}",
            f"Profit factor:  {m.get('profit_factor', 0):.2f}",
            f"Sharpe (ann.):  {m.get('sharpe', 0):.2f}",
            f"Sortino (ann.): {m.get('sortino', 0):.2f}",
            f"Max drawdown:   {m.get('max_dd', 0):.2%}",
            "",
            "Per-symbol:",
        ]
        for sym, st in sorted(self.per_symbol.items()):
            out.append(f"  {sym}: trades={st['num_trades']:3d}  "
                       f"win%={st['win_rate']:.0%}  pnl={st['pnl']:,.2f}")
        return "\n".join(out)


class MultiSymbolBacktester:
    def __init__(
        self,
        strategies: dict[str, Strategy],
        bars: dict[str, list[Bar]],
        starting_cash: float = 10_000.0,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        risk: RiskManager | None = None,
        timeframe: str = "1h",
        market: str = "24_7",
        sl_first: bool = True,
    ):
        if starting_cash <= 0:
            raise ValueError("starting_cash must be > 0")
        missing = set(strategies) - set(bars)
        if missing:
            raise ValueError(f"No bars for strategy symbols: {sorted(missing)}")
        self.strategies = strategies
        self.bars = bars
        self.broker = PaperBroker(
            starting_cash=starting_cash,
            fee_bps=fee_bps, slippage_bps=slippage_bps,
            sl_first=sl_first,
        )
        self.risk = risk or RiskManager()
        self.timeframe = timeframe
        self.market = market
        self.equity_curve: list[tuple[datetime, float]] = []
        self.trades: list[dict] = []
        # bookkeeping per symbol
        self._pending: dict[str, Optional[dict]] = {s: None for s in strategies}
        self._open: dict[str, Optional[dict]] = {s: None for s in strategies}
        self._history: dict[str, list[Bar]] = {s: [] for s in strategies}

    # ------------------------------------------------------------------- run
    def run(self) -> MultiBacktestResult:
        starting = self.broker.get_account().equity

        # Interleave bars chronologically with a heap. Use (timestamp, idx, symbol, bar)
        # to keep insertion stable when timestamps tie.
        heap: list[tuple[datetime, int, str, Bar]] = []
        for sym, bs in self.bars.items():
            if bs:
                heap.append((bs[0].timestamp, 0, sym, bs[0]))
        heapq.heapify(heap)
        cursors = {sym: 0 for sym in self.bars}

        last_seen_ts: Optional[datetime] = None
        atr_period = self.risk.cfg.atr_period
        atr_enabled = self.risk.cfg.atr_stop_mult > 0

        while heap:
            ts, _, sym, bar = heapq.heappop(heap)

            # Per-bar risk housekeeping only on advancing wall-clock.
            if last_seen_ts is None or ts != last_seen_ts:
                self.risk.on_bar(self.broker.get_account().equity, ts)
                last_seen_ts = ts

            self._history[sym].append(bar)
            if atr_enabled and len(self._history[sym]) > atr_period:
                self.risk.update_atr(compute_atr(self._history[sym], atr_period))

            # 1. broker processes the bar
            for fill in self.broker.on_bar(sym, bar):
                self._handle_fill(sym, fill)

            # 2. strategy signal
            signal = self.strategies[sym].on_bar(bar)
            if signal and signal.type in (SignalType.LONG, SignalType.SHORT):
                in_pos = self.broker.get_position(sym) is not None
                if not in_pos and self._pending[sym] is None and self._open[sym] is None:
                    account = self.broker.get_account()
                    allow, qty, _ = self.risk.evaluate(signal, account, ts)
                    if allow and qty > 0:
                        side = Side.BUY if signal.type == SignalType.LONG else Side.SELL
                        order = Order(
                            symbol=sym, side=side, qty=qty,
                            order_type=OrderType.MARKET,
                            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                        )
                        self.broker.submit_order(order)
                        self._pending[sym] = {
                            "symbol": sym,
                            "signal_time": ts, "side": side.value,
                            "planned_entry": signal.entry,
                            "planned_sl": signal.stop_loss,
                            "planned_tp": signal.take_profit,
                            "reason": signal.reason, "qty": qty,
                        }

            # 3. snapshot equity (one point per wall-clock bar advance)
            self.equity_curve.append((ts, self.broker.get_account().equity))

            # advance cursor and push next bar from that symbol
            cursors[sym] += 1
            if cursors[sym] < len(self.bars[sym]):
                nb = self.bars[sym][cursors[sym]]
                heapq.heappush(heap, (nb.timestamp, cursors[sym], sym, nb))

        self._force_close_at_end()

        ending = self.broker.get_account().equity
        table = _BARS_PER_YEAR_RTH if self.market == "rth" else _BARS_PER_YEAR_24_7
        ann = table.get(self.timeframe, 24 * 365)
        metrics = expand_metrics(starting, ending, self.equity_curve, self.trades, ann)

        per_sym: dict[str, dict] = {}
        for sym in self.strategies:
            ts_ = [t for t in self.trades if t.get("symbol") == sym]
            wins = [t for t in ts_ if t["pnl"] > 0]
            per_sym[sym] = {
                "num_trades": len(ts_),
                "win_rate": (len(wins) / len(ts_)) if ts_ else 0.0,
                "pnl": sum(t["pnl"] for t in ts_),
            }

        return MultiBacktestResult(
            equity_curve=self.equity_curve,
            trades=self.trades,
            starting_equity=starting, ending_equity=ending,
            metrics=metrics, per_symbol=per_sym,
        )

    # --------------------------------------------------------------- helpers
    def _handle_fill(self, sym: str, fill: Fill) -> None:
        role = self.broker.fill_role(fill)
        if role == "entry":
            if self._pending[sym] is None:
                return
            self._open[sym] = {
                **self._pending[sym],
                "entry_time": fill.timestamp,
                "entry_price": fill.price,
                "entry_fee": fill.fee,
            }
            self._pending[sym] = None
            return
        if self._open[sym] is None:
            return
        op = self._open[sym]
        entry_px = op["entry_price"]
        qty = op["qty"]
        side = op["side"]
        gross = (fill.price - entry_px) * qty if side == "buy" else (entry_px - fill.price) * qty
        net = gross - op["entry_fee"] - fill.fee
        risk_dollars = abs(entry_px - op["planned_sl"]) * qty
        r = net / risk_dollars if risk_dollars > 0 else 0.0
        self.trades.append({
            **op,
            "exit_time": fill.timestamp,
            "exit_price": fill.price,
            "exit_fee": fill.fee,
            "gross_pnl": gross, "pnl": net, "r": r,
        })
        self.risk.on_trade_closed(net, fill.timestamp)
        self._open[sym] = None

    def _force_close_at_end(self) -> None:
        for sym, bs in self.bars.items():
            if not bs or self._open[sym] is None:
                continue
            last = bs[-1]
            pos = self.broker.get_position(sym)
            if pos is None:
                continue
            exit_side = Side.SELL if pos.qty > 0 else Side.BUY
            self.broker.submit_order(Order(symbol=sym, side=exit_side,
                                           qty=abs(pos.qty), order_type=OrderType.MARKET))
            synthetic = Bar(last.timestamp, last.close, last.close,
                            last.close, last.close, 0.0)
            for fill in self.broker.on_bar(sym, synthetic):
                self._handle_fill(sym, fill)
        if self.equity_curve:
            self.equity_curve[-1] = (self.equity_curve[-1][0],
                                     self.broker.get_account().equity)
