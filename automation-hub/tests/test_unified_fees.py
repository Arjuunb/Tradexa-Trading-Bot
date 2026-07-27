"""HUB_UNIFIED_FEES — closing TradeCore audit risk R1.

Live paper fills perfectly (zero cost) by default while every backtest charges
fee + slippage, so a strategy looks systematically rosier live than in the test
that validated it. This flag makes the two charge the same, and these tests pin
BOTH that they agree when it is on, and that nothing changes when it is off.
"""
import math

import pytest

from services import fill_model as fm


def _clear(monkeypatch):
    for k in ("HUB_FILL_MODEL", "HUB_UNIFIED_FEES"):
        monkeypatch.delenv(k, raising=False)


# ------------------------------------------------------- default is unchanged

def test_default_is_still_perfect_fills(monkeypatch):
    """The flag is opt-in: with nothing set, behaviour is exactly as before."""
    _clear(monkeypatch)
    m = fm.from_env()
    assert isinstance(m, fm.PerfectFill)
    assert m.fee_pct() == 0.0
    assert m.apply("buy", 100.0, 1.0)["price"] == 100.0


def test_explicit_realistic_still_wins(monkeypatch):
    """An explicit HUB_FILL_MODEL choice is not overridden by the new flag."""
    _clear(monkeypatch)
    monkeypatch.setenv("HUB_FILL_MODEL", "realistic")
    monkeypatch.setenv("HUB_UNIFIED_FEES", "1")
    m = fm.from_env()
    assert isinstance(m, fm.RealisticFill)
    assert m.spread_pct > 0            # the full-friction model, not the unified one


# ------------------------------------------------- the flag closes the R1 gap

def test_flag_enables_backtest_matching_costs(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HUB_UNIFIED_FEES", "1")
    m = fm.from_env()
    assert isinstance(m, fm.RealisticFill)
    assert m.fee_pct() > 0, "live paper must actually charge a commission"


def test_per_side_cost_equals_the_backtests(monkeypatch):
    """THE point of the flag: the same trade costs the same in both engines."""
    from bot.tradecore.costs import DEFAULT_FEE_PCT, DEFAULT_SLIPPAGE_PCT
    _clear(monkeypatch)
    monkeypatch.setenv("HUB_UNIFIED_FEES", "1")
    m = fm.from_env()
    live_per_side = m.fee_pct() + m.cost_pct        # commission + price impact
    backtest_per_side = DEFAULT_FEE_PCT + DEFAULT_SLIPPAGE_PCT
    assert math.isclose(live_per_side, backtest_per_side, rel_tol=1e-12)
    assert math.isclose(fm.backtest_cost_pct_per_side(), backtest_per_side, rel_tol=1e-12)


def test_rates_are_sourced_from_tradecore_not_duplicated(monkeypatch):
    """If TradeCore's defaults ever move, the unified model moves with them —
    the two cannot drift apart."""
    from bot.tradecore import costs
    _clear(monkeypatch)
    monkeypatch.setenv("HUB_UNIFIED_FEES", "1")
    monkeypatch.setattr(costs, "DEFAULT_FEE_PCT", 0.001)
    monkeypatch.setattr(costs, "DEFAULT_SLIPPAGE_PCT", 0.002)
    m = fm.unified_fees()
    assert m.taker_fee_pct == 0.001
    assert math.isclose(m.cost_pct, 0.002, rel_tol=1e-12)


def test_unified_model_adds_no_randomness(monkeypatch):
    """Matching the backtest means matching it — no rejections or partial fills,
    which the backtest does not model."""
    _clear(monkeypatch)
    monkeypatch.setenv("HUB_UNIFIED_FEES", "1")
    m = fm.from_env()
    assert m.reject_prob == 0.0 and m.partial_fill_prob == 0.0
    for _ in range(50):
        r = m.apply("buy", 100.0, 1.0)
        assert r["rejected"] is False and r["filled_fraction"] == 1.0


def test_buys_fill_worse_and_sells_fill_worse(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("HUB_UNIFIED_FEES", "1")
    m = fm.from_env()
    assert m.apply("buy", 100.0, 1.0)["price"] > 100.0
    assert m.apply("sell", 100.0, 1.0)["price"] < 100.0


def test_maker_fills_pay_no_price_impact(monkeypatch):
    """A resting limit executes AT its price — that is the point of a maker
    entry, and the unified model keeps that property."""
    _clear(monkeypatch)
    monkeypatch.setenv("HUB_UNIFIED_FEES", "1")
    m = fm.from_env()
    assert m.apply("buy", 100.0, 1.0, maker=True)["price"] == 100.0
    assert m.fee_pct(maker=True) < m.fee_pct(maker=False)


# ------------------------------------------- end-to-end through the paper engine

def test_paper_engine_books_the_commission_when_unified(monkeypatch):
    """A round trip must actually cost money in the ledger, not just in theory."""
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    _clear(monkeypatch)
    monkeypatch.setenv("HUB_UNIFIED_FEES", "1")

    paper = PaperExecutionEngine(SqliteLedger(":memory:"), starting_balance=10_000,
                                 fill_model=fm.from_env())
    paper.open(symbol="BTCUSDT", side="long", size=1.0, entry=100.0, stop=95.0)
    paper.close(symbol="BTCUSDT", exit_price=100.0)      # flat move
    assert paper.realized_pnl() < 0, "a flat round trip must lose the fees"
    assert paper.fees_paid() > 0


def test_paper_engine_is_free_by_default(monkeypatch):
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    _clear(monkeypatch)
    paper = PaperExecutionEngine(SqliteLedger(":memory:"), starting_balance=10_000,
                                 fill_model=fm.from_env())
    paper.open(symbol="BTCUSDT", side="long", size=1.0, entry=100.0, stop=95.0)
    paper.close(symbol="BTCUSDT", exit_price=100.0)
    assert paper.realized_pnl() == 0.0 and paper.fees_paid() == 0.0
