"""Institutional-grade backtesting: the parts the bar engine cannot express.

The platform already has a working bar backtester (`bot/backtester.py`, with
slippage, commission and same-bar tie-breaks), walk-forward (`bot/walkforward.py`
and `services/backtest_lab`), Monte Carlo and multi-asset runs. This package
adds what was genuinely missing, and reuses the rest rather than restating it:

    ticks           tick simulation, honest about synthesised vs recorded
    microstructure  latency, order queue, liquidity-driven partial fills, spread
    benchmark       alpha, beta, capture ratios, information ratio
    report          professional HTML and PDF, with the assumptions on the page

The unifying claim is the brief's last line — results must match live trading.
That is not achieved by adding cost basis points; it is achieved by modelling
the things that decide WHETHER you traded: a queue you were behind, a bar whose
volume you exceeded, a price that moved during your latency.
"""
from tradexa.backtest.benchmark import (
    Comparison, alpha, beta, buy_and_hold, capture, compare, information_ratio,
    returns_of, tracking_error,
)
from tradexa.backtest.microstructure import (
    ExecutionModel, FRICTIONLESS, LIQUID_CRYPTO, LatencyModel, Liquidity,
    LiquidityCap, OrderQueue, QueuedOrder, SpreadModel, THIN_ALTCOIN, US_EQUITIES,
)
from tradexa.backtest.report import (
    BacktestReport, ReportSection, render_html, render_pdf,
)
from tradexa.backtest.ticks import (
    BarAggregator, RecordedTickStream, SyntheticTickStream, Tick, TickSource,
    synthesise,
)

__all__ = [
    "Tick", "TickSource", "synthesise", "SyntheticTickStream",
    "RecordedTickStream", "BarAggregator",
    "SpreadModel", "LatencyModel", "OrderQueue", "QueuedOrder", "LiquidityCap",
    "ExecutionModel", "Liquidity", "LIQUID_CRYPTO", "THIN_ALTCOIN",
    "US_EQUITIES", "FRICTIONLESS",
    "compare", "Comparison", "buy_and_hold", "alpha", "beta", "capture",
    "tracking_error", "information_ratio", "returns_of",
    "BacktestReport", "ReportSection", "render_html", "render_pdf",
]
