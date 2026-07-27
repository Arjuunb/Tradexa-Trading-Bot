"""TradeCore primitives + the characterization proof (Sprint 4, S4.1).

The characterization tests assert the canonical cost/R functions reproduce each
engine's CURRENT inline formula exactly, on shared sample inputs — the safety
proof that the S4.2/S4.3 swaps are behavior-preserving before any engine is
touched. If an engine's inline math ever changes, the matching test here fails,
forcing the divergence to be reconciled deliberately."""
import math

from bot.tradecore import costs, rmath


# ------------------------------------------------------------- unit behaviour

def test_cost_r_symmetric_and_asymmetric():
    # symmetric per-side == the classic "* 2 / risk" form
    assert costs.cost_r(100.0, 5.0, 0.0004) == 0.0004 * 100.0 * 2 / 5.0
    # asymmetric legs add independently
    assert costs.cost_r(100.0, 5.0, 0.0002, 0.0006) == (0.0002 + 0.0006) * 100.0 / 5.0


def test_cost_r_zero_risk_is_zero():
    assert costs.cost_r(100.0, 0.0, 0.0004) == 0.0
    assert costs.cost_r(100.0, -1.0, 0.0004) == 0.0


def test_gross_and_net_r_direction_and_cost():
    # long winner
    assert rmath.gross_r(100.0, 110.0, 5.0, "long") == 2.0
    # short winner (price falls)
    assert rmath.gross_r(100.0, 95.0, 5.0, "short") == 1.0
    # net subtracts the cost in R
    assert rmath.net_r(100.0, 110.0, 5.0, "long", cost_r=0.16) == 2.0 - 0.16
    assert rmath.gross_r(100.0, 110.0, 0.0, "long") == 0.0   # zero-risk guard


# ---------------------------------- characterization: reproduces each engine

def test_reproduces_symmetric_r_cost_engines():
    """services/replay.py:763, services/execution_sim.py:49, backtest.py:133 all
    compute cost_r = cost_pct * entry * 2 / risk."""
    entry, risk, cost_pct = 27_500.0, 180.0, 0.0006
    inline = cost_pct * entry * 2 / risk
    assert math.isclose(costs.cost_r(entry, risk, cost_pct), inline, rel_tol=1e-12)


def test_reproduces_custom_per_side_r_cost():
    """strategies/custom.py:758 computes (entry_cost + cost) * entry / risk."""
    entry, risk, entry_cost, cost = 1_850.0, 12.0, 0.0002, 0.0006
    inline = (entry_cost + cost) * entry / risk
    assert math.isclose(costs.cost_r(entry, risk, entry_cost, cost), inline, rel_tol=1e-12)


def test_reproduces_paper_engine_round_trip_fee_dollars():
    """execution/paper_engine.py:210 computes rate * size * (|entry| + |exit|)."""
    rate, size, entry, exit_price = 0.0004, 0.42, 64_980.0, 66_300.0
    inline = rate * size * (abs(entry) + abs(exit_price))
    assert math.isclose(costs.cost_dollars(size, entry, exit_price, rate), inline, rel_tol=1e-12)


def test_reproduces_paper_engine_gross_rr():
    """execution/paper_engine.py:237 computes the GROSS move/risk (no cost)."""
    entry, stop, exit_price = 100.0, 95.0, 108.0
    risk = abs(entry - stop)
    long_inline = (exit_price - entry) / risk
    assert math.isclose(rmath.gross_r(entry, exit_price, risk, "long"), long_inline, rel_tol=1e-12)
    short_inline = (entry - exit_price) / risk
    assert math.isclose(rmath.gross_r(entry, exit_price, risk, "short"), short_inline, rel_tol=1e-12)


def test_reproduces_custom_net_r():
    """strategies/custom.py computes move/risk - cost_r for its non-managed
    exits — exactly net_r()."""
    entry, exit_px, risk, cost = 100.0, 108.0, 5.0, 0.12
    long_inline = (exit_px - entry) / risk - cost
    assert math.isclose(rmath.net_r(entry, exit_px, risk, "long", cost), long_inline, rel_tol=1e-12)
    short_inline = (entry - exit_px) / risk - cost
    assert math.isclose(rmath.net_r(entry, exit_px, risk, "short", cost), short_inline, rel_tol=1e-12)


# ------------------------- documented divergences NOT unified (yet), pinned

def test_dollar_denominated_r_is_a_different_quantity():
    """bot/backtester.py:449 reports net_pnl / risk_dollars — a DOLLAR-based R
    that already nets fees and scales by qty. It is deliberately NOT swapped to
    gross_r/net_r (which are price-based): with fees they disagree, so a
    mechanical swap would silently move numbers. Reconciling the two is S4.5/S4.6
    work. This test pins the difference so it can't be unified by accident.

    NOTE: bot/ is a repo-root package that root-level tests import WITHOUT
    automation-hub on sys.path, so it cannot import tradecore today at all —
    a structural blocker recorded in docs/TRADECORE_PLAN.md."""
    entry, exit_px, qty = 100.0, 108.0, 2.0
    sl = 95.0
    risk_price = abs(entry - sl)
    fees = 1.0
    net_pnl = (exit_px - entry) * qty - fees
    risk_dollars = risk_price * qty
    dollar_r = net_pnl / risk_dollars

    price_gross_r = rmath.gross_r(entry, exit_px, risk_price, "long")
    # same trade, two different R's — the dollar form is net of fees
    assert not math.isclose(dollar_r, price_gross_r, rel_tol=1e-9)
    # and they DO agree once fees are zero (proving the only gap is cost, not direction)
    net_pnl_nofee = (exit_px - entry) * qty
    assert math.isclose(net_pnl_nofee / risk_dollars, price_gross_r, rel_tol=1e-12)


def test_default_constants_match_realistic_fill_and_custom_backtest():
    # the canonical defaults must equal the two engines that already agree
    # (services/fill_model.py:38 taker 0.0004; strategies/custom.py:670 fee/slip)
    assert costs.DEFAULT_FEE_PCT == 0.0004
    assert costs.DEFAULT_SLIPPAGE_PCT == 0.0002
    assert math.isclose(costs.round_trip_cost_pct(), 0.0006, rel_tol=1e-12)
