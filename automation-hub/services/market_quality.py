"""Market-quality gate (Phase 1) — a fail-closed pre-trade safety check.

Inspired by the "degraded state -> VETO" pattern, but stdlib-only and aimed at
the data we actually have. It blocks a trade BEFORE risk/execution when the
inputs look unsafe or the market is untradeable:

    * non-finite / non-positive entry or stop (NaN, inf, <= 0, bad data)
    * absurd stop distance — too tight (would size a huge position) or too wide
      (almost certainly bad data); the tight check is real capital protection
    * crossed order book (bid >= ask) — always rejected when a book is supplied
    * spread too wide / stale signal — OPTIONAL, active only when that data is
      provided and a threshold is set (ready for a live L2 feed; inert until then)

Design: STRONG = conservative. Any exception -> VETO (fail closed). Optional
checks never *weaken* safety — they only add rejections when their data exists.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class QualityVerdict:
    ok: bool
    reason: str = ""


@dataclass
class MarketQualityConfig:
    min_stop_distance_pct: float = 0.0005   # 0.05% — tighter => oversize risk
    max_stop_distance_pct: float = 0.25     # 25%   — wider  => likely bad data
    max_signal_age_s: float = 0.0           # 0 disables (live-only)
    max_spread_bps: float = 0.0             # 0 disables (crossed book always checked)


def _finite_pos(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x) and x > 0


class MarketQualityGate:
    def __init__(self, config: Optional[MarketQualityConfig] = None):
        self.cfg = config or MarketQualityConfig()

    def check(self, *, entry, stop=None, timestamp=None,
              bid=None, ask=None, spread_bps=None, now=None) -> QualityVerdict:
        cfg = self.cfg
        try:
            # 1. entry must be a sane, positive, finite price
            if not _finite_pos(entry):
                return QualityVerdict(False, f"Invalid entry price ({entry})")

            # 2. stop distance sanity — only when a real, distinct stop is given
            #    (a missing or entry-equal stop is owned by the risk step).
            if stop is not None:
                if not (isinstance(stop, (int, float)) and math.isfinite(stop)):
                    return QualityVerdict(False, f"Invalid stop price ({stop})")
                if stop > 0 and stop != entry:
                    pct = abs(entry - stop) / entry
                    if pct < cfg.min_stop_distance_pct:
                        return QualityVerdict(
                            False, f"Stop too tight ({pct * 100:.3f}% < "
                                   f"{cfg.min_stop_distance_pct * 100:.3f}%) — oversize risk")
                    if pct > cfg.max_stop_distance_pct:
                        return QualityVerdict(
                            False, f"Stop too wide ({pct * 100:.1f}% > "
                                   f"{cfg.max_stop_distance_pct * 100:.0f}%) — likely bad data")

            # 3. order-book integrity (always when a book is supplied)
            if bid is not None and ask is not None:
                if not (_finite_pos(bid) and _finite_pos(ask)):
                    return QualityVerdict(False, "Invalid order book (bid/ask)")
                if bid >= ask:
                    return QualityVerdict(False, f"Crossed book (bid {bid} >= ask {ask})")
                if cfg.max_spread_bps > 0:
                    sb = (ask - bid) / bid * 10000.0
                    if sb > cfg.max_spread_bps:
                        return QualityVerdict(False, f"Spread too wide ({sb:.1f}bps > "
                                                     f"{cfg.max_spread_bps:.0f}bps)")
            elif spread_bps is not None and cfg.max_spread_bps > 0:
                if not (isinstance(spread_bps, (int, float)) and math.isfinite(spread_bps) and spread_bps >= 0):
                    return QualityVerdict(False, f"Invalid spread ({spread_bps})")
                if spread_bps > cfg.max_spread_bps:
                    return QualityVerdict(False, f"Spread too wide ({spread_bps:.1f}bps)")

            # 4. signal staleness (live-only; disabled by default)
            if cfg.max_signal_age_s > 0 and timestamp is not None:
                age = self._age_seconds(timestamp, now)
                if age is not None and age > cfg.max_signal_age_s:
                    return QualityVerdict(False, f"Stale signal ({age:.0f}s > "
                                                 f"{cfg.max_signal_age_s:.0f}s)")

            return QualityVerdict(True, "market quality ok")
        except Exception as e:  # noqa: BLE001 — fail closed on anything unexpected
            return QualityVerdict(False, f"Quality check error: {e}")

    @staticmethod
    def _age_seconds(timestamp, now) -> Optional[float]:
        try:
            if isinstance(timestamp, str):
                ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            elif isinstance(timestamp, datetime):
                ts = timestamp
            else:
                return None
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ((now or datetime.now(timezone.utc)) - ts).total_seconds()
        except Exception:  # noqa: BLE001 — unparseable timestamp -> skip age check
            return None
