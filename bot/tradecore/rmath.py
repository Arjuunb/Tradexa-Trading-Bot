"""Canonical R (risk-multiple) accounting — one definition for every engine.

docs/TRADECORE_PLAN.md §R2: "R" is currently defined three ways —
  - gross move/risk        (execution/paper_engine.py:237)
  - net_pnl/risk_dollars   (bot/backtester.py:449)
  - R minus a cost_r term  (strategies/custom.py, services/replay.py)

These are the same quantity at two reporting stages: GROSS (before costs) and
NET (gross minus the round-trip cost in R). Defining both here, once, lets every
engine report the same number.
"""
from __future__ import annotations

_LONG = ("long", "buy", "b", "l")


def _sign(side: str) -> float:
    return 1.0 if str(side).strip().lower() in _LONG else -1.0


def gross_r(entry: float, exit_price: float, risk: float, side: str) -> float:
    """Signed R before costs: (exit - entry) * dir / risk. 0 for non-positive
    risk (matches paper_engine._rr and the sim guards)."""
    if not risk or risk <= 0:
        return 0.0
    return (float(exit_price) - float(entry)) * _sign(side) / float(risk)


def net_r(entry: float, exit_price: float, risk: float, side: str,
          cost_r: float = 0.0) -> float:
    """R after the round-trip trading cost (pass a value from
    tradecore.costs.cost_r). Equals gross_r when cost_r is 0."""
    return gross_r(entry, exit_price, risk, side) - float(cost_r)
