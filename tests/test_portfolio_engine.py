"""The Portfolio Engine, tested at the edges that matter.

Three things are being proven here, and only the first is arithmetic:

1. Each of the thirteen tracked figures is right, including at the boundaries
   where the obvious implementation is wrong (a hedged book, a short position, a
   venue in another currency).
2. Unavailable stays unavailable. Every path that cannot produce a number
   produces ``None`` and a note, never a zero — a portfolio page that shows 0.00
   for "unknown" is worse than one that shows nothing.
3. The engine is independent of the execution engine, structurally rather than
   by convention.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradexa.portfolio import (
    ClosedTrade, Direction, EquityPoint, Portfolio, PortfolioEngine,
    PositionSnapshot, VenueKind, VenueSnapshot,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def _pos(symbol="BTCUSDT", direction=Direction.LONG, qty=1.0, entry=100.0,
         mark=None, **kw):
    return PositionSnapshot(symbol=symbol, direction=direction, qty=qty,
                            entry=entry, mark=mark, **kw)


def _venue(name="binance", cash=10_000.0, positions=(), **kw):
    return VenueSnapshot(venue=name, cash=cash, positions=positions, **kw)


def _curve(days=30, start=10_000.0, step=50.0):
    return tuple(EquityPoint(NOW - timedelta(days=d), start + (days - d) * step)
                 for d in range(days, -1, -1))


def _engine():
    return PortfolioEngine()


# ═══════════════════════════════════════════════════ capital

def test_balance_is_settled_cash_not_equity():
    """Balance and equity differ by open P&L, and conflating them is how a
    dashboard shows a profit that has not been booked as though it were cash."""
    v = _venue(cash=10_000, positions=(_pos(qty=1, entry=100, mark=150),))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.balance == 10_000
    assert s.equity == 10_050


def test_equity_includes_unrealised_losses():
    v = _venue(cash=10_000, positions=(_pos(qty=2, entry=100, mark=90),))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.equity == 9_980


def test_a_short_gains_when_price_falls():
    """The sign trap. A short marked below entry is in profit, and an
    implementation that subtracts in one direction only reports every winning
    short as a loss."""
    v = _venue(positions=(_pos(direction=Direction.SHORT, qty=1, entry=100, mark=90),))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.unrealized_pnl == 10


def test_buying_power_applies_each_venues_own_leverage():
    """A 1x cash broker and a 10x futures venue do not share a multiplier.
    Summing free margin and then applying one leverage figure overstates the
    cash account by an order of magnitude."""
    cash = _venue("ibkr", cash=1_000, max_leverage=1.0)
    futures = _venue("binance", cash=1_000, max_leverage=10.0)
    s = _engine().snapshot(Portfolio(venues=(cash, futures), at=NOW))
    assert s.buying_power == 11_000


def test_margin_level_is_undefined_without_used_margin():
    """Not infinity, not zero. An unlevered account has no margin level, and
    reporting one invites a comparison that means nothing."""
    s = _engine().snapshot(Portfolio(venues=(_venue(),), at=NOW))
    assert s.margin_level is None


def test_free_margin_never_goes_negative():
    v = _venue(cash=1_000, used_margin=5_000)
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.free_margin == 0.0


# ═══════════════════════════════════════════════════ exposure

def test_gross_exposure_counts_both_sides_but_net_cancels():
    """A hedged book nets to zero and is still fully exposed. Netting alone
    would report a margin-callable position as flat."""
    v = _venue(positions=(
        _pos("BTCUSDT", Direction.LONG, 1, 100, mark=100),
        _pos("ETHUSDT", Direction.SHORT, 1, 100, mark=100)))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.gross_exposure == 200
    assert s.net_exposure == 0


def test_one_symbol_on_two_exchanges_is_one_exposure():
    """The specific mistake a multi-venue book invites, and the reason this
    cannot be computed inside any single execution engine."""
    a = _venue("binance", positions=(_pos("BTCUSDT", qty=1, entry=100, mark=100),))
    b = _venue("bybit", positions=(_pos("BTCUSDT", qty=2, entry=100, mark=100),))
    s = _engine().snapshot(Portfolio(venues=(a, b), at=NOW))
    assert s.exposure_by_symbol["BTCUSDT"] == 300
    assert s.exposure_by_venue == {"binance": 100, "bybit": 200}


def test_exposure_is_marked_to_market_not_to_cost():
    v = _venue(positions=(_pos(qty=1, entry=100, mark=140),))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.gross_exposure == 140


def test_exposure_pct_is_against_equity_including_open_pnl():
    """``cash`` is settled cash AFTER the position was paid for, so equity is
    cash plus open P&L — not cash plus the position's notional, which would
    count the same money twice."""
    v = _venue(cash=1_000, positions=(_pos(qty=1, entry=500, mark=600),))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.equity == 1_100
    assert s.exposure_pct == pytest.approx(600 / 1_100)


# ═══════════════════════════════════════════════════ unavailable is a value

def test_an_unmarked_position_makes_unrealised_pnl_unavailable():
    """Not zero. An unmarked position reported as flat turns a losing book into
    a break-even one at exactly the moment that matters."""
    v = _venue(positions=(_pos(mark=None),))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.unrealized_pnl is None
    assert s.equity is None
    assert any("unmarked" in n for n in s.notes)


def test_one_unmarked_position_does_not_produce_a_partial_total():
    """A sum over the marked half, presented as the total, is the single most
    misleading answer available — it looks complete."""
    v = _venue(positions=(_pos("BTCUSDT", mark=200), _pos("ETHUSDT", mark=None)))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.unrealized_pnl is None


def test_exposure_survives_a_missing_mark_by_falling_back_to_cost():
    """Exposure at cost is still useful and is stated as such; equity is not,
    so it is withheld. Different questions, different answers."""
    v = _venue(positions=(_pos(qty=3, entry=100, mark=None),))
    s = _engine().snapshot(Portfolio(venues=(v,), at=NOW))
    assert s.gross_exposure == 300
    assert s.equity is None


def test_an_unreachable_venue_is_excluded_not_counted_as_empty():
    """An exchange that failed to respond is not a flat account. Counting it as
    zero silently shrinks every total and every denominator."""
    up = _venue("binance", cash=5_000)
    down = _venue("bybit", cash=0.0, reachable=False, note="timeout")
    s = _engine().snapshot(Portfolio(venues=(up, down), at=NOW))
    assert s.balance == 5_000
    assert any("unreachable" in n and "bybit" in n for n in s.notes)
    assert not s.complete


def test_the_unreachable_venue_still_appears_in_the_breakdown():
    """Excluded from the totals, not from the report. A venue that vanishes from
    the page is one nobody goes to fix."""
    s = _engine().snapshot(Portfolio(
        venues=(_venue("binance"), _venue("bybit", reachable=False)), at=NOW))
    assert {v.venue for v in s.per_venue} == {"binance", "bybit"}
    assert s.venue("bybit").reachable is False


def test_no_equity_curve_means_no_returns_rather_than_zero_returns():
    s = _engine().snapshot(Portfolio(venues=(_venue(),), at=NOW))
    assert s.daily_return is None and s.monthly_return is None
    assert s.sharpe_ratio is None and s.max_drawdown_pct is None
    assert any("no equity curve" in n for n in s.notes)


def test_no_trades_means_no_win_rate_rather_than_zero_percent():
    """0% is a real, terrible track record. A new account has not earned it."""
    s = _engine().snapshot(Portfolio(venues=(_venue(),), at=NOW))
    assert s.win_rate is None and s.expectancy is None


def test_as_dict_preserves_none_rather_than_coercing_to_zero():
    """The serialisation boundary is where honesty rules are usually undone."""
    s = _engine().snapshot(Portfolio(venues=(_venue(positions=(_pos(),)),), at=NOW))
    data = s.as_dict()
    assert data["equity"] is None
    assert data["available"] is False
    assert data["notes"]


# ═══════════════════════════════════════════════════ multi-currency

def test_a_foreign_venue_is_converted_at_the_supplied_rate():
    eur = _venue("ibkr", cash=1_000, currency="EUR")
    usd = _venue("binance", cash=1_000)
    s = _engine().snapshot(Portfolio(venues=(eur, usd), fx_rates={"EUR": 1.10},
                                     at=NOW))
    assert s.balance == pytest.approx(2_100)
    assert s.venue("ibkr").fx_rate == 1.10


def test_an_unconvertible_venue_is_excluded_with_a_note():
    """Two currencies added without a rate is a number that is the sum of two
    different things. Refusing is the only honest option."""
    gbp = _venue("ig", cash=1_000, currency="GBP")
    usd = _venue("binance", cash=2_000)
    s = _engine().snapshot(Portfolio(venues=(gbp, usd), at=NOW))
    assert s.balance == 2_000
    assert any("GBP" in n for n in s.notes)
    assert not s.complete


def test_the_margin_level_ratio_is_not_converted():
    """It is a ratio, not an amount. Multiplying it by an FX rate would be
    dimensionally wrong and would look plausible."""
    eur = _venue("ibkr", cash=1_000, currency="EUR", used_margin=500)
    s = _engine().snapshot(Portfolio(venues=(eur,), fx_rates={"EUR": 1.10}, at=NOW))
    assert s.venue("ibkr").margin_level == pytest.approx(2.0)


# ═══════════════════════════════════════════════════ returns and track record

def test_daily_return_measures_from_yesterdays_close():
    curve = (EquityPoint(NOW - timedelta(days=1), 10_000),   # yesterday's close
             EquityPoint(NOW.replace(hour=1), 10_100),
             EquityPoint(NOW, 10_200))
    s = _engine().snapshot(Portfolio(venues=(_venue(),), equity_curve=curve, at=NOW))
    assert s.daily_return == pytest.approx(0.02)


def test_daily_return_is_unavailable_on_the_first_day():
    """An account opened today has no yesterday. Reporting 0% would claim a flat
    day that never happened."""
    curve = (EquityPoint(NOW.replace(hour=9), 10_000), EquityPoint(NOW, 10_500))
    s = _engine().snapshot(Portfolio(venues=(_venue(),), equity_curve=curve, at=NOW))
    assert s.daily_return is None


def test_monthly_return_is_a_calendar_month_not_thirty_days():
    curve = (EquityPoint(datetime(2026, 6, 30, 23, tzinfo=timezone.utc), 10_000),
             EquityPoint(datetime(2026, 7, 2, tzinfo=timezone.utc), 9_000),
             EquityPoint(NOW, 11_000))
    s = _engine().snapshot(Portfolio(venues=(_venue(),), equity_curve=curve, at=NOW))
    assert s.monthly_return == pytest.approx(0.10)


def test_max_drawdown_is_reported_as_a_positive_fraction():
    curve = (EquityPoint(NOW - timedelta(days=3), 10_000),
             EquityPoint(NOW - timedelta(days=2), 12_000),
             EquityPoint(NOW - timedelta(days=1), 9_000),
             EquityPoint(NOW, 11_000))
    s = _engine().snapshot(Portfolio(venues=(_venue(),), equity_curve=curve, at=NOW))
    assert s.max_drawdown_pct == pytest.approx(0.25)


def test_sharpe_uses_daily_closes_not_raw_samples():
    """Otherwise the ratio is a function of polling frequency: the same account
    polled hourly and daily would report different performance."""
    dense = []
    for d in range(20, -1, -1):
        day = NOW - timedelta(days=d)
        for hour in (1, 5, 9):
            dense.append(EquityPoint(day.replace(hour=hour), 10_000 + (20 - d) * 100))
    sparse = tuple(EquityPoint(NOW - timedelta(days=d), 10_000 + (20 - d) * 100)
                   for d in range(20, -1, -1))
    a = _engine().snapshot(Portfolio(venues=(_venue(),), equity_curve=tuple(dense), at=NOW))
    b = _engine().snapshot(Portfolio(venues=(_venue(),), equity_curve=sparse, at=NOW))
    assert a.sharpe_ratio == pytest.approx(b.sharpe_ratio)


def test_sharpe_needs_two_days_and_says_so():
    curve = (EquityPoint(NOW, 10_000),)
    s = _engine().snapshot(Portfolio(venues=(_venue(),), equity_curve=curve, at=NOW))
    assert s.sharpe_ratio is None


def test_a_short_sample_is_reported_with_its_size_not_suppressed():
    """The figure is real arithmetic and is shown; what it is not yet is
    evidence, and the note is what says so."""
    curve = (EquityPoint(NOW - timedelta(days=1), 10_000), EquityPoint(NOW, 10_100))
    s = _engine().snapshot(Portfolio(venues=(_venue(),), equity_curve=curve, at=NOW))
    assert s.sharpe_ratio is not None
    assert any("indicative" in n for n in s.notes)


def test_win_rate_and_expectancy_come_from_closed_trades():
    trades = tuple(ClosedTrade("BTCUSDT", pnl, NOW) for pnl in
                   (100, 100, 100, -50, -50, 200, -25, 40, -10, 15))
    s = _engine().snapshot(Portfolio(venues=(_venue(),), closed_trades=trades, at=NOW))
    assert s.win_rate == pytest.approx(0.6)
    assert s.expectancy == pytest.approx(sum(t.pnl for t in trades) / len(trades))
    assert s.trade_count == 10


def test_a_break_even_trade_counts_as_a_loss_consistently():
    """Win rate and expectancy must split on the same boundary, or the two
    figures on one page stop reconciling."""
    trades = (ClosedTrade("BTCUSDT", 0.0, NOW), ClosedTrade("ETHUSDT", 100.0, NOW))
    s = _engine().snapshot(Portfolio(venues=(_venue(),), closed_trades=trades, at=NOW))
    assert s.win_rate == pytest.approx(0.5)


def test_profit_factor_is_undefined_before_the_first_loss():
    """Infinity on a dashboard flatters a three-trade record into looking
    flawless."""
    trades = (ClosedTrade("BTCUSDT", 100.0, NOW),)
    s = _engine().snapshot(Portfolio(venues=(_venue(),), closed_trades=trades, at=NOW))
    assert s.profit_factor is None


# ═══════════════════════════════════════════════════ per-venue breakdown

def test_every_figure_is_available_per_venue():
    a = _venue("binance", cash=6_000, positions=(_pos(qty=1, entry=100, mark=110),))
    b = _venue("ibkr", cash=4_000)
    s = _engine().snapshot(Portfolio(venues=(a, b), at=NOW))
    assert s.venue("binance").equity == 6_010
    assert s.venue("ibkr").equity == 4_000
    assert sum(v.balance for v in s.per_venue) == s.balance


def test_a_venue_breakdown_cannot_disagree_with_the_aggregate():
    """It runs the identical path over a narrowed portfolio rather than a second
    implementation, so drift is impossible rather than merely unlikely."""
    a = _venue("binance", cash=6_000, positions=(_pos(qty=1, entry=100, mark=110),))
    p = Portfolio(venues=(a, _venue("ibkr", cash=4_000)), at=NOW)
    one = _engine().venue_breakdown(p, "binance")
    assert one.equity == _engine().snapshot(p).venue("binance").equity


def test_a_breakdown_says_the_curve_is_portfolio_wide():
    """The equity curve describes the whole book. Presenting it as one venue's
    would attribute another account's drawdown to this one."""
    p = Portfolio(venues=(_venue("binance"),), equity_curve=_curve(), at=NOW)
    one = _engine().venue_breakdown(p, "binance")
    assert any("portfolio-wide" in n for n in one.notes)


