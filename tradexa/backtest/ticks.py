"""Tick-level simulation, and honesty about where the ticks come from.

A bar backtest answers "did price touch my stop during this hour?" with a
guess, because a bar records four prices and no order. Tick simulation replaces
the guess — but only if the ticks are real.

**Synthesised ticks are labelled as synthesised, everywhere.** ``synthesise``
expands an OHLCV bar into a plausible path, and every ``Tick`` it produces
carries ``synthetic=True``, every ``TickStream`` built from bars reports
``is_synthetic``, and any result derived from one is expected to say so. A
synthetic path is a real improvement on a bar — it fixes the same-bar
stop-and-target ambiguity deterministically instead of by a coin flip — and it
is emphatically not tick data. Reporting a backtest on invented ticks as
"tick-accurate" is the most flattering lie a backtester can tell.

The path is deterministic and conservative:

    up bar   (close ≥ open):  open → low → high → close
    down bar (close < open):  open → high → low → close

The adverse extreme is visited FIRST in both cases. That is the pessimistic
reading — a long is taken to its stop before its target — and it matches the
``sl_first`` tie-break the bar backtester already applies, so the two engines
resolve the same ambiguity the same way rather than disagreeing about a trade
neither can see inside.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Iterator, Optional, Protocol, Sequence, runtime_checkable

from bot.types import Bar


@dataclass(frozen=True)
class Tick:
    """One observation of price. Real or synthesised, and it says which."""

    timestamp: datetime
    price: float
    volume: float = 0.0
    bid: Optional[float] = None
    ask: Optional[float] = None
    #: False only for ticks that came from a real trade feed.
    synthetic: bool = True

    @property
    def mid(self) -> float:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return self.price

    @property
    def spread(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


@runtime_checkable
class TickSource(Protocol):
    """Anything that can produce ticks. A real feed satisfies this too."""

    is_synthetic: bool

    def __iter__(self) -> Iterator[Tick]:
        ...


def synthesise(bar: Bar, *, steps: int = 4,
               spread_pct: float = 0.0) -> list[Tick]:
    """Expand one bar into a deterministic intrabar path.

    ``steps`` above 4 interpolates between the four anchors, which produces a
    smoother path and NOT more information — the extra points are invented from
    the same four numbers. Useful for exercising a queue model at finer
    granularity; useless as evidence about what price did.
    """
    if bar.high < bar.low:
        raise ValueError(f"bar high {bar.high} is below low {bar.low}")
    rising = bar.close >= bar.open
    # Adverse extreme first — see the module docstring.
    anchors = ([bar.open, bar.low, bar.high, bar.close] if rising
               else [bar.open, bar.high, bar.low, bar.close])

    path: list[float] = []
    if steps <= len(anchors):
        path = anchors[:max(2, steps)]
    else:
        per_leg = max(1, (steps - 1) // (len(anchors) - 1))
        for i in range(len(anchors) - 1):
            start, end = anchors[i], anchors[i + 1]
            for step in range(per_leg):
                path.append(start + (end - start) * step / per_leg)
        path.append(anchors[-1])

    # Volume split evenly. A volume profile weighted towards the extremes would
    # look more realistic and would be fabricated — the bar records one total
    # and says nothing about its distribution.
    slice_volume = (bar.volume or 0.0) / len(path)
    span = timedelta(0)
    ticks: list[Tick] = []
    for index, price in enumerate(path):
        half = price * spread_pct / 2.0 if spread_pct else 0.0
        ticks.append(Tick(
            timestamp=bar.timestamp + span * index,
            price=price, volume=slice_volume,
            bid=price - half if spread_pct else None,
            ask=price + half if spread_pct else None,
            synthetic=True))
    return ticks


class SyntheticTickStream:
    """Ticks derived from bars. ``is_synthetic`` is True and stays True."""

    is_synthetic = True

    def __init__(self, bars: Sequence[Bar], *, steps: int = 4,
                 spread_pct: float = 0.0) -> None:
        self.bars = list(bars)
        self.steps = steps
        self.spread_pct = spread_pct

    def __iter__(self) -> Iterator[Tick]:
        for bar in self.bars:
            yield from synthesise(bar, steps=self.steps, spread_pct=self.spread_pct)

    def __len__(self) -> int:
        return len(self.bars) * max(2, self.steps)


class RecordedTickStream:
    """Real ticks from a feed or a capture file.

    The only stream that may report ``is_synthetic = False``, and it takes the
    ticks as given rather than deriving anything — a stream that "fills gaps" in
    recorded data has stopped being recorded data.
    """

    is_synthetic = False

    def __init__(self, ticks: Iterable[Tick]) -> None:
        self._ticks = [t if not t.synthetic else
                       Tick(t.timestamp, t.price, t.volume, t.bid, t.ask, False)
                       for t in ticks]

    def __iter__(self) -> Iterator[Tick]:
        return iter(self._ticks)

    def __len__(self) -> int:
        return len(self._ticks)


@dataclass
class BarAggregator:
    """Ticks back into bars, for comparing the two simulations.

    Exists so a tick run and a bar run can be shown to describe the same market:
    aggregating the synthesised ticks must reproduce the original OHLC exactly.
    If it does not, the tick path is not a decomposition of the bar and any
    difference in results is the synthesiser's, not the market's.
    """

    period: timedelta
    _open: Optional[float] = field(default=None, init=False)
    _high: float = field(default=float("-inf"), init=False)
    _low: float = field(default=float("inf"), init=False)
    _close: float = field(default=0.0, init=False)
    _volume: float = field(default=0.0, init=False)
    _start: Optional[datetime] = field(default=None, init=False)

    def push(self, tick: Tick) -> Optional[Bar]:
        """Add a tick; returns a completed bar when the period rolls over."""
        completed = None
        if self._start is None:
            self._start = tick.timestamp
        elif tick.timestamp - self._start >= self.period:
            completed = self.flush()
            self._start = tick.timestamp
        if self._open is None:
            self._open = tick.price
        self._high = max(self._high, tick.price)
        self._low = min(self._low, tick.price)
        self._close = tick.price
        self._volume += tick.volume
        return completed

    def flush(self) -> Optional[Bar]:
        if self._open is None or self._start is None:
            return None
        bar = Bar(self._start, self._open, self._high, self._low, self._close,
                  self._volume)
        self._open, self._high, self._low = None, float("-inf"), float("inf")
        self._volume = 0.0
        return bar


__all__ = ["Tick", "TickSource", "synthesise", "SyntheticTickStream",
           "RecordedTickStream", "BarAggregator"]
