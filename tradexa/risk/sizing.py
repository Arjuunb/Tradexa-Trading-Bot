"""Position-sizing arithmetic — pure.

Extracted verbatim from ``SignalPipeline._process``. Every multiplication and
every formatting rule is preserved exactly; a differential test compares this
against the original inline expression across a grid of inputs, because "I
copied it carefully" is not evidence when the output decides position size.

The composition being modelled: a base risk-per-trade percentage is scaled by
conviction, then by nine independent modifiers. Each modifier is a subsystem's
opinion about whether now is a good time to be large:

    kelly         the recent win/loss record
    equity_curve  drawdown against the account's own equity curve
    learned       what the learning store knows about this symbol
    allocator     the capital sleeve assigned to this strategy
    event         proximity to a scheduled economic event
    boost         a proven winning pattern, sized UP
    context       funding and sentiment modifiers
    side          long-vs-short performance for this symbol
    streak        consecutive-loss throttling

They multiply rather than average, which is deliberate and worth stating: any
one subsystem can veto size on its own, and two cautious signals compound
instead of cancelling. Averaging would let a confident allocator paper over a
Kelly factor that has collapsed.

``describe_factors`` reproduces the human-readable note shown in the decision
log. It is here rather than at the call site because the note and the number
must never disagree — a log that says "× kelly 0.50" while the size reflects
0.75 is worse than no note at all.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Conviction floor. Confidence 1.0 gives full risk, 0.5 gives 75%, and 0.0
#: still gives 50% rather than zero — a low-confidence signal that passed every
#: gate is a trade, just a smaller one. Sizing it to nothing would silently
#: convert a "yes" into a "no" after the decision was already made.
CONFIDENCE_FLOOR = 0.5

#: Context modifiers are clamped to this band. Below it, an upstream sentiment
#: feed could size a trade to near-zero; above it, one could size UP, and only
#: the proven-edge boost is permitted to do that.
CONTEXT_MIN = 0.5
CONTEXT_MAX = 1.0


@dataclass(frozen=True)
class RiskFactors:
    """The nine modifiers plus conviction, as one value.

    Frozen and named so a caller cannot silently pass them positionally in the
    wrong order — ten bare floats in a row is exactly the signature where
    ``kelly`` and ``streak`` get swapped and nobody notices, because the result
    is still a plausible number.
    """

    confidence: float = 1.0
    kelly: float = 1.0
    equity_curve: float = 1.0
    learned: float = 1.0
    allocator: float = 1.0
    event: float = 1.0
    boost: float = 1.0
    context: float = 1.0
    side: float = 1.0
    streak: float = 1.0

    @property
    def conviction(self) -> float:
        """Confidence mapped onto [CONFIDENCE_FLOOR, 1.0]."""
        return CONFIDENCE_FLOOR + CONFIDENCE_FLOOR * self.confidence

    @property
    def throttling(self) -> float:
        """The most pessimistic of the defensive factors.

        Used to decide whether the edge boost is permitted: defense outranks
        offense, so a proven pattern is not sized up while anything else is
        sizing down.
        """
        return min(self.kelly, self.equity_curve, self.learned, self.event)


def clamp_context(value: float) -> float:
    """Bound a context modifier. Mirrors the pipeline's inline clamp, including
    its tolerance of ``None`` and unparseable input — an upstream feed returning
    junk must not size a trade, and must not raise inside the trading loop."""
    try:
        raw = float(value if value is not None else 1.0)
    except (TypeError, ValueError):
        return CONTEXT_MAX
    return max(CONTEXT_MIN, min(CONTEXT_MAX, raw))


def effective_risk(base_pct: float, factors: RiskFactors) -> float:
    """The risk fraction to size with.

    Order of operations matches the original exactly. Floating-point
    multiplication is not associative, so regrouping these terms — even into a
    tidier ``math.prod`` — can move the last bits of the result and therefore
    the position size. It is written as one left-to-right chain for that
    reason, not for style.
    """
    risk = base_pct * factors.conviction
    risk *= (factors.kelly * factors.equity_curve * factors.learned
             * factors.allocator * factors.event * factors.boost
             * factors.context * factors.side * factors.streak)
    return risk


#: (attribute, label, predicate) — a factor appears in the note only when its
#: predicate holds. The asymmetry is intentional and preserved from the
#: original: throttles are reported when they bite (< 1.0), the boost when it
#: lifts (> 1.0), and the allocator whenever it is not neutral, because a
#: sleeve of 1.5x is as material to explaining a size as a sleeve of 0.5x.
_NOTE_RULES = (
    ("kelly", "kelly", lambda v: v < 1.0),
    ("equity_curve", "curve", lambda v: v < 1.0),
    ("learned", "learned", lambda v: v < 1.0),
    ("allocator", "alloc", lambda v: v != 1.0),
    ("event", "event", lambda v: v < 1.0),
    ("boost", "edge", lambda v: v > 1.0),
    ("context", "context", lambda v: v < 1.0),
    ("side", "side", lambda v: v < 1.0),
    ("streak", "streak", lambda v: v < 1.0),
)


def describe_factors(factors: RiskFactors) -> str:
    """The decision-log note, e.g. ``conf 0.80 × kelly 0.50 × streak 0.75``.

    Only factors that actually moved the number appear. Listing all nine every
    time would bury the one that mattered — the note exists to answer "why was
    this trade small?", and an answer containing nine ``× 1.00`` terms does not.
    """
    parts = [f"conf {factors.confidence:.2f}"]
    for attr, label, applies in _NOTE_RULES:
        value = getattr(factors, attr)
        if applies(value):
            parts.append(f"× {label} {value:.2f}")
    return " ".join(parts)


__all__ = ["RiskFactors", "effective_risk", "describe_factors", "clamp_context",
           "CONFIDENCE_FLOOR", "CONTEXT_MIN", "CONTEXT_MAX"]
