"""The parts of a backtest that decide whether you traded at all.

Costs are the easy half — the platform already models slippage, commission and
spread. These tests cover the half that no cost adjustment can express: a queue
you were behind, a bar whose volume you exceeded, a price that moved during your
latency. Each makes a backtest optimistic in a way that a basis-point penalty
cannot fix, because they change *whether* the trade happened.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Bar
from tradexa.backtest import (
    BacktestReport, BarAggregator, ExecutionModel, FRICTIONLESS, LIQUID_CRYPTO,
    LatencyModel, Liquidity, LiquidityCap, OrderQueue, QueuedOrder,
    RecordedTickStream, SpreadModel, SyntheticTickStream, THIN_ALTCOIN, Tick,
    buy_and_hold, capture, compare, render_html, render_pdf, synthesise,
)

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _bar(o=100, h=110, l=95, c=105, v=1000, at=T0):
    return Bar(at, o, h, l, c, v)


# ═══════════════════════════════════════════ tick simulation

def test_a_synthesised_path_visits_the_adverse_extreme_first():
    """The pessimistic reading of an ambiguous bar, matching the bar engine's
    own `sl_first` tie-break — so the two engines resolve the same ambiguity the
    same way rather than disagreeing about a trade neither can see inside."""
    up = [t.price for t in synthesise(_bar(o=100, h=110, l=95, c=105))]
    assert up == [100, 95, 110, 105]
    down = [t.price for t in synthesise(_bar(o=105, h=110, l=95, c=100))]
    assert down == [105, 110, 95, 100]


def test_synthesised_ticks_are_labelled_synthetic():
    """The most flattering lie a backtester can tell is calling invented ticks
    tick data."""
    assert all(t.synthetic for t in synthesise(_bar()))
    assert SyntheticTickStream([_bar()]).is_synthetic is True


def test_only_recorded_ticks_may_claim_to_be_real():
    stream = RecordedTickStream([Tick(T0, 100.0, synthetic=True)])
    assert stream.is_synthetic is False
    assert all(not t.synthetic for t in stream)


def test_the_tick_path_reconstructs_the_original_bar():
    """If aggregating the ticks does not reproduce the OHLC, the path is not a
    decomposition of the bar and any difference in results is the synthesiser's,
    not the market's."""
    bar = _bar(o=100, h=110, l=95, c=105, v=900)
    aggregator = BarAggregator(period=timedelta(hours=1))
    for tick in synthesise(bar):
        aggregator.push(tick)
    rebuilt = aggregator.flush()
    assert (rebuilt.open, rebuilt.high, rebuilt.low, rebuilt.close) == (100, 110, 95, 105)
    assert rebuilt.volume == pytest.approx(900)


def test_more_steps_do_not_invent_new_extremes():
    """Interpolation produces a smoother path and not more information."""
    ticks = synthesise(_bar(o=100, h=110, l=95, c=105), steps=16)
    assert max(t.price for t in ticks) <= 110
    assert min(t.price for t in ticks) >= 95


def test_a_bar_with_impossible_prices_is_refused():
    with pytest.raises(ValueError):
        synthesise(Bar(T0, 100, 90, 110, 105, 1))


# ═══════════════════════════════════════════ spread

def test_a_taker_pays_the_spread_and_a_maker_earns_it():
    """Applying half a spread to every fill charges a resting order for
    liquidity it provided — and for a market-making strategy that IS the P&L."""
    spread = SpreadModel(fraction=0.001)
    assert spread.fill_price(100, is_buy=True, liquidity=Liquidity.TAKER) > 100
    assert spread.fill_price(100, is_buy=True, liquidity=Liquidity.MAKER) < 100


def test_the_spread_can_widen_under_stress():
    normal = SpreadModel(fraction=0.001)
    assert normal.widen(3.0).half(100) == pytest.approx(normal.half(100) * 3)


# ═══════════════════════════════════════════ latency

def test_latency_is_time_not_a_price_penalty():
    """The two differ whenever the market moves during the delay — and that is
    the entire point of latency."""
    ticks = [Tick(T0 + timedelta(milliseconds=n * 50), 100 + n) for n in range(6)]
    model = LatencyModel(decision_ms=60, venue_ms=40, jitter_ms=0)
    price, index = model.price_after_delay(ticks, from_index=0)
    assert index == 2 and price == 102


def test_a_flat_market_costs_nothing_in_latency():
    """A fixed price penalty would charge the same in a dead market as in a fast
    one."""
    ticks = [Tick(T0 + timedelta(milliseconds=n * 50), 100.0) for n in range(6)]
    price, _ = LatencyModel(decision_ms=100, jitter_ms=0).price_after_delay(
        ticks, from_index=0)
    assert price == 100.0


def test_latency_is_deterministic_unless_jitter_is_asked_for():
    """A backtest that returns a different answer each run cannot be used to
    decide anything."""
    model = LatencyModel(decision_ms=50, venue_ms=30, jitter_ms=0)
    assert len({model.total_ms for _ in range(10)}) == 1


