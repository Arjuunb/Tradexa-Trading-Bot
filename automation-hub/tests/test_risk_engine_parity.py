"""Differential harness: the standalone Risk Engine vs the live pipeline.

Step one of routing production through ``tradexa.risk``. Nothing is switched
over here. This file runs BOTH decision paths over a grid of scenarios and
compares their verdicts, so any disagreement shows up as a test failure rather
than as a live trade.

Every disagreement is one of two things, and both are worth finding before a
switch rather than after:

    the new engine has a bug          — fix the engine
    the pipeline has an undocumented rule — the new engine is missing it

Neither is discoverable by reading the two implementations side by side, which
is why this is a harness and not a code review.

What is compared, and what deliberately is not:

*Compared:* whether a trade is allowed at all. That is the safety-critical
property — a trade the pipeline refuses must not become one the engine allows.

*Not compared:* the exact quantity. The pipeline applies nine strategy-derived
modifiers (Kelly, learning store, allocator, streak) that the standalone engine
deliberately does not know about, because knowing about them would make it
depend on strategies. Identical sizes were never the goal; the engine being at
least as conservative is.

That asymmetry is the whole point and is asserted directly: the engine may
size SMALLER than the pipeline, never larger.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline

from tradexa.risk import (
    AccountState, Direction, MarketConditions, OpenPosition, PIPELINE_PARITY,
    RiskContext, RiskEngine, TradeProposal,
)

MONDAY_NOON = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
EQUITY = 10_000.0


@dataclass
class Scenario:
    """One situation, expressed once and fed to both decision paths.

    Stated in neutral terms rather than in either engine's vocabulary, so the
    translation to each is visible and neither gets a home-field advantage.
    """

    name: str
    entry: float = 100.0
    stop: Optional[float] = 95.0
    confidence: float = 0.9
    open_positions: int = 0
    realized_today: float = 0.0
    equity: float = EQUITY
    paused: bool = False

    # ---------------------------------------------------------------- adapt
    def to_alert(self) -> dict:
        return {"alert_id": f"parity-{self.name}", "symbol": "BTCUSDT",
                "side": "BUY", "entry": self.entry, "stop": self.stop,
                "confidence": self.confidence}

    def to_context(self) -> RiskContext:
        # qty 5 @ 100 is what the pipeline ACTUALLY opens for the seed alert
        # below — 500 notional each. An earlier version used 0.01 here, and the
        # harness reported a divergence that was purely its own: the pipeline
        # was at its exposure cap while the engine saw a near-empty book. A
        # differential test comparing two different states compares nothing.
        positions = tuple(
            OpenPosition(f"FILLER{i}", Direction.LONG, qty=5.0, entry=100.0,
                         stop=99.0, cluster="other")
            for i in range(self.open_positions))
        return RiskContext(
            proposal=TradeProposal(
                symbol="BTCUSDT", direction=Direction.LONG, entry=self.entry,
                # The engine validates the stop itself, so an absent stop is
                # passed through as an obviously-invalid one rather than being
                # filtered here. Sanitising the input would hide the very
                # divergence this harness exists to find.
                stop=self.stop if self.stop is not None else self.entry,
                confidence=self.confidence),
            account=AccountState(equity=self.equity, starting_equity=EQUITY,
                                 cash=self.equity,
                                 realized_pnl_today=self.realized_today),
            positions=positions,
            market=MarketConditions(cluster="crypto"),
            now=MONDAY_NOON,
            kill_switch_engaged=self.paused,
            kill_switch_reason="trading paused" if self.paused else "")


def _build_pipeline(scenario: Scenario) -> SignalPipeline:
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=scenario.equity,
                          risk_per_trade_pct=PIPELINE_PARITY.risk_per_trade_pct,
                          max_open_positions=PIPELINE_PARITY.max_open_positions,
                          max_daily_loss_pct=PIPELINE_PARITY.max_daily_loss_pct,
                          exposure_limit_pct=PIPELINE_PARITY.max_position_exposure_pct,
                          max_total_exposure_pct=PIPELINE_PARITY.max_total_exposure_pct)
    if scenario.paused:
        pipe.controls.pause_all()
    for i in range(scenario.open_positions):
        pipe.process({"alert_id": f"seed-{i}", "symbol": f"FILLER{i}",
                      "side": "BUY", "entry": 100.0, "stop": 99.0,
                      "confidence": 1.0})
    return pipe


# ── the scenario grid ───────────────────────────────────────────────────────
# Chosen to hit each side of every shared boundary. A grid of only-valid or
# only-invalid cases would agree trivially and prove nothing.
SCENARIOS = [
    Scenario("clean"),
    Scenario("tight_stop", stop=99.5),
    Scenario("wide_stop", stop=80.0),
    Scenario("low_confidence", confidence=0.1),
    Scenario("full_confidence", confidence=1.0),
    Scenario("no_stop", stop=None),
    Scenario("stop_equals_entry", stop=100.0),
    Scenario("stop_wrong_side", stop=105.0),
    Scenario("zero_entry", entry=0.0),
    Scenario("paused", paused=True),
    Scenario("at_position_cap", open_positions=3),
    Scenario("one_below_position_cap", open_positions=2),
]

# NOT in the grid, and the omission is deliberate rather than an oversight:
#
#   daily / weekly loss — the pipeline reads realised P&L from its paper
#   engine, and the harness has no seam to inject one without executing and
#   closing real trades first. Setting the figure on the RiskContext alone
#   compares an engine that has seen a loss against a pipeline that has not,
#   which is a harness artefact dressed up as a finding. Both sides' loss
#   limits are covered by their own tests instead.
#
# Adding a scenario here that cannot be expressed identically on both sides
# would make this file report divergences it invented.


def _pipeline_allows(scenario: Scenario) -> bool:
    return bool(_build_pipeline(scenario).process(scenario.to_alert()).accepted)


def _engine_allows(scenario: Scenario) -> tuple[bool, float]:
    d = RiskEngine(PIPELINE_PARITY).evaluate(scenario.to_context())
    return d.approved, d.quantity


# ── the comparison ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_the_engine_never_allows_what_the_pipeline_refuses(scenario):
    """The safety-critical direction.

    The reverse — the engine refusing something the pipeline allows — is
    acceptable and tracked separately: a stricter engine is a safe engine, and
    the standalone one enforces limits (leverage, margin, account risk) the
    pipeline has never had.
    """
    pipeline_ok = _pipeline_allows(scenario)
    engine_ok, _ = _engine_allows(scenario)
    if not pipeline_ok:
        assert not engine_ok, (
            f"[{scenario.name}] the pipeline REFUSED this trade and the "
            "standalone engine would have allowed it — the engine is missing "
            "a rule the pipeline enforces")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_an_invalid_trade_is_refused_by_both(scenario):
    """Trade validity is the one area both must agree on exactly. A malformed
    trade is not a risk judgement — it is arithmetic that cannot be done."""
    if scenario.name not in ("no_stop", "stop_equals_entry", "stop_wrong_side",
                             "zero_entry"):
        pytest.skip("not a validity scenario")
    assert not _pipeline_allows(scenario)
    assert not _engine_allows(scenario)[0]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_the_engine_never_sizes_larger_than_the_pipeline(scenario):
    """The asymmetry that makes the switch safe.

    Identical sizes were never the goal — the pipeline applies nine
    strategy-derived modifiers the standalone engine deliberately does not know
    about. Being at least as conservative IS the goal, and it is the property
    that makes routing production through the engine incapable of increasing
    risk on any trade.
    """
    pipeline_ok = _pipeline_allows(scenario)
    engine_ok, engine_qty = _engine_allows(scenario)
    if not (pipeline_ok and engine_ok):
        pytest.skip("only comparable when both approve")

    pipe = _build_pipeline(scenario)
    result = pipe.process(scenario.to_alert())
    pipeline_qty = float((result.fill or {}).get("size") or 0.0)
    assert pipeline_qty > 0, "pipeline approved but reported no size"
    assert engine_qty <= pipeline_qty * 1.000001, (
        f"[{scenario.name}] the standalone engine sized LARGER "
        f"({engine_qty:.6f}) than the pipeline ({pipeline_qty:.6f})")


def test_both_agree_a_clean_trade_is_allowed():
    """Guards the guard: if every scenario were refused by both, the harness
    would pass while comparing nothing."""
    clean = Scenario("clean")
    assert _pipeline_allows(clean) and _engine_allows(clean)[0]


def test_the_grid_covers_both_outcomes():
    """A grid of only-valid or only-invalid cases agrees trivially."""
    verdicts = {_pipeline_allows(s) for s in SCENARIOS}
    assert verdicts == {True, False}, "the scenario grid is one-sided"


# ── divergence report ───────────────────────────────────────────────────────

def test_report_where_the_two_disagree():
    """Not an assertion — a printed inventory of every divergence.

    Each line is a decision someone has to make before the switch: either the
    engine gains the pipeline's rule, or the difference is deliberate and gets
    recorded. Printing rather than failing keeps the safety assertions above
    meaningful; a test that failed on every acceptable difference would be
    turned off within a week.
    """
    rows = []
    for s in SCENARIOS:
        p_ok = _pipeline_allows(s)
        e_ok, e_qty = _engine_allows(s)
        if p_ok != e_ok:
            direction = ("engine STRICTER" if p_ok and not e_ok
                         else "engine LOOSER — investigate")
            rows.append(f"  {s.name:26s} pipeline={p_ok!s:5s} engine={e_ok!s:5s}  {direction}")
    print("\n=== risk verdict divergences ===")
    print("\n".join(rows) if rows else "  none — both paths agree on every scenario")
    # Only the dangerous direction fails, and it is already asserted above.
    assert not [r for r in rows if "LOOSER" in r], "\n".join(rows)