def test_unattributed_trades_are_omitted_from_a_breakdown_not_misassigned():
    trades = (ClosedTrade("BTCUSDT", 100.0, NOW),)   # no venue recorded
    p = Portfolio(venues=(_venue("binance"),), closed_trades=trades, at=NOW)
    one = _engine().venue_breakdown(p, "binance")
    assert one.win_rate is None
    assert any("attribution" in n for n in one.notes)


def test_an_unknown_venue_returns_none():
    p = Portfolio(venues=(_venue("binance"),), at=NOW)
    assert _engine().venue_breakdown(p, "nope") is None


# ═══════════════════════════════════════════════════ structure

def test_the_engine_is_pure():
    """Two calls, same answer. A portfolio figure that cannot be reproduced
    cannot be explained after the fact."""
    p = Portfolio(venues=(_venue(positions=(_pos(mark=120),)),),
                  equity_curve=_curve(), at=NOW)
    e = _engine()
    first, second = e.snapshot(p), e.snapshot(p)
    assert first.as_dict()["equity"] == second.as_dict()["equity"]
    assert first.sharpe_ratio == second.sharpe_ratio


def test_the_portfolio_package_is_independent_of_execution():
    """The requirement, enforced structurally. Portfolio mathematics that
    imports an execution engine can only ever describe that one engine's
    account — and a second broker means a second copy of the arithmetic."""
    import ast
    import pathlib

    banned = ("execution", "broker", "exchange", "ccxt", "fastapi", "sqlite3",
              "database", "services", "requests", "data.ledger")
    root = pathlib.Path(__file__).resolve().parents[1] / "tradexa" / "portfolio"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                head = name.split(".")[0]
                assert head not in banned, (
                    f"{path.name} imports {name} — the Portfolio Engine must "
                    "stay independent of execution")


