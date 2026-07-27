"""Backtester characterization gate (Sprint 4, S4.0 for the event-driven engine).

docs/TRADECORE_PLAN.md §6: pin an engine BEFORE changing it. S4.5 proposes that
bot/backtester.py adopt the shared TradeManager, and this is the riskiest engine
in the codebase — Backtester.step() drives BOTH paper_trading/simulator.run_paper
AND the real-time bots/live_runner.LiveBotRunner, so a silent shift here reaches
LIVE trading.

Every number below was READ OFF the current engine, not assumed. They pin the
paths S4.5 would touch: plain stop / target fills, the fee+slippage accounting
that makes this engine's R dollar-denominated, T3a partial take-profit (a real
broker fill with its own fee share), T3b break-even, T4 time exit, and the
same-bar SL/TP straddle tie-break.
"""
from datetime import datetime, timedelta, timezone

import pytest

from bot.backtester import Backtester
from bot.strategies.base import Strategy
from bot.types import Bar, Signal, SignalType

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _bar(i, o, h, l, c, v=100.0):
    return Bar(T0 + timedelta(hours=i), o, h, l, c, v)


class _OneShot(Strategy):
    """Emits exactly one LONG signal on a chosen bar with explicit SL/TP."""
    name = "charact_one_shot"

    def __init__(self, symbol, fire_at=3, sl_offset=-1.0, tp_offset=5.0):
        super().__init__(symbol)
        self.fired = False
        self.fire_at = fire_at
        self.sl_offset = sl_offset
        self.tp_offset = tp_offset

    def generate(self, bar):
        if not self.fired and len(self.bars) == self.fire_at:
            self.fired = True
            return Signal(timestamp=bar.timestamp, symbol=self.symbol,
                          type=SignalType.LONG, entry=bar.close,
                          stop_loss=bar.close + self.sl_offset,
                          take_profit=bar.close + self.tp_offset,
                          reason="charact")
        return None


def _run(bars, *, sl_offset=-1.0, tp_offset=5.0, fire_at=3, **kw):
    strat = _OneShot("X", fire_at=fire_at, sl_offset=sl_offset, tp_offset=tp_offset)
    bt = Backtester(strat, bars, starting_cash=10_000, **kw)
    bt.run()
    return bt.trades


def _series(n=12, slope=1.0):
    return [_bar(i, 100 + i * slope, 100 + i * slope + 0.5,
                 100 + i * slope - 0.5, 100 + i * slope) for i in range(n)]


# --------------------------------------------------------------- determinism

def test_backtester_is_deterministic():
    bars = _series(12)
    assert _run(bars) == _run(bars)


# ------------------------------------------------- plain stop / target fills

def test_plain_target_fill_is_pinned():
    """Signal at bar 3 (close 103) fills at bar 4's OPEN (no look-ahead), so the
    realised risk is |103-101| = 2 and the +5 target at 107 pays exactly 2R."""
    t = _run(_series(12), fee_bps=0.0, slippage_bps=0.0)[0]
    assert t["side"] == "buy"
    assert t["entry_price"] == pytest.approx(103.0)
    assert t["planned_sl"] == pytest.approx(101.0)
    assert t["planned_tp"] == pytest.approx(107.0)
    assert t["exit_price"] == pytest.approx(107.0)
    assert t["r"] == pytest.approx(2.0)
    assert t["pnl"] == pytest.approx(t["gross_pnl"])     # zero-fee run


def test_plain_stop_fill_is_pinned():
    """Falling series takes the stop for exactly -1R."""
    t = _run(_series(12, slope=-1.0), sl_offset=-3.0, fee_bps=0.0, slippage_bps=0.0)[0]
    assert t["entry_price"] == pytest.approx(97.0)
    assert t["planned_sl"] == pytest.approx(95.0)
    assert t["exit_price"] == pytest.approx(95.0)
    assert t["r"] == pytest.approx(-1.0)


def test_fees_make_r_dollar_denominated_and_worse_than_gross():
    """This engine reports net_pnl/risk_dollars, so fees + slippage degrade both
    the fill prices AND R. Pins the dollar-R divergence TradeCore documents."""
    free = _run(_series(12), fee_bps=0.0, slippage_bps=0.0)[0]
    paid = _run(_series(12), fee_bps=5.0, slippage_bps=2.0)[0]
    assert free["r"] == pytest.approx(2.0)
    assert paid["r"] == pytest.approx(1.90686, abs=1e-5)
    assert paid["pnl"] < paid["gross_pnl"]          # fees booked
    assert paid["entry_price"] > free["entry_price"]  # slippage on entry
    assert paid["exit_price"] < free["exit_price"]    # and on exit