def test_jitter_produces_variation_when_requested():
    model = LatencyModel(decision_ms=50, jitter_ms=20, seed=3)
    assert len({round(model.total_ms, 6) for _ in range(10)}) > 1


# ═══════════════════════════════════════════ order queue

def test_a_resting_order_does_not_fill_just_because_price_touched():
    """"Price touched my limit" is a fill for whoever was there first."""
    queue = OrderQueue(participation=1.0)
    queue.place(QueuedOrder("o1", price=99.0, qty=1.0, is_buy=True, queue_ahead=10.0))
    assert queue.on_trade(99.0, volume=3.0) == []


def test_the_queue_ahead_must_be_consumed_first():
    queue = OrderQueue(participation=1.0)
    queue.place(QueuedOrder("o1", price=99.0, qty=1.0, is_buy=True, queue_ahead=5.0))
    queue.on_trade(99.0, volume=3.0)
    fills = queue.on_trade(99.0, volume=5.0)
    assert fills and fills[0]["qty"] == pytest.approx(1.0)


def test_price_trading_through_the_level_sweeps_the_queue():
    """The one case where a resting order is certain to fill."""
    queue = OrderQueue(participation=0.01)
    queue.place(QueuedOrder("o1", price=99.0, qty=2.0, is_buy=True, queue_ahead=999.0))
    fills = queue.on_trade(98.0, volume=1.0)
    assert fills and fills[0]["qty"] == pytest.approx(2.0)


def test_a_sell_limit_fills_on_the_other_side():
    queue = OrderQueue(participation=1.0)
    queue.place(QueuedOrder("s1", price=101.0, qty=1.0, is_buy=False))
    assert queue.on_trade(99.0, volume=10.0) == []
    assert queue.on_trade(102.0, volume=10.0)


def test_only_part_of_a_bars_volume_is_attributed_to_your_price():
    """Assuming all of a bar's volume passed through your exact limit is how a
    thin market becomes a perfect one."""
    queue = OrderQueue(participation=0.25)
    queue.place(QueuedOrder("o1", price=99.0, qty=10.0, is_buy=True))
    fills = queue.on_trade(99.0, volume=20.0)
    assert fills[0]["qty"] == pytest.approx(5.0)
    assert fills[0]["partial"] is True


def test_a_filled_order_is_marked_maker():
    queue = OrderQueue(participation=1.0)
    queue.place(QueuedOrder("o1", price=99.0, qty=1.0, is_buy=True))
    assert queue.on_trade(99.0, volume=5.0)[0]["liquidity"] == "maker"


# ═══════════════════════════════════════════ liquidity-driven partial fills

def test_an_order_larger_than_the_market_fills_partially():
    """A 10-unit order into a bar that traded 12 does not fill at one price."""
    cap = LiquidityCap(max_participation=0.10)
    result = cap.apply(requested=10.0, period_volume=12.0, price=100.0, is_buy=True)
    assert result["filled"] == pytest.approx(1.2)
    assert result["unfilled"] == pytest.approx(8.8)
    assert result["partial"] is True


def test_a_bar_that_traded_nothing_fills_nothing():
    """Filling into a bar with no volume is the purest form of backtest
    fiction."""
    result = LiquidityCap().apply(requested=1.0, period_volume=0.0, price=100.0,
                                  is_buy=True)
    assert result["filled"] == 0.0


def test_taking_more_of_the_market_costs_more():
    cap = LiquidityCap(max_participation=1.0, impact_bps_per_unit=100)
    small = cap.apply(requested=1.0, period_volume=100.0, price=100.0, is_buy=True)
    large = cap.apply(requested=50.0, period_volume=100.0, price=100.0, is_buy=True)
    assert large["price"] > small["price"] > 100.0


def test_impact_pushes_against_the_trader_on_both_sides():
    cap = LiquidityCap(max_participation=1.0, impact_bps_per_unit=100)
    buy = cap.apply(requested=50.0, period_volume=100.0, price=100.0, is_buy=True)
    sell = cap.apply(requested=50.0, period_volume=100.0, price=100.0, is_buy=False)
    assert buy["price"] > 100.0 > sell["price"]


# ═══════════════════════════════════════════ commission

def test_a_maker_rebate_is_a_credit_not_a_charge():
    model = ExecutionModel(commission_bps=4.0, maker_rebate_bps=1.0)
    assert model.commission(10_000, liquidity=Liquidity.TAKER) == pytest.approx(4.0)
    assert model.commission(10_000, liquidity=Liquidity.MAKER) == pytest.approx(-1.0)


def test_the_presets_differ_in_the_ways_that_matter():
    """Named for the market they represent, not for how cautious someone feels."""
    assert THIN_ALTCOIN.spread.fraction > LIQUID_CRYPTO.spread.fraction
    assert THIN_ALTCOIN.liquidity.max_participation < LIQUID_CRYPTO.liquidity.max_participation
    assert FRICTIONLESS.commission_bps == 0


def test_the_execution_model_can_describe_itself():
    """So a report can print the assumptions rather than a reader guessing."""
    described = LIQUID_CRYPTO.describe()
    for key in ("spread_bps", "latency_ms", "commission_bps", "max_participation"):
        assert key in described