def test_the_shared_metric_arithmetic_is_reused_not_restated():
    """Drawdown, Sharpe and expectancy already exist in bot.metrics and are used
    by the backtester. A second implementation would agree the day it was
    written and drift on the first fix — and a portfolio page disagreeing with
    the backtest report about the same account is worse than either being
    absent."""
    import inspect

    from tradexa.portfolio import metrics as pm

    src = inspect.getsource(pm)
    assert "from bot.metrics import" in src
    curve = _curve(days=40)
    engine_dd = _engine().snapshot(
        Portfolio(venues=(_venue(),), equity_curve=curve, at=NOW)).max_drawdown_pct
    from bot.metrics import max_drawdown
    assert engine_dd == pytest.approx(abs(max_drawdown([p.equity for p in curve])))


def test_one_venue_and_nine_take_the_same_path():
    """Multi-venue is the normal case, not a mode. Nothing in the engine may
    assume a single balance."""
    many = tuple(_venue(f"venue{i}", cash=1_000,
                        positions=(_pos(f"SYM{i}", qty=1, entry=10, mark=10),))
                 for i in range(9))
    s = _engine().snapshot(Portfolio(venues=many, at=NOW))
    assert s.venue_count == 9
    assert s.balance == 9_000
    assert s.gross_exposure == 90
    assert len(s.exposure_by_symbol) == 9