# ------------------------------------------- T3a partial + T3b break-even

def test_partial_take_profit_books_a_real_broker_fill():
    """T3a routes an actual partial_close through the broker and records it as
    its own trade row with a pro-rated entry fee — behaviour TradeManager does
    NOT model (it returns a partial PRICE, not a filled order)."""
    trades = _run(_series(14), fee_bps=0.0, slippage_bps=0.0,
                  partial_tp_r=1.0, partial_tp_frac=0.5, breakeven_after_r=1.0)
    partials = [t for t in trades if t.get("is_partial")]
    rest = [t for t in trades if not t.get("is_partial")]
    assert len(partials) == 1 and len(rest) == 1
    p = partials[0]
    assert p["reason"].endswith("partial_tp")
    assert p["entry_price"] == pytest.approx(103.0)
    assert p["exit_price"] == pytest.approx(105.0)      # +1R
    assert p["r"] == pytest.approx(1.0)
    # half the position was booked; the two rows split the original qty evenly
    assert p["qty"] == pytest.approx(rest[0]["qty"])


def test_breakeven_does_not_corrupt_the_remainder_r():
    """REGRESSION TEST for the break-even R bug.

    T3b rewrites ``planned_sl`` to the entry price. R used to be computed from
    that mutated stop, so ``risk_dollars`` collapsed to 0 and a profitable
    remainder was reported as **0.0R** despite making +$49.02.

    R is now measured against the risk taken AT ENTRY, which is the only
    meaningful denominator, so the remainder correctly reports 2.0R
    (entry 103 -> exit 107, original risk 2).
    """
    trades = _run(_series(14), fee_bps=0.0, slippage_bps=0.0,
                  partial_tp_r=1.0, partial_tp_frac=0.5, breakeven_after_r=1.0)
    rest = [t for t in trades if not t.get("is_partial")][0]
    assert rest["planned_sl"] == pytest.approx(rest["entry_price"])   # BE moved
    assert rest["exit_price"] == pytest.approx(107.0)                 # ran to target
    assert rest["pnl"] == pytest.approx(49.0196, abs=1e-3)            # profitable
    assert rest["r"] == pytest.approx(2.0)     # <-- corrected (was 0.0)
    # and R stays consistent with P&L: same sign, non-zero for a winner
    assert rest["r"] > 0


def test_breakeven_before_partial_still_allows_partial_tp():
    """Second latent effect of the same bug: when break-even fires BEFORE the
    partial, recomputing risk from the mutated stop gave 0 and
    ``_manage_open_trade`` bailed out early — silently disabling partial-TP for
    the rest of the trade. Using the entry risk keeps it armed."""
    trades = _run(_series(16), fee_bps=0.0, slippage_bps=0.0,
                  breakeven_after_r=0.5, partial_tp_r=1.0, partial_tp_frac=0.5)
    assert any(t.get("is_partial") for t in trades), \
        "partial-TP must still fire after an earlier break-even move"


def test_time_exit_is_pinned():
    """T4 force-closes after max_hold_bars, at neither SL nor TP."""
    t = _run(_series(20, slope=0.01), fee_bps=0.0, slippage_bps=0.0, max_hold_bars=3)[0]
    assert t["exit_price"] != pytest.approx(t["planned_tp"])
    assert t["exit_price"] != pytest.approx(t["planned_sl"])
    assert t["exit_price"] == pytest.approx(100.05, abs=1e-6)


def test_same_bar_sl_tp_straddle_resolves_stop_first():
    """One bar spanning BOTH stop and target must resolve stop-first (the
    conservative default). TradeManager implements this tie-break independently,
    so it is pinned on both sides."""
    bars = _series(4)
    bars.append(_bar(4, 104.0, 200.0, 1.0, 104.0))          # spans everything
    bars += [_bar(i, 104.0, 104.5, 103.5, 104.0) for i in range(5, 9)]
    t = _run(bars, fire_at=3, fee_bps=0.0, slippage_bps=0.0)[0]
    assert t["r"] == pytest.approx(-1.0), "stop must win the straddle"
