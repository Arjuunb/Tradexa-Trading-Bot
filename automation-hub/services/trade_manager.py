"""Trade management — break-even, scale-out and trailing stops.

The three standard mid-trade moves, as pure logic shared by the backtest
simulator and the live paper engine (one behavior everywhere):

    break-even   — once a trade is +``be_at_r``, the stop moves to entry
    scale-out    — bank ``scale_frac`` of the position at +``scale_at_r``
    trailing     — keep the stop ``trail_r`` behind the best price, optionally
                   armed only after the trade has run ``trail_after_r``

All levels are expressed in R (multiples of the entry risk), so the behavior
adapts to each trade's own stop distance. Checks are conservative: the stop is
evaluated against the bar BEFORE it is moved, and a bar that touches both stop
and target counts as the stop (same pessimistic rule the simulators use).

EVERYTHING IS OFF BY DEFAULT — and that is a measured decision, not an
oversight. Tested out-of-sample across 50 regime scenarios with realistic
fills against the Decision Brain's plain 3R exit (net +175.3R):

    break-even at 1R                 +96.3R   (winners retrace to entry first)
    scale 50% at 1.5R               +124.8R   (caps the 3R runs that pay for losers)
    break-even at 2R                +155.0R
    trail 1R armed at 2.5R          +101.4R   (>1R pullbacks are normal en route to 3R)
    BE 1R + scale 1.5R + trail 1R    +28.2R   (the classic retail combo — worst of all)

Every early-exit rule truncated the big winners more than it saved on losers.
Enable a config here only after validating it on real market data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ManagedTrade:
    """Mutable management state for one open position."""
    side: str                 # "long" | "short"
    entry: float
    stop: float
    target: float
    risk: float               # |entry - original stop|
    be: bool = False          # stop moved to break-even?
    scaled: bool = False      # partial profit taken?
    best: float = field(default=0.0)  # most favorable price seen

    def __post_init__(self):
        if not self.best:
            self.best = self.entry


@dataclass
class Action:
    """What the engine should do on this bar (at most one exit + stop moves)."""
    exit_price: Optional[float] = None    # full exit level hit (stop or target)
    exit_reason: str = ""
    partial_price: Optional[float] = None  # scale-out fill level (fraction of size)
    stop_moved_to: Optional[float] = None  # new stop after BE / trailing


class TradeManager:
    """Applies break-even / scale-out / trailing to a ManagedTrade, bar by bar.

    ``be_at_r``    move stop to entry once the trade reaches this many R.
    ``scale_at_r`` take ``scale_frac`` of the position off at this many R.
    ``trail_r``    after scaling out, keep the stop this many R behind the
                   best price seen (0 disables trailing).
    Any level set to 0 disables that behavior.
    """

    def __init__(self, *, be_at_r: float = 0, scale_at_r: float = 0,
                 scale_frac: float = 0.5, trail_r: float = 0.0,
                 trail_after_r: float = 0.0):
        self.be_at_r = float(be_at_r)
        self.scale_at_r = float(scale_at_r)
        self.scale_frac = min(max(float(scale_frac), 0.0), 0.9)
        self.trail_r = float(trail_r)
        self.trail_after_r = float(trail_after_r)

    def on_bar(self, t: ManagedTrade, high: float, low: float) -> Action:
        act = Action()
        sign = 1.0 if t.side == "long" else -1.0
        fav_px = high if t.side == "long" else low     # best price this bar
        adv_px = low if t.side == "long" else high     # worst price this bar

        # 1. stop first, against the CURRENT stop (pessimistic intrabar rule)
        if (adv_px - t.stop) * sign <= 0:
            act.exit_price, act.exit_reason = t.stop, "stop"
            return act

        # 2. scale-out at +scale_at_r (before the runner target)
        if (self.scale_at_r > 0 and self.scale_frac > 0 and not t.scaled):
            level = t.entry + sign * self.scale_at_r * t.risk
            if (fav_px - level) * sign >= 0 and (level - t.target) * sign < 0:
                t.scaled = True
                act.partial_price = level

        # 3. full target for the (remaining) position
        if (fav_px - t.target) * sign >= 0:
            act.exit_price, act.exit_reason = t.target, "target"
            return act

        # 4. break-even: once +be_at_r, the trade can no longer become a loss
        t.best = fav_px if (fav_px - t.best) * sign > 0 else t.best
        if self.be_at_r > 0 and not t.be:
            if (t.best - t.entry) * sign >= self.be_at_r * t.risk:
                t.be = True
                if (t.entry - t.stop) * sign > 0:
                    t.stop = t.entry
                    act.stop_moved_to = t.stop

        # 5. trailing (for the runner once profit is banked, or from the start
        #    when scale-out is disabled). ``trail_after_r`` arms the trail only
        #    once the trade has already run that far — a giveback stop that
        #    protects a near-target winner without strangling a young trade.
        armed = (t.best - t.entry) * sign >= self.trail_after_r * t.risk
        if self.trail_r > 0 and armed and (t.scaled or self.scale_at_r <= 0):
            trailed = t.best - sign * self.trail_r * t.risk
            if (trailed - t.stop) * sign > 0:
                t.stop = trailed
                act.stop_moved_to = t.stop

        return act

    def r_multiple(self, t: ManagedTrade, exit_price: float,
                   partial_price: Optional[float] = None,
                   cost_r: float = 0.0) -> float:
        """Blended R for the whole trade: the scaled fraction banked at the
        partial level plus the remainder at the final exit, minus costs."""
        sign = 1.0 if t.side == "long" else -1.0
        final_r = (exit_price - t.entry) * sign / t.risk
        if partial_price is None and not t.scaled:
            return final_r - cost_r
        part = (partial_price if partial_price is not None
                else t.entry + sign * self.scale_at_r * t.risk)
        part_r = (part - t.entry) * sign / t.risk
        return (self.scale_frac * part_r + (1.0 - self.scale_frac) * final_r) - cost_r