def test_venue_kinds_share_one_code_path():
    """A broker and an exchange differ in how their state is fetched, which is
    the adapter's problem — not in how equity is computed, which is this
    engine's."""
    v = (_venue("ibkr", cash=1_000, kind=VenueKind.BROKER),
         _venue("binance", cash=1_000, kind=VenueKind.EXCHANGE),
         _venue("paper", cash=1_000, kind=VenueKind.PAPER))
    s = _engine().snapshot(Portfolio(venues=v, at=NOW))
    assert s.balance == 3_000
    assert {x.kind for x in s.per_venue} == {"broker", "exchange", "paper"}


def test_a_complete_snapshot_reports_nothing_missing():
    """The honesty machinery has to be able to say "all clear". A caveat list
    that is never empty is one nobody reads, which costs more than it buys the
    first time something is genuinely absent."""
    v = _venue(cash=10_000, positions=(_pos(mark=110),))
    trades = tuple(ClosedTrade("BTCUSDT", pnl, NOW) for pnl in
                   (10, -5, 20, -8, 15, -3, 30, -12, 6, -4, 18, -7))
    s = _engine().snapshot(Portfolio(venues=(v,), equity_curve=_curve(days=40),
                                     closed_trades=trades, at=NOW))
    assert s.notes == ()
    assert s.complete is True
    assert s.as_dict()["available"] is True


def test_an_empty_portfolio_is_not_an_error():
    s = _engine().snapshot(Portfolio(at=NOW))
    assert s.balance == 0.0 and s.venue_count == 0
    assert s.equity == 0.0     # nothing held is genuinely zero, unlike unknown
