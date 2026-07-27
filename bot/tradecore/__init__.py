"""TradeCore — the single source of truth for how every engine costs and
accounts for a trade (DSP Sprint 4).

Today the per-trade cost-in-R formula is copy-pasted across four files and "R"
is defined three incompatible ways (see docs/TRADECORE_PLAN.md §3). This package
holds ONE implementation of each, verified by tests/test_tradecore.py to
faithfully reproduce every engine's current inline math — so the later slices
that route each engine through here (S4.2/S4.3) are provably behavior-preserving.

Nothing here has callers yet; importing it changes no runtime behavior.
"""
from .costs import (
    DEFAULT_FEE_PCT,
    DEFAULT_SLIPPAGE_PCT,
    cost_dollars,
    cost_r,
    round_trip_cost_pct,
)
from .rmath import gross_r, net_r
from .trade_manager import Action, ManagedTrade, TradeManager

__all__ = [
    "DEFAULT_FEE_PCT", "DEFAULT_SLIPPAGE_PCT",
    "cost_r", "cost_dollars", "round_trip_cost_pct",
    "gross_r", "net_r",
    "Action", "ManagedTrade", "TradeManager",
]
