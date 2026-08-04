"""Searching a strategy's declared parameter space.

``BaseStrategy.optimisation_grid()`` says what may be tried. This runs it —
otherwise the declaration is a field nothing reads, and "supports optimisation"
means a dictionary that looks like a plan.

The engine is a **pure function of a scoring callable**. It knows how to
enumerate candidates, skip the invalid ones and rank the results; it does not
know what a backtest is. That is what lets the same search drive a full
backtest, a paper replay, or a two-line test with a synthetic scorer.

Three properties are deliberate, and each exists because the obvious
implementation produces a number that looks like a result and is not one.

**The search space is bounded before it runs.** ``max_candidates`` refuses a
grid rather than discovering its size by waiting. A five-figure sweep should be
a decision someone made, not a surprise.

**Invalid combinations are skipped and counted, never scored.** A grid that
sweeps ``fast`` and ``slow`` independently proposes combinations the strategy
itself rejects. Silently scoring them as zero would rank real losers above
configurations that never ran.

**A winner is only a winner out of sample.** Given a second scorer,
``grid_search`` re-scores the in-sample best on unseen data and reports whether
the choice held. Picking the best of 108 candidates on one slice of history and
calling it optimal is overfitting with a progress bar — and it is exactly what
the platform's existing spec optimiser refuses to do, so the plugin optimiser
speaks the same language rather than a more flattering one.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from tradexa.strategy.base import BaseStrategy

#: Refuse a sweep larger than this unless the caller raises it explicitly.
#: Sized so a few tunable parameters fit comfortably and a cartesian explosion
#: does not: 500 backtests is minutes, 50,000 is an afternoon nobody chose.
DEFAULT_MAX_CANDIDATES = 500

#: How much better the out-of-sample score must be than the in-sample median
#: before a result is called robust. Not a significance test — a sanity floor,
#: stated rather than implied.
OUT_OF_SAMPLE_TOLERANCE = 0.0


class OptimisationError(Exception):
    """Raised before a search runs, never during one."""


@dataclass(frozen=True)
class Candidate:
    """One parameter set and what it scored."""

    params: dict[str, Any]
    score: float
    detail: Mapping[str, Any] = field(default_factory=dict)
    #: Score on data the search never saw. ``None`` when no validator was given.
    validation_score: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return {"params": dict(self.params), "score": self.score,
                "validation_score": self.validation_score,
                "detail": dict(self.detail)}


@dataclass(frozen=True)
class OptimisationResult:
    """The whole search, not just its winner.

    Carries the losers and the skipped combinations because a ranking without
    them cannot be judged: "best of 3 valid candidates out of 108 proposed" and
    "best of 108" are different findings that look identical when only the top
    row is reported.
    """

    strategy: str
    candidates: tuple[Candidate, ...] = ()
    skipped: tuple[dict[str, Any], ...] = ()
    evaluated: int = 0
    proposed: int = 0
    notes: tuple[str, ...] = ()

    @property
    def best(self) -> Optional[Candidate]:
        return self.candidates[0] if self.candidates else None

    @property
    def robust(self) -> Optional[bool]:
        """Whether the winner held up out of sample.

        ``None`` means it was never checked — which is different from checked
        and passed, and conflating them is how an unvalidated sweep gets
        reported as a validated one.
        """
        best = self.best
        if best is None or best.validation_score is None:
            return None
        return best.validation_score >= OUT_OF_SAMPLE_TOLERANCE

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "best": self.best.as_dict() if self.best else None,
            "robust": self.robust,
            "candidates": [c.as_dict() for c in self.candidates],
            "skipped": list(self.skipped),
            "evaluated": self.evaluated,
            "proposed": self.proposed,
            "notes": list(self.notes),
        }

    def explain(self) -> str:
        if not self.best:
            return f"{self.strategy}: no valid candidate scored"
        robust = {True: "held out of sample", False: "did NOT hold out of sample",
                  None: "not validated out of sample"}[self.robust]
        return (f"{self.strategy}: best {self.best.params} scored "
                f"{self.best.score:.4f} ({self.evaluated} of {self.proposed} "
                f"candidates evaluated, {robust})")


def candidates(strategy: type[BaseStrategy], *,
               only: Optional[Iterable[str]] = None,
               overrides: Optional[Mapping[str, Any]] = None
               ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every combination the grid proposes, split into valid and rejected.

    ``overrides`` pins parameters that are not being swept, so a search over
    ``fast``/``slow`` can still fix ``rr_target`` at the value the operator
    actually runs — sweeping around defaults the live bot does not use produces
    a "best" for a strategy nobody is trading.
    """
    grid = strategy.optimisation_grid(only)
    if not grid:
        return [], []
    names = list(grid)
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for combo in itertools.product(*(grid[n] for n in names)):
        params = dict(zip(names, combo))
        if overrides:
            params.update(overrides)
        result = strategy.validate_params(params)
        if result.ok:
            valid.append(params)
        else:
            rejected.append({"params": params, "reason": result.explain()})
    return valid, rejected


