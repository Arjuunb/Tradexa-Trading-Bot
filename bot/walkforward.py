"""Walk-forward validation.

Splits a bar series into rolling (train, test) windows. A user-supplied
``build_strategy`` callable instantiates a fresh strategy for each window,
optionally using the train slice to choose parameters; the test slice is then
backtested out-of-sample.

This is the standard quant-trading technique for catching overfitting: any
strategy whose performance evaporates between train and test is rejected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from bot.backtester import Backtester, BacktestResult
from bot.risk import RiskConfig, RiskManager
from bot.strategies.base import Strategy
from bot.types import Bar


BuildStrategy = Callable[[Sequence[Bar]], Strategy]
"""Factory: receives the TRAIN bars, returns a tuned strategy. Often it just
ignores the train slice and returns a default strategy."""


@dataclass
class WalkForwardWindow:
    train_start: int
    train_end: int  # exclusive
    test_start: int
    test_end: int   # exclusive
    result: BacktestResult


@dataclass
class WalkForwardReport:
    windows: list[WalkForwardWindow]

    def is_robust(self, min_sharpe: float = 0.5,
                  max_dd: float = -0.20) -> bool:
        """A coarse robustness check: every test window must beat thresholds."""
        for w in self.windows:
            m = w.result.metrics
            if m.get("sharpe", 0) < min_sharpe or m.get("max_dd", 0) < max_dd:
                return False
        return True

    def summary(self) -> str:
        lines = [
            f"Walk-forward windows: {len(self.windows)}",
            "  #  train_bars  test_bars  trades   ret     sharpe   dd",
        ]
        for i, w in enumerate(self.windows):
            m = w.result.metrics
            lines.append(
                f"  {i:>2}  {w.train_end - w.train_start:>10d}  "
                f"{w.test_end - w.test_start:>9d}  "
                f"{m.get('num_trades', 0):>6d}  "
                f"{m.get('total_return', 0):>6.2%}  "
                f"{m.get('sharpe', 0):>7.2f}  "
                f"{m.get('max_dd', 0):>6.2%}"
            )
        return "\n".join(lines)


def walk_forward(
    bars: Sequence[Bar],
    build_strategy: BuildStrategy,
    train_bars: int,
    test_bars: int,
    step: int | None = None,
    risk: RiskConfig | None = None,
    starting_cash: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
    timeframe: str = "1h",
    market: str = "24_7",
) -> WalkForwardReport:
    """Run a rolling walk-forward backtest.

    Each iteration:
        1. Slice ``bars[train_start:train_end]`` and call ``build_strategy``.
        2. Backtest the resulting strategy against ``bars[test_start:test_end]``.
        3. Advance both windows by ``step`` (default = test_bars; non-overlapping).
    """
    if train_bars < 1 or test_bars < 1:
        raise ValueError("train_bars and test_bars must be >= 1")
    step = step or test_bars
    if step < 1:
        raise ValueError("step must be >= 1")
    n = len(bars)
    windows: list[WalkForwardWindow] = []
    train_start = 0
    while train_start + train_bars + test_bars <= n:
        train_end = train_start + train_bars
        test_start = train_end
        test_end = test_start + test_bars
        strat = build_strategy(bars[train_start:train_end])
        bt = Backtester(
            strategy=strat,
            bars=list(bars[test_start:test_end]),
            starting_cash=starting_cash,
            fee_bps=fee_bps, slippage_bps=slippage_bps,
            risk=RiskManager(risk) if risk is not None else None,
            timeframe=timeframe, market=market,
        )
        res = bt.run()
        windows.append(WalkForwardWindow(
            train_start=train_start, train_end=train_end,
            test_start=test_start, test_end=test_end,
            result=res,
        ))
        train_start += step
    return WalkForwardReport(windows=windows)