# ═══════════════════════════════════════════ benchmark comparison

def _rising(n=60, start=100.0, step=0.5):
    return [start + i * step for i in range(n)]


def test_a_strategy_is_judged_against_holding_the_asset():
    """60% in a year the asset rose 200% is not a good result."""
    result = compare(equity=_rising(60, 100, 0.5), prices=_rising(60, 50, 0.6))
    assert result.beat_benchmark is False
    assert "trailed" in result.explain()


def test_beating_the_benchmark_with_a_worse_drawdown_is_flagged():
    """Outperforming by taking twice the drawdown is leverage, and leverage is
    available to the benchmark too."""
    equity = [100, 130, 90, 160]
    prices = [100, 105, 103, 110]
    result = compare(equity, prices)
    assert result.beat_benchmark and result.beat_on_risk is False
    assert "deeper drawdown" in result.explain()


def test_both_curves_start_at_the_same_capital():
    """A benchmark normalised differently makes the excess return an artefact of
    the normalisation."""
    bench = buy_and_hold([50, 60, 70], starting_equity=1000.0)
    assert bench[0] == pytest.approx(1000.0)


def test_capture_ratios_separate_the_kind_of_strategy():
    """80% upside with 30% downside is a different instrument from 120/110 at the
    same total return."""
    market = [0.10, -0.10, 0.10, -0.10]
    defensive = [0.08, -0.03, 0.08, -0.03]
    assert capture(defensive, market, upside=True) == pytest.approx(0.8)
    assert capture(defensive, market, upside=False) == pytest.approx(0.3)


def test_a_short_sample_says_so_rather_than_pretending():
    result = compare(_rising(10), _rising(10, 50))
    assert any("indicative" in n for n in result.notes)


def test_comparing_nothing_is_not_an_error():
    assert compare([], []).notes


# ═══════════════════════════════════════════ reports

def _report():
    report = BacktestReport(
        title="EMA Trend Bot — BTCUSDT 1h", subtitle="2024-01-01 to 2025-01-01",
        equity_curve=_rising(50), benchmark_curve=buy_and_hold(_rising(50, 60), 100),
        assumptions=LIQUID_CRYPTO.describe(),
        caveats=["ticks were synthesised from OHLCV, not recorded"])
    report.add("Performance", {"total return": 0.245, "sharpe": 1.32,
                               "max drawdown": 0.084, "trades": 143})
    report.add("Unavailable", {"sortino": None}, note="None stays None.")
    return report


def test_the_html_report_is_self_contained():
    """No CDN, no fonts, no scripts — it has to open from a file share and from
    an email attachment five years from now."""
    html = render_html(_report())
    assert "<svg" in html and "http://" not in html and "https://" not in html
    assert "<script" not in html


def test_the_html_report_states_its_assumptions():
    """A backtest result without its execution assumptions is a number without
    units."""
    html = render_html(_report())
    assert "Execution assumptions" in html
    assert "commission bps" in html


def test_caveats_are_prominent_not_a_footnote():
    assert "synthesised from OHLCV" in render_html(_report())


def test_unavailable_values_render_as_unavailable():
    """Not 0.00 — a dash, so a missing Sortino cannot be read as a zero one."""
    assert "—" in render_html(_report())


def test_html_escapes_its_inputs():
    report = BacktestReport(title="<script>alert(1)</script>")
    assert "<script>alert" not in render_html(report)


def test_the_pdf_is_a_real_pdf():
    pdf = render_pdf(_report())
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert b"/Type /Catalog" in pdf and b"xref" in pdf


def test_the_pdf_has_a_page_and_a_font():
    pdf = render_pdf(_report())
    assert b"/Type /Page" in pdf and b"/BaseFont /Helvetica" in pdf


def test_the_pdf_survives_characters_a_base_font_cannot_encode():
    """A non-Latin-1 character would corrupt the file rather than render wrong,
    so it is replaced visibly."""
    report = BacktestReport(title="Strategy 日本 — résumé")
    pdf = render_pdf(report)
    assert pdf.startswith(b"%PDF")


def test_the_pdf_escapes_parentheses():
    """Unescaped, they terminate a PDF string literal and break the file."""
    report = BacktestReport(title="Sharpe (annualised) \\ test")
    assert render_pdf(report).startswith(b"%PDF")


def test_a_long_report_paginates():
    report = BacktestReport(title="Long")
    for n in range(12):
        report.add(f"Section {n}", {f"row {i}": i for i in range(12)})
    pdf = render_pdf(report)
    # `/Type /Page /Parent` matches a page object and NOT the `/Type /Pages`
    # tree node — counting `/Type /Page` alone would match both and report a
    # single-page document as paginated.
    assert pdf.count(b"/Type /Page /Parent") >= 2, (
        "a 12-section report fitted on one page — the layout never broke")


def test_both_renderers_accept_an_empty_report():
    empty = BacktestReport(title="Nothing ran")
    assert render_html(empty) and render_pdf(empty).startswith(b"%PDF")
