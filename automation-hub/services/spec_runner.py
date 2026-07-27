"""The one place a strategy spec is turned into a backtest.

"One engine, everywhere" is the central claim of this system: the number the
marketplace publishes, the number the review scores, the number the tuner
measures and the baseline the monitor compares against must all mean the same
thing, or none of them mean anything.

That claim was true but fragile — five call sites each wired up ``get_bars`` →
``TradeBrain`` → ``simulate`` themselves, with the quality-filter default and the
min-score default copy-pasted into each. Nothing stopped one of them drifting.
This module is that wiring, once. The callers keep their own shapes (some take a
bar count, some a range key, the sweep takes a symbol/timeframe pair) but all of
them route through ``run_spec``.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_TIMEFRAME = "4h"
DEFAULT_MIN_SCORE = 60


def run_spec_with_bars(spec: dict, bars: int, *, symbol: Optional[str] = None,
                       timeframe: Optional[str] = None) -> tuple:
    """``(results, rows)`` — the backtest and the candles it was actually fed.

    The sweep needs the rows to verify that the data source honoured the
    requested timeframe (comparing a series against itself would fabricate a
    "best timeframe"), so they are returned rather than smuggled into the result
    dict, which several endpoints serialise straight to JSON."""
    from data.market_data import get_bars
    from strategies.brain import TradeBrain
    from strategies.custom import simulate

    sym = symbol or spec.get("symbol") or DEFAULT_SYMBOL
    tf = timeframe or spec.get("timeframe") or DEFAULT_TIMEFRAME
    run = spec if (symbol is None and timeframe is None) else {
        **spec, "symbol": sym, "timeframe": tf}

    rows, _src = get_bars(sym, n=bars, timeframe=tf)
    if not rows:
        return None, []
    # The quality filter is ON unless the spec turns it off — the same default
    # the live engine uses, so a backtest is not quietly easier than reality.
    use_brain = run.get("quality_filter", True)
    res = simulate(run, rows, brain=TradeBrain() if use_brain else None,
                   min_score=int(run.get("min_score", DEFAULT_MIN_SCORE)) if use_brain else 0)
    return res, rows


def run_spec(spec: dict, bars: int, *, symbol: Optional[str] = None,
             timeframe: Optional[str] = None) -> Optional[dict]:
    """Run ``spec`` over ``bars`` candles through the existing simulate path.

    ``symbol``/``timeframe`` override the spec's own, which is what a sweep cell
    needs — the cell is the spec run somewhere else, not a different spec.
    Returns None when there is no data, so a caller reports "no result" rather
    than presenting an empty backtest as a finished one."""
    return run_spec_with_bars(spec, bars, symbol=symbol, timeframe=timeframe)[0]


def make_runner(bars_for_range, range_key: str) -> Callable[[dict], Optional[dict]]:
    """``runner(spec) -> results`` over a named window. Used by the tuner, the
    publisher and the monitoring agent's baseline."""
    def _run(spec: dict):
        tf = spec.get("timeframe") or DEFAULT_TIMEFRAME
        return run_spec(spec, bars_for_range(tf, range_key))
    return _run


def make_cell_runner(bars_for_range, range_key: str,
                     verify_timeframe=None) -> Callable[[dict, str, str], Any]:
    """``runner(spec, symbol, timeframe) -> results`` for a sweep grid.

    ``verify_timeframe(rows, timeframe) -> bool`` tags each result with whether
    the feed really delivered the requested candle size. Without it a source that
    ignores the timeframe argument would let the sweep rank a series against
    itself and report a "best timeframe" that is an artefact."""
    def _run(spec: dict, symbol: str, timeframe: str):
        res, rows = run_spec_with_bars(spec, bars_for_range(timeframe, range_key),
                                       symbol=symbol, timeframe=timeframe)
        if isinstance(res, dict) and verify_timeframe is not None:
            res["__tf_verified"] = verify_timeframe(rows, timeframe)
        return res
    return _run
