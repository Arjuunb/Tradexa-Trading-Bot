"""The five verdicts a decision rule can return.

Shared vocabulary, so it lives on its own rather than inside whichever module
happened to need it first. The signal pipeline records rule outcomes, the
decision gate grades setup quality, and the decision store persists both — all
three have to agree on what "weak" means or the Decision Archive cannot compare
them.

A boolean cannot carry this. The distinction it loses is not cosmetic:

    PASSED       the rule ran and the trade satisfied it
    WEAK         satisfied, but marginally. Worth surfacing to a human and
                 never a reason to reject on its own.
    FAILED       the rule ran and the trade did not satisfy it
    VETOED       overridden by an authority above this rule — the risk engine
                 — as distinct from failing on the rule's own merits
    UNAVAILABLE  the rule could not be evaluated at all: missing data, an
                 absent module, an unreachable dependency. NOT a pass.

UNAVAILABLE exists because it was already happening and being recorded as a
pass. When ``tradexa.risk`` is not importable the pipeline noted the fact in a
human-readable detail string and set ``passed=True`` — so every machine
consumer showed a green tick for a risk veto that never ran.
"""
from __future__ import annotations


class RuleStatus:
    PASSED = "passed"
    WEAK = "weak"
    FAILED = "failed"
    VETOED = "vetoed"
    UNAVAILABLE = "unavailable"

    ALL = (PASSED, WEAK, FAILED, VETOED, UNAVAILABLE)

    # The two that mean "this rule did not stop the trade". WEAK belongs here:
    # a marginal pass is still a pass, which is exactly why it needs its own
    # name rather than being rounded to either neighbour.
    _AFFIRMATIVE = (PASSED, WEAK)

    @classmethod
    def is_affirmative(cls, status: str) -> bool:
        return status in cls._AFFIRMATIVE
