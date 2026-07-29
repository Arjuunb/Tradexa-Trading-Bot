"""Position-sizing arithmetic, extracted from the pipeline.

The important test here is `test_matches_the_original_expression_exactly`: it
recomputes the ORIGINAL inline expression, verbatim, across a grid of inputs
and asserts bit-identical equality with the extracted function. "I copied it
carefully" is not evidence when the output decides how much money goes on a
trade.
"""
from __future__ import annotations

import itertools

import pytest

from tradexa.risk.sizing import (
    CONFIDENCE_FLOOR, CONTEXT_MAX, CONTEXT_MIN,
    RiskFactors, clamp_context, describe_factors, effective_risk,
)


# ── the differential check ──────────────────────────────────────────────────

def _original(base, confidence, kf, ef, lf, af, econ_risk, bf, xf, sfm, stf):
    """The expression exactly as it appears in SignalPipeline._process.

    Transcribed rather than imported, deliberately: importing would test the
    extraction against itself. If someone edits the pipeline's arithmetic and
    not this, the test fails — which is the point, because the two must not
    diverge silently.
    """
    eff_risk = base * (0.5 + 0.5 * confidence)
    eff_risk *= kf * ef * lf * af * econ_risk * bf * xf * sfm * stf
    return eff_risk


# A grid rather than a handful of cases: floating-point multiplication is not
# associative, so a regrouping bug shows up on some value combinations and not
# others. 3^5 x a few = a few hundred comparisons, still instant.
_VALUES = (0.5, 1.0, 1.25)


@pytest.mark.parametrize("confidence", (0.0, 0.5, 0.8, 1.0))
@pytest.mark.parametrize("kf,ef,lf", list(itertools.product(_VALUES, repeat=3)))
def test_matches_the_original_expression_exactly(confidence, kf, ef, lf):
    base = 0.01
    af, econ, bf, xf, sfm, stf = 1.2, 0.9, 1.1, 0.75, 0.95, 0.8
    expected = _original(base, confidence, kf, ef, lf, af, econ, bf, xf, sfm, stf)
    got = effective_risk(base, RiskFactors(
        confidence=confidence, kelly=kf, equity_curve=ef, learned=lf,
        allocator=af, event=econ, boost=bf, context=xf, side=sfm, streak=stf))
    assert got == expected, "extraction changed the arithmetic"


def test_all_neutral_factors_leave_full_risk_at_full_confidence():
    assert effective_risk(0.01, RiskFactors(confidence=1.0)) == pytest.approx(0.01)


# ── conviction ──────────────────────────────────────────────────────────────

def test_confidence_maps_onto_the_documented_band():
    assert RiskFactors(confidence=1.0).conviction == 1.0
    assert RiskFactors(confidence=0.5).conviction == 0.75
    assert RiskFactors(confidence=0.0).conviction == CONFIDENCE_FLOOR


def test_zero_confidence_still_sizes_something():
    """A low-confidence signal that passed all twenty-two gates is a trade.
    Sizing it to nothing would convert a 'yes' into a 'no' after the decision
    was made."""
    assert effective_risk(0.01, RiskFactors(confidence=0.0)) > 0


# ── the multiplication is a veto chain, not an average ──────────────────────

def test_any_single_factor_can_halve_the_size_alone():
    """Each subsystem holds an independent veto on size."""
    for field in ("kelly", "equity_curve", "learned", "allocator", "event",
                  "context", "side", "streak"):
        risk = effective_risk(0.01, RiskFactors(**{field: 0.5}))
        assert risk == pytest.approx(0.005), field


def test_two_cautious_factors_compound_rather_than_cancel():
    """Averaging would let a confident allocator paper over a collapsed Kelly
    factor. Multiplying means both opinions are respected."""
    both = effective_risk(0.01, RiskFactors(kelly=0.5, streak=0.5))
    assert both == pytest.approx(0.0025)


def test_a_generous_factor_does_not_rescue_a_throttled_one():
    risk = effective_risk(0.01, RiskFactors(kelly=0.5, allocator=2.0))
    assert risk == pytest.approx(0.01)     # 0.5 x 2.0, not max() or mean()


# ── the boost guard ─────────────────────────────────────────────────────────

def test_throttling_reports_the_most_pessimistic_defensive_factor():
    """Drives the caller's decision on whether the edge boost is allowed:
    defense outranks offense."""
    f = RiskFactors(kelly=0.9, equity_curve=0.4, learned=1.0, event=1.0)
    assert f.throttling == pytest.approx(0.4)


def test_throttling_ignores_the_non_defensive_factors():
    """The allocator and the boost are not defensive signals — a small sleeve
    is a capital decision, not a warning."""
    f = RiskFactors(allocator=0.1, boost=2.0, streak=0.2)
    assert f.throttling == 1.0


# ── context clamp ───────────────────────────────────────────────────────────

def test_context_is_bounded_at_both_ends():
    assert clamp_context(0.1) == CONTEXT_MIN
    assert clamp_context(5.0) == CONTEXT_MAX
    assert clamp_context(0.7) == pytest.approx(0.7)


def test_a_broken_context_feed_is_neutral_rather_than_fatal():
    """An upstream feed returning junk must not size a trade, and must not
    raise inside the trading loop."""
    assert clamp_context(None) == CONTEXT_MAX
    assert clamp_context("nonsense") == CONTEXT_MAX


# ── the decision-log note ───────────────────────────────────────────────────

def test_a_clean_signal_notes_only_its_confidence():
    """Nine '× 1.00' terms would bury the one that mattered."""
    assert describe_factors(RiskFactors(confidence=0.8)) == "conf 0.80"


def test_a_throttled_factor_is_named_with_its_value():
    note = describe_factors(RiskFactors(confidence=1.0, kelly=0.5))
    assert note == "conf 1.00 × kelly 0.50"


def test_the_boost_appears_only_when_it_lifts():
    assert "edge" not in describe_factors(RiskFactors(boost=1.0))
    assert "edge 1.20" in describe_factors(RiskFactors(boost=1.2))


def test_the_allocator_appears_whenever_it_is_not_neutral():
    """A 1.5x sleeve explains a large size as much as a 0.5x sleeve explains a
    small one, so this one is reported in both directions."""
    assert "alloc 1.50" in describe_factors(RiskFactors(allocator=1.5))
    assert "alloc 0.50" in describe_factors(RiskFactors(allocator=0.5))
    assert "alloc" not in describe_factors(RiskFactors(allocator=1.0))


def test_the_note_lists_factors_in_a_stable_order():
    """So two decision-log entries for the same situation read identically and
    can be compared."""
    f = RiskFactors(confidence=0.9, kelly=0.8, streak=0.7, context=0.6)
    assert describe_factors(f) == "conf 0.90 × kelly 0.80 × context 0.60 × streak 0.70"


def test_the_note_and_the_number_cannot_disagree():
    """Every factor the note mentions must have actually moved the result."""
    f = RiskFactors(confidence=1.0, kelly=0.5, streak=0.5)
    note = describe_factors(f)
    assert "kelly" in note and "streak" in note
    assert effective_risk(0.01, f) < 0.01
