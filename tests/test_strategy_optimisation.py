"""Searching a strategy's declared parameter space.

The grid was already declared; this is what runs it. Without a consumer,
"supports optimisation" means a dictionary that looks like a plan.

Most of these use a synthetic scorer, deliberately: the search logic — bounding
the space, skipping invalid combinations, ranking, validating out of sample —
is what is under test, and a real backtest would make every assertion depend on
market data. One test drives the actual ``Backtester`` to prove the plumbing
joins up.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Bar
from tradexa.strategy import (
    BaseStrategy, Maturity, OptimisationError, ParamType, Parameter,
    StrategyMeta, candidates, grid_search, split,
)


class Tunable(BaseStrategy):
    """Two tunable knobs with a rule that rejects part of the grid."""

    meta = StrategyMeta(key="tunable", name="Tunable", maturity=Maturity.STABLE)
    parameters = (
        Parameter("fast", ParamType.INT, default=5, minimum=1, maximum=100,
                  tunable=True, optimise=(5, 10, 20)),
        Parameter("slow", ParamType.INT, default=20, minimum=1, maximum=200,
                  tunable=True, optimise=(10, 20, 40)),
        Parameter("fixed", ParamType.FLOAT, default=1.0, minimum=0.0, maximum=9.0),
    )

    @classmethod
    def validate(cls, params):
        fast, slow = params.get("fast"), params.get("slow")
        if fast is not None and slow is not None and fast >= slow:
            return (f"fast ({fast}) must be below slow ({slow})",)
        return ()

    def generate(self, bar):
        return None


def _prefer(target_fast: int):
    """A scorer that peaks at one value, so the winner is knowable."""
    return lambda cls, params: -abs(params["fast"] - target_fast)


# ═══════════════════════════════════════════ enumerating the space

def test_only_tunable_parameters_are_combined():
    valid, _ = candidates(Tunable)
    assert all(set(p) == {"fast", "slow"} for p in valid)


def test_combinations_the_strategy_rejects_are_separated_not_scored():
    """A grid that sweeps fast and slow independently proposes combinations the
    strategy itself refuses. Scoring them zero would rank them above real
    losers."""
    valid, rejected = candidates(Tunable)
    assert len(valid) + len(rejected) == 9
    assert all(p["params"]["fast"] >= p["params"]["slow"] for p in rejected)
    assert all("must be below" in p["reason"] for p in rejected)


def test_overrides_pin_the_parameters_not_being_swept():
    """Sweeping around defaults the live bot does not use produces a "best" for
    a strategy nobody is trading."""
    valid, _ = candidates(Tunable, only=("fast",), overrides={"fixed": 7.5})
    assert all(p["fixed"] == 7.5 for p in valid)


# ═══════════════════════════════════════════ running the search

def test_the_search_ranks_by_score():
    result = grid_search(Tunable, _prefer(10))
    assert result.best.params["fast"] == 10
    assert [c.score for c in result.candidates] == sorted(
        (c.score for c in result.candidates), reverse=True)


def test_the_result_reports_the_whole_search_not_just_the_winner():
    """"Best of 3 valid out of 9 proposed" and "best of 9" are different
    findings that look identical when only the top row is reported."""
    result = grid_search(Tunable, _prefer(10))
    assert result.proposed == 9
    assert result.evaluated == len(result.candidates) <= 6
    assert result.skipped


def test_a_mapping_result_keeps_the_whole_backtest_next_to_the_score():
    """So a caller does not have to re-run to find out how many trades produced
    the number — a rerun that may not reproduce."""
    result = grid_search(Tunable, lambda c, p: {"score": 1.0, "trades": 42})
    assert result.best.detail["trades"] == 42


def test_a_mapping_without_a_score_is_skipped_not_guessed():
    result = grid_search(Tunable, lambda c, p: {"trades": 42})
    assert result.evaluated == 0
    assert any("no 'score' key" in s["reason"] for s in result.skipped)


def test_an_evaluation_that_raises_is_skipped_not_scored_zero():
    """A strategy that blows up on one parameter set has told you something
    about that set. Scoring it zero ranks it above a configuration that merely
    lost money."""
    def boom(cls, params):
        if params["fast"] == 5:
            raise RuntimeError("no data for this window")
        return 1.0

    result = grid_search(Tunable, boom)
    assert any("no data for this window" in s["reason"] for s in result.skipped)
    assert all(c.params["fast"] != 5 for c in result.candidates)


def test_an_oversized_grid_is_refused_before_it_runs():
    """A five-figure sweep should be a decision someone made, not something they
    discover by waiting."""
    with pytest.raises(OptimisationError) as exc:
        grid_search(Tunable, _prefer(10), max_candidates=2)
    assert "9 combinations" in str(exc.value)
    assert "max_candidates" in str(exc.value)


def test_a_strategy_with_nothing_tunable_says_so_rather_than_returning_empty():
    class Fixed(BaseStrategy):
        meta = StrategyMeta(key="fixed2", name="Fixed")

        def generate(self, bar):
            return None

    result = grid_search(Fixed, _prefer(1))
    assert result.best is None
    assert any("nothing to optimise" in n for n in result.notes)


# ═══════════════════════════════════════════ out of sample

def test_an_unvalidated_search_says_it_is_in_sample_only():
    """Picking the best of nine on one slice of history and calling it optimal
    is overfitting with a progress bar."""
    result = grid_search(Tunable, _prefer(10))
    assert result.robust is None
    assert any("in-sample only" in n for n in result.notes)


def test_a_winner_that_holds_out_of_sample_is_marked_robust():
    result = grid_search(Tunable, _prefer(10), validate_with=lambda c, p: 2.0)
    assert result.robust is True
    assert result.best.validation_score == 2.0


def test_a_winner_that_collapses_out_of_sample_is_marked_not_robust():
    result = grid_search(Tunable, _prefer(10), validate_with=lambda c, p: -5.0)
    assert result.robust is False
    assert "did NOT hold" in result.explain()


def test_only_the_winner_is_validated():
    """Validating every candidate and then picking the best out-of-sample score
    uses the validation set to choose, which makes it a second training set with
    a reassuring name."""
    seen = []

    def validator(cls, params):
        seen.append(params)
        return 1.0

    grid_search(Tunable, _prefer(10), validate_with=validator)
    assert len(seen) == 1


def test_a_failing_validator_is_reported_not_swallowed():
    def boom(cls, params):
        raise RuntimeError("test window empty")

    result = grid_search(Tunable, _prefer(10), validate_with=boom)
    assert result.robust is None
    assert any("test window empty" in n for n in result.notes)


def test_the_split_is_chronological():
    """Shuffling bars lets a strategy be tuned on the future and validated on
    the past, which passes cleanly and means nothing."""
    data = list(range(100))
    train, test = split(data, 0.7)
    assert train == data[:70] and test == data[70:]


def test_a_nonsensical_split_is_refused():
    for fraction in (0.0, 1.0, -0.5, 2.0):
        with pytest.raises(OptimisationError):
            split(list(range(10)), fraction)


# ═══════════════════════════════════════════ end to end, real backtester

def _synthetic_bars(n=600):
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        base = 100 + 8 * math.sin(i / 25)
        o = base + 0.3 * math.sin(i / 3)
        c = base + 0.3 * math.cos(i / 4)
        bars.append(Bar(t0 + timedelta(hours=i), o, max(o, c) + 0.9,
                        min(o, c) - 0.9, c, 1000 + i))
    return bars


def test_the_search_drives_the_real_backtester():
    """The plumbing, joined up: declared grid → validated combinations → real
    backtest → ranking → out-of-sample re-score. Asserts the machinery runs and
    reports, not that a particular configuration wins — that depends on market
    data and would make this a test of the market."""
    from bot.backtester import Backtester
    from bot.strategies import SupportResistanceRejection

    train, test = split(_synthetic_bars(), 0.7)

    def score(cls, params, window):
        result = Backtester(cls(symbol="SYNTH", **params), list(window)).run()
        m = result.metrics or {}
        trades = int(m.get("num_trades", 0) or 0)
        return {"score": float(m.get("avg_r", 0.0) or 0.0) * trades,
                "trades": trades}

    result = grid_search(SupportResistanceRejection,
                         lambda c, p: score(c, p, train),
                         validate_with=lambda c, p: score(c, p, test),
                         only=("pivot", "min_touches"))
    assert result.evaluated == 9, "the real backtester did not score every candidate"
    assert result.best is not None
    assert result.best.validation_score is not None
    assert "trades" in result.best.detail
