"""Support & Resistance + strong rejection-candle strategy.

ZONE DETECTION
--------------
We identify swing highs / swing lows over a rolling window (default 50 bars).
A swing high is a bar whose high is the maximum of a +/- `pivot` window;
a swing low is the symmetric definition.

Nearby swings (within `cluster_pct` of each other) are merged into a single
"zone" with [low, high] bounds — the more touches, the stronger the zone.
Zones older than `max_zone_age` bars are dropped.

ENTRY RULES
-----------
LONG  — last closed bar's low pierces a support zone AND the bar is a strong
        bullish rejection (pin bar or bullish engulfing) AND close is back
        above the zone high.
SHORT — symmetric: pierces resistance, strong bearish rejection (pin / bearish
        engulfing), close back below zone low.

REJECTION CANDLE DEFINITIONS
----------------------------
Pin bar (bullish):  lower_wick >= 2 * body  AND  close > (open+close)/2 area near top.
Pin bar (bearish):  upper_wick >= 2 * body  AND  close < midpoint.
Bullish engulfing:  bar's body fully engulfs prior bar's body AND bar closes up
                    AND prior bar closed down.
Bearish engulfing:  symmetric.

RISK PER TRADE
--------------
Stop loss is placed just beyond the rejection candle's extreme (wick low for
longs, wick high for shorts) with a small buffer. Take profit is at
`rr_target` * risk distance (default 2R).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.strategies.base import Strategy
from bot.types import Bar, Signal, SignalType


@dataclass
class Zone:
    low: float
    high: float
    kind: str          # "support" or "resistance"
    touches: int = 1
    last_touch_idx: int = 0


class SupportResistanceRejection(Strategy):
    name = "sr_rejection"

    def __init__(
        self,
        symbol: str,
        pivot: int = 3,
        lookback: int = 100,
        cluster_pct: float = 0.0025,    # 0.25%
        max_zone_age: int = 300,
        rr_target: float = 2.0,
        sl_buffer_pct: float = 0.0005,  # 5 bps buffer beyond wick
        min_touches: int = 2,
    ):
        super().__init__(
            symbol,
            pivot=pivot, lookback=lookback, cluster_pct=cluster_pct,
            max_zone_age=max_zone_age, rr_target=rr_target,
            sl_buffer_pct=sl_buffer_pct, min_touches=min_touches,
        )
        self.zones: list[Zone] = []

    # --------------------------------------------------------------- pivots
    def _is_swing_high(self, i: int) -> bool:
        p = self.params["pivot"]
        if i < p or i + p >= len(self.bars):
            return False
        hi = self.bars[i].high
        for j in range(i - p, i + p + 1):
            if j == i:
                continue
            if self.bars[j].high >= hi:
                return False
        return True

    def _is_swing_low(self, i: int) -> bool:
        p = self.params["pivot"]
        if i < p or i + p >= len(self.bars):
            return False
        lo = self.bars[i].low
        for j in range(i - p, i + p + 1):
            if j == i:
                continue
            if self.bars[j].low <= lo:
                return False
        return True

    # ----------------------------------------------------------- zone mgmt
    def _update_zones(self) -> None:
        if len(self.bars) < self.params["pivot"] * 2 + 2:
            return
        # The pivot at index i is only *confirmed* once `pivot` bars have closed
        # to its right. Touch index is i, not len(bars)-1.
        i = len(self.bars) - self.params["pivot"] - 1
        if i < 0:
            return

        cluster = self.params["cluster_pct"]

        def merge(price: float, kind: str, touch_idx: int) -> None:
            for z in self.zones:
                if z.kind != kind:
                    continue
                mid = (z.low + z.high) / 2
                if mid > 0 and abs(price - mid) / mid <= cluster:
                    z.low = min(z.low, price * (1 - cluster / 2))
                    z.high = max(z.high, price * (1 + cluster / 2))
                    z.touches += 1
                    z.last_touch_idx = touch_idx
                    return
            self.zones.append(Zone(
                low=price * (1 - cluster / 2),
                high=price * (1 + cluster / 2),
                kind=kind,
                last_touch_idx=touch_idx,
            ))

        if self._is_swing_high(i):
            merge(self.bars[i].high, "resistance", i)
        if self._is_swing_low(i):
            merge(self.bars[i].low, "support", i)

        # drop stale zones
        cutoff = len(self.bars) - self.params["max_zone_age"]
        self.zones = [z for z in self.zones if z.last_touch_idx >= cutoff]

    # --------------------------------------------------------- candle tests
    @staticmethod
    def _body(b: Bar) -> float:
        return abs(b.close - b.open)

    def _bullish_pin(self, b: Bar) -> bool:
        rng = b.high - b.low
        if rng <= 0:
            return False
        body = self._body(b)
        lower_wick = min(b.open, b.close) - b.low
        upper_wick = b.high - max(b.open, b.close)
        # Long lower wick relative to body AND short upper wick AND close
        # in the upper third of the range (classic hammer shape).
        close_position = (b.close - b.low) / rng
        return (
            lower_wick >= 2 * body
            and lower_wick > upper_wick * 2
            and close_position >= 0.6
        )

    def _bearish_pin(self, b: Bar) -> bool:
        rng = b.high - b.low
        if rng <= 0:
            return False
        body = self._body(b)
        upper_wick = b.high - max(b.open, b.close)
        lower_wick = min(b.open, b.close) - b.low
        close_position = (b.close - b.low) / rng
        return (
            upper_wick >= 2 * body
            and upper_wick > lower_wick * 2
            and close_position <= 0.4
        )

    def _bullish_engulf(self) -> bool:
        if len(self.bars) < 2:
            return False
        prev, cur = self.bars[-2], self.bars[-1]
        return (
            prev.close < prev.open                # prior bearish
            and cur.close > cur.open              # current bullish
            and cur.close >= prev.open
            and cur.open <= prev.close
        )

    def _bearish_engulf(self) -> bool:
        if len(self.bars) < 2:
            return False
        prev, cur = self.bars[-2], self.bars[-1]
        return (
            prev.close > prev.open
            and cur.close < cur.open
            and cur.open >= prev.close
            and cur.close <= prev.open
        )

    # ------------------------------------------------------------ generate
    def generate(self, bar: Bar) -> Optional[Signal]:
        self._update_zones()
        if not self.zones:
            return None

        min_touches = self.params["min_touches"]
        buf = self.params["sl_buffer_pct"]
        rr = self.params["rr_target"]

        # LONG setup: piercing support + bullish rejection + close back inside
        for z in self.zones:
            if z.kind != "support" or z.touches < min_touches:
                continue
            if bar.low <= z.high and bar.close > z.high:
                if self._bullish_pin(bar) or self._bullish_engulf():
                    entry = bar.close
                    stop = bar.low * (1 - buf)
                    risk = entry - stop
                    if risk <= 0:
                        continue
                    tp = entry + rr * risk
                    return Signal(
                        timestamp=bar.timestamp,
                        symbol=self.symbol,
                        type=SignalType.LONG,
                        entry=entry, stop_loss=stop, take_profit=tp,
                        reason=f"Bullish rejection at support {z.low:.4f}-{z.high:.4f} (touches={z.touches})",
                    )

        # SHORT setup
        for z in self.zones:
            if z.kind != "resistance" or z.touches < min_touches:
                continue
            if bar.high >= z.low and bar.close < z.low:
                if self._bearish_pin(bar) or self._bearish_engulf():
                    entry = bar.close
                    stop = bar.high * (1 + buf)
                    risk = stop - entry
                    if risk <= 0:
                        continue
                    tp = entry - rr * risk
                    return Signal(
                        timestamp=bar.timestamp,
                        symbol=self.symbol,
                        type=SignalType.SHORT,
                        entry=entry, stop_loss=stop, take_profit=tp,
                        reason=f"Bearish rejection at resistance {z.low:.4f}-{z.high:.4f} (touches={z.touches})",
                    )

        return None