def grid_search(strategy: type[BaseStrategy],
                evaluate: Callable[[type[BaseStrategy], dict[str, Any]], Any],
                *,
                only: Optional[Iterable[str]] = None,
                overrides: Optional[Mapping[str, Any]] = None,
                validate_with: Optional[Callable[[type[BaseStrategy], dict[str, Any]], Any]] = None,
                max_candidates: int = DEFAULT_MAX_CANDIDATES,
                top: int = 10) -> OptimisationResult:
    """Score every valid combination and rank them.

    ``evaluate`` receives the strategy class and one parameter set, and returns
    either a number or a mapping containing ``score``. The mapping form is there
    so a backtest can return its whole result — trade count, drawdown, profit
    factor — and have it kept next to the score rather than thrown away and
    re-derived later from a rerun that may not reproduce.

    An evaluation that raises is recorded as skipped, not scored. A strategy
    that blows up on one parameter set has told you something about that set;
    scoring it zero would rank it above a configuration that merely lost money.
    """
    grid = strategy.optimisation_grid(only)
    notes: list[str] = []
    if not grid:
        return OptimisationResult(strategy=strategy.meta.key,
                                  notes=("no tunable parameters are declared — "
                                         "nothing to optimise",))

    valid, rejected = candidates(strategy, only=only, overrides=overrides)
    proposed = len(valid) + len(rejected)
    if proposed > max_candidates:
        raise OptimisationError(
            f"{strategy.meta.key}: the grid proposes {proposed} combinations, "
            f"above the {max_candidates} limit. Narrow it with `only=`, or raise "
            "`max_candidates` deliberately — a sweep this size is a decision, "
            "not a default.")
    if rejected:
        notes.append(f"{len(rejected)} combination(s) the strategy's own rules "
                     "reject were skipped, not scored")

    scored: list[Candidate] = []
    skipped = [dict(r) for r in rejected]
    for params in valid:
        try:
            outcome = evaluate(strategy, dict(params))
        except Exception as exc:  # noqa: BLE001 — a failure is not a score
            skipped.append({"params": params,
                            "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if isinstance(outcome, Mapping):
            if "score" not in outcome:
                skipped.append({"params": params,
                                "reason": "evaluate() returned a mapping with no "
                                          "'score' key"})
                continue
            score, detail = float(outcome["score"]), dict(outcome)
        else:
            score, detail = float(outcome), {}
        scored.append(Candidate(params=params, score=score, detail=detail))

    scored.sort(key=lambda c: c.score, reverse=True)

    if scored and validate_with is not None:
        # Only the winner is re-scored. Validating every candidate and then
        # picking the best out-of-sample score would use the validation set to
        # choose, which makes it a second training set with a reassuring name.
        best = scored[0]
        try:
            outcome = validate_with(strategy, dict(best.params))
            v = float(outcome["score"] if isinstance(outcome, Mapping) else outcome)
            scored[0] = Candidate(best.params, best.score, best.detail, v)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"out-of-sample validation failed: "
                         f"{type(exc).__name__}: {exc}")
    elif scored:
        notes.append("no out-of-sample validator was supplied — the ranking is "
                     "in-sample only and the winner may be curve-fitted")

    if len(scored) < 2 and scored:
        notes.append("only one candidate scored; a ranking of one is not a "
                     "comparison")

    return OptimisationResult(
        strategy=strategy.meta.key, candidates=tuple(scored[:top]),
        skipped=tuple(skipped), evaluated=len(scored), proposed=proposed,
        notes=tuple(notes))


def split(data: Sequence[Any], fraction: float = 0.7
          ) -> tuple[Sequence[Any], Sequence[Any]]:
    """Chronological train/test split.

    Chronological, never shuffled: shuffling bars lets a strategy be tuned on
    the future and validated on the past, which passes cleanly and means
    nothing. Matches the split the platform's spec optimiser already uses, so
    the two report overfitting on the same basis.
    """
    if not 0 < fraction < 1:
        raise OptimisationError(f"split fraction must be between 0 and 1, got {fraction}")
    cut = int(len(data) * fraction)
    return data[:cut], data[cut:]


__all__ = ["Candidate", "OptimisationResult", "OptimisationError",
           "DEFAULT_MAX_CANDIDATES", "candidates", "grid_search", "split"]
