"""Canonical trade-cost math — one implementation for the whole platform.

Replaces the copy-pasted variants documented in docs/TRADECORE_PLAN.md §3a
(five, not four — custom.simulate's own copy surfaced during the S4.2 sweep):
  - services/replay.py           cost_r = fill_cost_pct * entry * 2 / risk
  - services/execution_sim.py    cost_r = cost_pct * entry * 2 / risk
  - backtest.py                  r -= cost * entry * 2 / risk
  - strategies/custom.py (simulate)          same symmetric form
  - strategies/custom.py (simulate_strategy) (entry_cost + cost) * entry / risk
…and the dollar form in execution/paper_engine.py:210:
  - _round_trip_fee = rate * size * (|entry| + |exit|)

All five are special cases of the two functions below (per-side costs, with a
symmetric default). tests/test_tradecore.py pins that equivalence.

Costs are expressed as a fraction of NOTIONAL per side (e.g. 0.0004 == 4 bps).
"""
from __future__ import annotations

# Canonical defaults. The realistic fill model (services/fill_model.py:38) and
# the research backtester (strategies/custom.py:670) already agree on these; the
# event-driven PaperBroker uses 5 bps / 2 bps (bot/brokers/paper.py:49) and is
# the documented outlier to reconcile in S4.6 — NOT silently changed here.
DEFAULT_FEE_PCT: float = 0.0004        # 4 bps taker, per side
DEFAULT_SLIPPAGE_PCT: float = 0.0002   # 2 bps, per side


def round_trip_cost_pct(fee_pct: float = DEFAULT_FEE_PCT,
                        slippage_pct: float = DEFAULT_SLIPPAGE_PCT) -> float:
    """Total per-side cost fraction (fee + slippage) — the scalar most engines
    call ``cost``/``cost_pct``. Round-trip is two of these (entry + exit)."""
    return float(fee_pct) + float(slippage_pct)


def cost_r(entry: float, risk: float, entry_cost_pct: float,
           exit_cost_pct: float | None = None) -> float:
    """Round-trip trading cost expressed in R (multiples of the trade's risk).

    Per-side by design: the entry and exit legs may charge different rates
    (maker entry / taker exit). With a symmetric rate this reduces to the
    familiar ``cost_pct * entry * 2 / risk``; asymmetric reproduces custom.py's
    ``(entry_cost + cost) * entry / risk``.

    ``risk`` is the price distance |entry - stop|; a non-positive risk yields 0
    (no defined R), matching the guards in the call sites being replaced.
    """
    if not risk or risk <= 0:
        return 0.0
    if exit_cost_pct is None:
        exit_cost_pct = entry_cost_pct
    return (float(entry_cost_pct) + float(exit_cost_pct)) * abs(float(entry)) / float(risk)


def cost_dollars(size: float, entry: float, exit_price: float,
                 entry_cost_pct: float, exit_cost_pct: float | None = None) -> float:
    """Round-trip commission in account currency: cost is charged on the entry
    notional and the exit notional independently. With a symmetric rate this is
    ``rate * size * (|entry| + |exit|)`` — paper_engine's round-trip fee."""
    if exit_cost_pct is None:
        exit_cost_pct = entry_cost_pct
    s = abs(float(size))
    return (float(entry_cost_pct) * s * abs(float(entry))
            + float(exit_cost_pct) * s * abs(float(exit_price)))
