"""Trading-fee (commission) modeling in the paper engine.

Before this, the paper engine booked spread/slippage as price impact but no
explicit commission ("fees not modeled"). Now realized P&L is net of a
round-trip commission taken from the fill model. PerfectFill charges nothing, so
all existing behaviour/tests are unchanged.
"""
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.fill_model import PerfectFill, RealisticFill


def _frictionless_fee(taker=0.001):
    # zero spread/slippage/latency so the ONLY cost is the commission -> the fee
    # can be asserted exactly against the round-trip notional.
    return RealisticFill(spread_pct=0, slippage_pct=0, latency_pct=0,
                         taker_fee_pct=taker, maker_fee_pct=taker / 2)


# ─────────────────────────── fee model ───────────────────────────
def test_perfect_fill_has_no_fee():
    assert PerfectFill().fee_pct() == 0.0
    assert PerfectFill().fee_pct(maker=True) == 0.0


def test_realistic_fill_maker_taker_fees():
    fm = RealisticFill(taker_fee_pct=0.0004, maker_fee_pct=0.0002)
    assert fm.fee_pct() == 0.0004            # taker (default)
    assert fm.fee_pct(maker=True) == 0.0002  # maker discount


# ─────────────────────────── default (no fee) is unchanged ───────────────────────────
def test_default_engine_charges_no_fee():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000)   # PerfectFill
    paper.open(symbol="BTCUSDT", side="BUY", size=1.0, entry=100.0, stop=95.0)
    res = paper.close(symbol="BTCUSDT", exit_price=110.0)
    assert res.fee == 0.0
    assert abs(res.pnl - 10.0) < 1e-9          # full gross, no fee
    assert abs(paper.balance() - 10_010.0) < 1e-9
    assert paper.fees_paid() == 0.0


# ─────────────────────────── fee is deducted on close ───────────────────────────
def test_close_deducts_round_trip_commission():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000, fill_model=_frictionless_fee(0.001))
    paper.open(symbol="BTCUSDT", side="BUY", size=1.0, entry=100.0, stop=95.0)
    res = paper.close(symbol="BTCUSDT", exit_price=110.0)
    # gross = (110-100)*1 = 10 ; fee = 0.001 * 1 * (100+110) = 0.21 ; net = 9.79
    expected_fee = 0.001 * 1.0 * (100.0 + 110.0)
    assert abs(res.fee - expected_fee) < 1e-9
    assert abs(res.pnl - (10.0 - expected_fee)) < 1e-9
    assert abs(paper.balance() - (10_000 + 10.0 - expected_fee)) < 1e-9
    assert abs(paper.fees_paid() - expected_fee) < 1e-9


def test_short_close_also_pays_fee():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000, fill_model=_frictionless_fee(0.001))
    paper.open(symbol="ETHUSDT", side="SELL", size=2.0, entry=100.0, stop=105.0)
    res = paper.close(symbol="ETHUSDT", exit_price=90.0)
    # short gross = (100-90)*2 = 20 ; fee = 0.001*2*(100+90) = 0.38 ; net = 19.62
    expected_fee = 0.001 * 2.0 * (100.0 + 90.0)
    assert abs(res.fee - expected_fee) < 1e-9
    assert abs(res.pnl - (20.0 - expected_fee)) < 1e-9


# ─────────────────────────── partial close pays a proportional fee ───────────────────────────
def test_partial_close_fee_is_proportional():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000, fill_model=_frictionless_fee(0.001))
    paper.open(symbol="BTCUSDT", side="BUY", size=10.0, entry=100.0, stop=95.0)
    res = paper.reduce(symbol="BTCUSDT", exit_price=110.0, fraction=0.4)   # close 4 units
    # closed_size = 4 ; gross = (110-100)*4 = 40 ; fee = 0.001*4*(100+110) = 0.84
    expected_fee = 0.001 * 4.0 * (100.0 + 110.0)
    assert abs(res.fee - expected_fee) < 1e-9
    assert abs(res.pnl - (40.0 - expected_fee)) < 1e-9
