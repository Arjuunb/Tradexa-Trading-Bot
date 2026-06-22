"""Order fill models for the paper engine.

The paper engine fills perfectly by default. ``RealisticFill`` makes fills pay
the cost of trading — half-spread + slippage + latency drift moves the fill
price against you, orders can partially fill, and a small fraction are rejected.

Injected into ``PaperExecutionEngine`` so the live paper engine can run with
realistic execution; the default ``PerfectFill`` keeps existing behaviour (and
tests) unchanged.
"""
from __future__ import annotations

import os
import random


class PerfectFill:
    name = "perfect"

    def apply(self, action: str, price: float, size: float, **_) -> dict:
        return {"price": price, "size": size, "rejected": False,
                "filled_fraction": 1.0, "cost_pct": 0.0}

    def status(self) -> dict:
        return {"model": self.name, "note": "Ideal fills — no spread/slippage/rejection."}


class RealisticFill:
    name = "realistic"

    def __init__(self, *, spread_pct: float = 0.0004, slippage_pct: float = 0.0003,
                 latency_pct: float = 0.0001, partial_fill_prob: float = 0.0,
                 partial_fraction: float = 0.6, reject_prob: float = 0.0, seed: int = 1):
        self.spread_pct = float(spread_pct)
        self.slippage_pct = float(slippage_pct)
        self.latency_pct = float(latency_pct)
        self.partial_fill_prob = float(partial_fill_prob)
        self.partial_fraction = float(partial_fraction)
        self.reject_prob = float(reject_prob)
        self._rnd = random.Random(int(seed))

    @property
    def cost_pct(self) -> float:
        return self.spread_pct / 2 + self.slippage_pct + self.latency_pct

    def apply(self, action: str, price: float, size: float, *,
              allow_reject: bool = True, allow_partial: bool = True) -> dict:
        """``action`` ∈ {buy, sell}. Buys fill higher, sells fill lower."""
        cost = self.cost_pct
        if allow_reject and self.reject_prob and self._rnd.random() < self.reject_prob:
            return {"price": price, "size": 0.0, "rejected": True,
                    "filled_fraction": 0.0, "cost_pct": cost}
        fill_price = price * (1 + cost) if action == "buy" else price * (1 - cost)
        frac = 1.0
        if allow_partial and self.partial_fill_prob and self._rnd.random() < self.partial_fill_prob:
            frac = self.partial_fraction
        return {"price": round(fill_price, 8), "size": round(size * frac, 10),
                "rejected": False, "filled_fraction": frac, "cost_pct": cost}

    def status(self) -> dict:
        return {"model": self.name, "spread_pct": self.spread_pct, "slippage_pct": self.slippage_pct,
                "latency_pct": self.latency_pct, "partial_fill_prob": self.partial_fill_prob,
                "reject_prob": self.reject_prob, "round_trip_cost_pct": round(self.cost_pct * 2 * 100, 4),
                "note": "Spread + slippage + latency move the fill against you; orders may partial-fill or reject."}


def from_env():
    """Build a fill model from env (HUB_FILL_MODEL=realistic enables friction)."""
    if os.environ.get("HUB_FILL_MODEL", "").lower() in ("realistic", "real", "1", "true"):
        return RealisticFill(
            spread_pct=float(os.environ.get("HUB_FILL_SPREAD_PCT", 0.0004)),
            slippage_pct=float(os.environ.get("HUB_FILL_SLIPPAGE_PCT", 0.0003)),
            partial_fill_prob=float(os.environ.get("HUB_FILL_PARTIAL_PROB", 0.0)),
            reject_prob=float(os.environ.get("HUB_FILL_REJECT_PROB", 0.0)))
    return PerfectFill()
