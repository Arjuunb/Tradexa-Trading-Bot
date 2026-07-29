"""The standalone Risk Engine.

Organised by the thirteen responsibilities, plus the two structural
properties that make the engine trustworthy: it is independent of strategies,
and there is no way to obtain an approved size without going through it.

Every test builds its own context. That is the payoff of a pure engine — a 19%
drawdown, a margin call, an account one tick from its daily limit are each two
lines here, where an engine that fetched its own state would need every one of
them manufactured into a database first.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradexa.risk import (
    AccountState, CONSERVATIVE, Direction, MarketConditions, OpenPosition,
    PIPELINE_PARITY, RiskContext, RiskDecision, RiskEngine, RiskLimits,
    TradeProposal,
)
from tradexa.risk import rules as R

MONDAY_NOON = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def proposal(**over):
    kw = dict(symbol="BTCUSDT", direction=Direction.LONG, entry=100.0,
              stop=95.0, confidence=1.0)
    kw.update(over)
    return TradeProposal(**kw)


def context(*, limits_free: bool = True, **over) -> RiskContext:
    """A context that passes cleanly, so each test perturbs exactly one thing."""
    kw = dict(
        proposal=proposal(),
        account=AccountState(equity=10_000.0, cash=10_000.0),
        positions=(),
        market=MarketConditions(cluster="crypto"),
        now=MONDAY_NOON,
    )
    kw.update(over)
    return RiskContext(**kw)


@pytest.fixture()
def engine():
    return RiskEngine(PIPELINE_PARITY)


# ═══════════════════════════════ structural: independence & no bypass

def test_the_engine_imports_no_strategy_exchange_or_database():
    """Independence, enforced. Claimed in a docstring it is a convention;
    conventions break at the first deadline.

    Reads the AST rather than the source text, so prose naming a banned module
    cannot fail it and a real import cannot hide from it.
    """
    forbidden = {
        "ccxt", "sqlite3", "sqlalchemy", "redis", "requests", "httpx",
        "fastapi", "starlette", "websockets", "aiohttp",
        "strategies", "bot", "services", "webhook_api", "app", "data",
        "execution", "database",
    }
    package = Path(R.__file__).parent
    offenders: list[str] = []
    for path in package.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module.split(".")[0])
        leaked = found & forbidden
        if leaked:
            offenders.append(f"{path.name}: {sorted(leaked)}")
    assert not offenders, f"the risk engine is not standalone: {offenders}"


def test_the_only_way_to_get_a_size_is_to_evaluate(engine):
    """"No strategy may bypass risk" is structural, not a rule someone has to
    remember: quantity exists only on a RiskDecision, and a RiskDecision is
    only produced by evaluate()."""
    assert not hasattr(TradeProposal, "quantity")
    assert not hasattr(TradeProposal, "qty")
    d = engine.evaluate(context())
    assert isinstance(d, RiskDecision) and d.quantity > 0


def test_a_rejected_decision_carries_no_size(engine):
    """So a caller that ignores `approved` and reads `quantity` anyway trades
    nothing, rather than trading the size risk refused."""
    d = engine.evaluate(context(kill_switch_engaged=True))
    assert d.approved is False and d.quantity == 0.0


def test_the_engine_holds_no_state_between_calls(engine):
    """A rejection has to be reproducible. An engine that remembers cannot be
    asked 'why did it say no?' after the fact."""
    ctx = context()
    a, b = engine.evaluate(ctx), engine.evaluate(ctx)
    assert a.approved == b.approved and a.quantity == b.quantity


def test_the_engine_never_mutates_its_context(engine):
    ctx = context()
    before = (ctx.account.equity, len(ctx.positions), ctx.proposal.entry)
    engine.evaluate(ctx)
    assert (ctx.account.equity, len(ctx.positions), ctx.proposal.entry) == before


# ═══════════════════════════════ 1. position sizing

def test_size_is_derived_from_risk_and_stop_distance():
    """1% of 10,000 is 100 at risk; a 5-point stop buys 20 units."""
    eng = RiskEngine(RiskLimits(risk_per_trade_pct=0.01,
                                max_position_exposure_pct=0, max_total_exposure_pct=0,
                                max_leverage=0, min_free_margin_pct=0))
    d = eng.evaluate(context())
    assert d.quantity == pytest.approx(20.0)
    assert d.risk_amount == pytest.approx(100.0)


def test_a_wider_stop_buys_fewer_units():
    """The core property of fixed-fractional sizing: risk stays constant."""
    eng = RiskEngine(RiskLimits(max_position_exposure_pct=0, max_total_exposure_pct=0,
                                max_leverage=0, min_free_margin_pct=0))
    tight = eng.evaluate(context(proposal=proposal(stop=99.0)))
    wide = eng.evaluate(context(proposal=proposal(stop=90.0)))
    assert tight.quantity > wide.quantity
    assert tight.risk_amount == pytest.approx(wide.risk_amount)


def test_lower_confidence_sizes_smaller_but_never_to_zero():
    """A signal that cleared every gate is a trade. Sizing it to nothing would
    convert a 'yes' into a 'no' after the decision was made.

    Exposure caps are lifted so the RISK-based size is what is being measured.
    With them on, the 5%-of-equity position cap binds first at these numbers
    and both confidences produce the same quantity — a true statement about the
    engine, but not the one this test is about.
    """
    eng = RiskEngine(PIPELINE_PARITY.with_(
        max_position_exposure_pct=0, max_total_exposure_pct=0,
        max_leverage=0, min_free_margin_pct=0))
    full = eng.evaluate(context(proposal=proposal(confidence=1.0)))
    low = eng.evaluate(context(proposal=proposal(confidence=0.0)))
    assert 0 < low.quantity < full.quantity


def test_risk_per_trade_is_capped_by_the_hard_ceiling():
    """The backstop for a modifier chain that multiplies somewhere absurd."""
    eng = RiskEngine(RiskLimits(risk_per_trade_pct=0.50, max_risk_per_trade_pct=0.02,
                                max_position_exposure_pct=0, max_total_exposure_pct=0,
                                max_leverage=0, min_free_margin_pct=0))
    d = eng.evaluate(context())
    assert d.risk_pct <= 0.02 + 1e-9


def test_the_reported_risk_reflects_the_FINAL_capped_quantity(engine):
    """Reporting the pre-cap figure would overstate what is actually at stake."""
    d = engine.evaluate(context())
    assert d.risk_amount == pytest.approx(d.quantity * 5.0)


# ═══════════════════════════════ 2. maximum account risk

def test_open_risk_across_positions_blocks_a_new_trade():
    """Six trades at 1% each is 6% on one adverse move, and no individual
    trade broke a rule."""
    eng = RiskEngine(RiskLimits(max_account_risk_pct=0.02))
    ctx = context(positions=(
        OpenPosition("ETHUSDT", Direction.LONG, qty=10, entry=50, stop=40),  # 100 at risk
        OpenPosition("SOLUSDT", Direction.LONG, qty=10, entry=20, stop=10),  # 100 at risk
    ))
    d = eng.evaluate(ctx)
    assert not d.approved and d.rule == "max_account_risk"


def test_an_unstopped_position_is_reported_not_counted_as_zero_risk():
    """Counting it as 0 is how a book looks safe while carrying the most
    dangerous thing in it."""
    ctx = context(positions=(OpenPosition("ETHUSDT", Direction.LONG, qty=10,
                                          entry=50, stop=None),))
    result = R.max_account_risk(ctx, RiskLimits())
    assert result.passed and "unstopped" in result.detail
    assert result.context["unstopped"] == ["ETHUSDT"]


# ═══════════════════════════════ 3 & 4. daily / weekly drawdown

def test_the_daily_loss_limit_blocks_new_entries(engine):
    ctx = context(account=AccountState(equity=9_700.0, starting_equity=10_000.0,
                                       realized_pnl_today=-300.0))
    d = engine.evaluate(ctx)
    assert not d.approved and "daily_drawdown" in {v.rule for v in d.violations}


def test_below_the_daily_limit_still_trades(engine):
    ctx = context(account=AccountState(equity=9_900.0, starting_equity=10_000.0,
                                       realized_pnl_today=-100.0))
    assert engine.evaluate(ctx).approved


def test_the_weekly_limit_catches_what_the_daily_limit_misses():
    """A run of small daily losses stays under the daily cap every day and
    still empties an account inside a week."""
    eng = RiskEngine(RiskLimits(max_daily_loss_pct=0.03, max_weekly_loss_pct=0.05))
    ctx = context(account=AccountState(equity=9_400.0, starting_equity=10_000.0,
                                       realized_pnl_today=-100.0,     # under daily
                                       realized_pnl_week=-600.0))     # over weekly
    d = eng.evaluate(ctx)
    assert not d.approved and "weekly_drawdown" in {v.rule for v in d.violations}


def test_peak_to_trough_drawdown_blocks_entries(engine):
    ctx = context(account=AccountState(equity=7_900.0, peak_equity=10_000.0,
                                       starting_equity=7_900.0))
    d = engine.evaluate(ctx)
    assert not d.approved and "max_drawdown" in {v.rule for v in d.violations}


def test_drawdown_is_never_negative_when_equity_exceeds_the_peak():
    """A negative drawdown reads as a gain and would disable the guard."""
    acct = AccountState(equity=12_000.0, peak_equity=10_000.0)
    assert acct.drawdown_pct == 0.0


# ═══════════════════════════════ 5. portfolio exposure

def test_a_single_position_is_capped_by_its_exposure_limit():
    """A tight stop can justify a large position on risk grounds and still put
    an unacceptable share of the account into one instrument."""
    eng = RiskEngine(RiskLimits(max_position_exposure_pct=0.05,
                                max_total_exposure_pct=0, max_leverage=0,
                                min_free_margin_pct=0))
    d = eng.evaluate(context(proposal=proposal(stop=99.9)))   # very tight stop
    assert d.approved and d.quantity * 100.0 <= 500.0 + 1e-6


def test_the_book_total_is_capped_across_positions():
    eng = RiskEngine(RiskLimits(max_total_exposure_pct=0.10,
                                max_position_exposure_pct=0, max_leverage=0,
                                min_free_margin_pct=0, max_open_positions=0,
                                max_account_risk_pct=0, max_correlated_positions=0))
    ctx = context(positions=(OpenPosition("ETHUSDT", Direction.LONG, qty=10, entry=90,
                                          stop=80, cluster="crypto"),))  # 900 notional
    d = eng.evaluate(ctx)
    assert d.approved and (d.quantity * 100.0) <= 100.0 + 1e-6   # 1000 cap - 900 used


def test_a_full_book_is_refused_rather_than_sized_to_zero():
    """A zero-size trade is not a smaller trade, it is a refusal. Reporting it
    as an approval of size 0 would put a phantom trade in the log."""
    eng = RiskEngine(RiskLimits(max_total_exposure_pct=0.10, max_open_positions=0,
                                max_account_risk_pct=0, max_correlated_positions=0))
    ctx = context(positions=(OpenPosition("ETHUSDT", Direction.LONG, qty=20, entry=100,
                                          stop=90, cluster="crypto"),))  # 2000 > 1000
    d = eng.evaluate(ctx)
    assert not d.approved and d.rule == "portfolio_exposure"


def test_gross_exposure_counts_shorts():
    """A hedged book nets to zero and is still fully exposed."""
    ctx = context(positions=(
        OpenPosition("A", Direction.LONG, qty=1, entry=100),
        OpenPosition("B", Direction.SHORT, qty=-1, entry=100),
    ))
    assert ctx.gross_exposure == 200.0


def test_the_open_position_count_is_enforced(engine):
    ctx = context(positions=tuple(
        OpenPosition(f"S{i}", Direction.LONG, qty=1, entry=10, stop=9)
        for i in range(3)))
    d = engine.evaluate(ctx)
    assert not d.approved and "max_open_positions" in {v.rule for v in d.violations}


# ═══════════════════════════════ 6. correlation limits

def test_correlated_same_direction_positions_are_capped(engine):
    """Three simultaneous crypto longs are one 3x bet, not diversification."""
    ctx = context(positions=(
        OpenPosition("ETHUSDT", Direction.LONG, qty=1, entry=50, stop=45, cluster="crypto"),
        OpenPosition("SOLUSDT", Direction.LONG, qty=1, entry=20, stop=18, cluster="crypto"),
    ))
    d = engine.evaluate(ctx)
    assert not d.approved and "correlation_limit" in {v.rule for v in d.violations}


def test_the_opposite_direction_does_not_count_against_the_cluster(engine):
    """Two longs and a short are not the same bet three times."""
    ctx = context(positions=(
        OpenPosition("ETHUSDT", Direction.SHORT, qty=-1, entry=50, stop=55, cluster="crypto"),
        OpenPosition("SOLUSDT", Direction.SHORT, qty=-1, entry=20, stop=22, cluster="crypto"),
    ))
    assert engine.evaluate(ctx).approved


def test_an_unclassified_symbol_says_it_was_not_evaluated():
    """Silently passing would let it dodge the limit and look checked."""
    ctx = context(market=MarketConditions(cluster=""))
    result = R.correlation_limit(ctx, RiskLimits())
    assert result.passed and result.context["evaluated"] is False


# ═══════════════════════════════ 7 & 8. leverage and margin

def test_leverage_is_capped():
    eng = RiskEngine(RiskLimits(max_leverage=1.0, max_position_exposure_pct=0,
                                max_total_exposure_pct=0, min_free_margin_pct=0,
                                max_open_positions=0, max_account_risk_pct=0,
                                max_correlated_positions=0))
    ctx = context(positions=(OpenPosition("ETHUSDT", Direction.LONG, qty=95, entry=100,
                                          stop=90),))    # 9,500 of 10,000
    d = eng.evaluate(ctx)
    assert d.approved and (ctx.gross_exposure + d.quantity * 100) <= 10_000 + 1e-6


def test_a_fully_levered_account_is_refused():
    eng = RiskEngine(RiskLimits(max_leverage=1.0, max_open_positions=0,
                                max_account_risk_pct=0, max_correlated_positions=0,
                                max_position_exposure_pct=0, max_total_exposure_pct=0,
                                min_free_margin_pct=0))
    ctx = context(positions=(OpenPosition("ETHUSDT", Direction.LONG, qty=100, entry=100,
                                          stop=90),))
    d = eng.evaluate(ctx)
    assert not d.approved and d.rule == "leverage"


def test_the_free_margin_buffer_is_preserved():
    """A trade that fits exactly is one adverse tick from a margin call."""
    eng = RiskEngine(RiskLimits(min_free_margin_pct=0.20, max_position_exposure_pct=0,
                                max_total_exposure_pct=0, max_leverage=0))
    ctx = context(account=AccountState(equity=10_000.0, used_margin=7_000.0))
    d = eng.evaluate(ctx)
    assert d.approved
    assert (3_000.0 - d.quantity * 100.0) >= 2_000.0 - 1e-6


def test_no_free_margin_is_a_refusal():
    eng = RiskEngine(RiskLimits(min_free_margin_pct=0.20, max_open_positions=0,
                                max_account_risk_pct=0, max_correlated_positions=0,
                                max_position_exposure_pct=0, max_total_exposure_pct=0,
                                max_leverage=0))
    ctx = context(account=AccountState(equity=10_000.0, used_margin=9_000.0))
    d = eng.evaluate(ctx)
    assert not d.approved and d.rule == "margin"


# ═══════════════════════════════ 9. trade validation

@pytest.mark.parametrize("bad,why", [
    (dict(stop=100.0), "stop equals entry"),
    (dict(stop=105.0), "long stop above entry"),
    (dict(entry=0.0), "no entry price"),
    (dict(stop=0.0), "no stop"),
])
def test_an_incoherent_trade_is_refused(engine, bad, why):
    d = engine.evaluate(context(proposal=proposal(**bad)))
    assert not d.approved, why
    assert "trade_validation" in {v.rule for v in d.violations}


def test_a_short_stop_must_be_above_entry(engine):
    ok = proposal(direction=Direction.SHORT, entry=100.0, stop=105.0)
    bad = proposal(direction=Direction.SHORT, entry=100.0, stop=95.0)
    assert engine.evaluate(context(proposal=ok)).approved
    assert not engine.evaluate(context(proposal=bad)).approved


def test_a_zero_equity_account_cannot_trade(engine):
    d = engine.evaluate(context(account=AccountState(equity=0.0)))
    assert not d.approved


# ═══════════════════════════════ 10. kill switch

def test_the_kill_switch_blocks_everything(engine):
    d = engine.evaluate(context(kill_switch_engaged=True,
                                kill_switch_reason="daily loss breached"))
    assert not d.approved and d.rule == "kill_switch"
    assert "daily loss breached" in d.reason


def test_nothing_can_argue_past_a_halt(engine):
    """A perfect trade on a healthy account is still refused. A halt a
    well-sized trade could argue past is not a halt."""
    d = engine.evaluate(context(kill_switch_engaged=True))
    assert not d.approved


def test_the_kill_switch_short_circuits_the_rest(engine):
    """Nothing after a halt is worth computing, and a halt decision cluttered
    with fifteen other verdicts buries the one that matters."""
    d = engine.evaluate(context(kill_switch_engaged=True))
    assert len(d.checks) == 1 and d.checks[0].rule == "kill_switch"


def test_is_halted_matches_the_port(engine):
    assert engine.is_halted(context(kill_switch_engaged=True)) is True
    assert engine.is_halted(context()) is False


# ═══════════════════════════════ 11. volatility adjustment

def test_high_volatility_scales_the_size_down():
    eng = RiskEngine(RiskLimits(volatility_reference_pct=0.02,
                                max_position_exposure_pct=0, max_total_exposure_pct=0,
                                max_leverage=0, min_free_margin_pct=0))
    calm = eng.evaluate(context(market=MarketConditions(atr_pct=0.02)))
    wild = eng.evaluate(context(market=MarketConditions(atr_pct=0.08)))
    assert wild.quantity < calm.quantity


def test_low_volatility_does_not_scale_size_up():
    """Only the proven-edge boost may increase size; a quiet market is not
    evidence of an edge."""
    eng = RiskEngine(RiskLimits(volatility_reference_pct=0.02,
                                max_position_exposure_pct=0, max_total_exposure_pct=0,
                                max_leverage=0, min_free_margin_pct=0))
    calm = eng.evaluate(context(market=MarketConditions(atr_pct=0.001)))
    ref = eng.evaluate(context(market=MarketConditions(atr_pct=0.02)))
    assert calm.quantity == pytest.approx(ref.quantity)


def test_the_volatility_scale_has_a_floor():
    """A volatile market reduces size rather than reducing it to nothing."""
    limits = RiskLimits(volatility_reference_pct=0.02, min_volatility_scale=0.25)
    result = R.volatility_adjustment(context(market=MarketConditions(atr_pct=10.0)), limits)
    assert result.scale == pytest.approx(0.25)


def test_an_extreme_market_can_be_refused_outright():
    """A hard 'not here', distinct from 'smaller here' — reducing size in a
    market where the stop is meaningless is the wrong response."""
    eng = RiskEngine(RiskLimits(max_volatility_pct=0.10))
    d = eng.evaluate(context(market=MarketConditions(atr_pct=0.15, cluster="crypto")))
    assert not d.approved and "volatility_ceiling" in {v.rule for v in d.violations}


# ═══════════════════════════════ 12. news blackout

def test_an_imminent_event_blocks_entry():
    eng = RiskEngine(RiskLimits(news_blackout_minutes=30))
    d = eng.evaluate(context(market=MarketConditions(minutes_to_news=10, cluster="crypto")))
    assert not d.approved and "news_blackout" in {v.rule for v in d.violations}


def test_the_blackout_covers_the_window_after_an_event_too():
    """Spreads stay wide after the print, not only before it."""
    eng = RiskEngine(RiskLimits(news_blackout_minutes=30))
    d = eng.evaluate(context(market=MarketConditions(minutes_to_news=-10, cluster="crypto")))
    assert not d.approved


def test_an_event_outside_the_window_does_not_block():
    eng = RiskEngine(RiskLimits(news_blackout_minutes=30))
    assert eng.evaluate(context(
        market=MarketConditions(minutes_to_news=120, cluster="crypto"))).approved


def test_no_known_event_is_different_from_an_event_right_now():
    """Conflating them would either blackout permanently or never."""
    limits = RiskLimits(news_blackout_minutes=30)
    unknown = R.news_blackout(context(market=MarketConditions(minutes_to_news=None)), limits)
    now = R.news_blackout(context(market=MarketConditions(minutes_to_news=0)), limits)
    assert unknown.passed and unknown.context["evaluated"] is False
    assert now.failed


# ═══════════════════════════════ 13. session filters

def test_outside_the_session_window_is_refused():
    eng = RiskEngine(RiskLimits(session_start_hour=8, session_end_hour=16))
    early = datetime(2026, 1, 5, 3, tzinfo=timezone.utc)
    d = eng.evaluate(context(now=early))
    assert not d.approved and "session_filter" in {v.rule for v in d.violations}


def test_inside_the_session_window_is_allowed():
    eng = RiskEngine(RiskLimits(session_start_hour=8, session_end_hour=16))
    assert eng.evaluate(context(now=MONDAY_NOON)).approved


def test_a_session_that_wraps_midnight_is_handled():
    """21:00–06:00 is expressed start > end and must not be read as an empty
    window that refuses everything."""
    limits = RiskLimits(session_start_hour=21, session_end_hour=6)
    at_23 = R.session_filter(context(now=datetime(2026, 1, 5, 23, tzinfo=timezone.utc)), limits)
    at_03 = R.session_filter(context(now=datetime(2026, 1, 5, 3, tzinfo=timezone.utc)), limits)
    at_12 = R.session_filter(context(now=MONDAY_NOON), limits)
    assert at_23.passed and at_03.passed and at_12.failed


def test_a_disallowed_weekday_is_refused():
    weekdays_only = RiskLimits(trading_days_mask=0b0011111)      # Mon-Fri
    eng = RiskEngine(weekdays_only)
    saturday = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    assert not eng.evaluate(context(now=saturday)).approved
    assert eng.evaluate(context(now=MONDAY_NOON)).approved


# ═══════════════════════════════ reporting

def test_a_rejection_reports_every_failing_rule(engine):
    """Being refused, fixing one thing, and being refused again for a second
    is worse than being told both at once."""
    ctx = context(
        account=AccountState(equity=9_000.0, starting_equity=10_000.0,
                             peak_equity=12_000.0, realized_pnl_today=-500.0,
                             realized_pnl_week=-1_000.0),
        positions=tuple(OpenPosition(f"S{i}", Direction.LONG, qty=1, entry=10, stop=9,
                                     cluster="crypto") for i in range(3)))
    d = engine.evaluate(ctx)
    failing = {v.rule for v in d.violations}
    assert len(failing) >= 3, f"only reported {failing}"


def test_every_rule_reports_what_it_measured_even_when_it_passes(engine):
    """'daily loss -1.2% of -3.0%' is the line that tells an operator how close
    they are; a log containing only failures cannot answer that."""
    d = engine.evaluate(context())
    assert all(c.detail for c in d.checks)


def test_explain_names_the_rules_not_just_blocked_by_risk(engine):
    d = engine.evaluate(context(kill_switch_engaged=True, kill_switch_reason="halt"))
    assert "kill_switch" in d.explain()


def test_an_approval_explains_its_size(engine):
    assert "APPROVED" in engine.evaluate(context()).explain()


def test_the_decision_serialises_for_a_log(engine):
    import json
    d = engine.evaluate(context())
    payload = d.as_dict()
    json.dumps(payload)
    assert payload["approved"] is True and payload["limits"] == "pipeline_parity"


def test_the_decision_records_which_limits_were_in_force(engine):
    """A rejection that cannot say which limits produced it is unauditable."""
    assert engine.evaluate(context()).limits_name == "pipeline_parity"
    assert RiskEngine(CONSERVATIVE).evaluate(context()).limits_name == "conservative"


# ═══════════════════════════════ failure behaviour

def test_a_rule_that_raises_fails_closed():
    """A risk check that errors has not approved anything. Treating an
    exception as a pass is how a broken feed silently disables a guard."""
    def exploding(ctx, limits):
        raise RuntimeError("feed down")

    eng = RiskEngine(RiskLimits(),
                     blocking_rules=(R.kill_switch, exploding))
    d = eng.evaluate(context())
    assert not d.approved and "exploding" in {v.rule for v in d.violations}
    assert "refusing the trade" in d.reason


def test_a_quantity_rule_that_raises_also_fails_closed():
    def exploding(ctx, limits, qty):
        raise RuntimeError("bad")

    eng = RiskEngine(RiskLimits(), quantity_rules=(exploding,))
    d = eng.evaluate(context())
    assert not d.approved


def test_disabled_limits_are_reported_as_disabled_not_silently_skipped():
    limits = RiskLimits(max_daily_loss_pct=0, max_weekly_loss_pct=0,
                        news_blackout_minutes=0)
    for rule in (R.daily_drawdown, R.weekly_drawdown, R.news_blackout):
        assert rule(context(), limits).detail == "disabled"


def test_a_zero_limit_disables_rather_than_refusing_everything():
    """0 means 'no cap' consistently, so a partially-configured engine cannot
    accidentally enforce a limit of zero."""
    eng = RiskEngine(RiskLimits(max_open_positions=0, max_total_exposure_pct=0,
                                max_account_risk_pct=0, max_correlated_positions=0,
                                max_position_exposure_pct=0, max_leverage=0,
                                min_free_margin_pct=0))
    ctx = context(positions=tuple(
        OpenPosition(f"S{i}", Direction.LONG, qty=5, entry=100, stop=95, cluster="crypto")
        for i in range(10)))
    assert eng.evaluate(ctx).approved


# ═══════════════════════════════ presets

def test_the_conservative_preset_is_stricter_than_pipeline_parity():
    """Compared with exposure caps lifted, so the presets' RISK settings are
    what is measured. Left on, both are capped to the same notional and the
    comparison would pass or fail for an unrelated reason."""
    ctx = context()
    off = dict(max_position_exposure_pct=0, max_total_exposure_pct=0,
               max_leverage=0, min_free_margin_pct=0)
    strict = RiskEngine(CONSERVATIVE.with_(**off)).evaluate(ctx)
    normal = RiskEngine(PIPELINE_PARITY.with_(**off)).evaluate(ctx)
    assert strict.quantity < normal.quantity
    assert strict.risk_pct < normal.risk_pct


def test_limits_are_frozen_so_they_cannot_change_mid_decision():
    limits = RiskLimits()
    with pytest.raises(Exception):
        limits.max_leverage = 100        # type: ignore[misc]


def test_with_returns_a_copy_rather_than_mutating():
    base = RiskLimits(name="base")
    tweaked = base.with_(max_leverage=3.0)
    assert base.max_leverage == 1.0 and tweaked.max_leverage == 3.0
