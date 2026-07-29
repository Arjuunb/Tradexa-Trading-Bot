"""Risk — position sizing and trade validation.

Phase 3 of the architecture consolidation. The extraction is deliberately
incremental: `automation-hub/services/signal_pipeline.py` runs twenty-two
ordered gates against ten stateful collaborators (Kelly state, the learning
store, the allocator, the paper book, the equity curve), and moving all of it
at once would be a large change to the code that decides position size on a
live account.

So the PURE part comes out first — the arithmetic that turns a set of factors
into an effective risk percentage, and the sentence that explains it. That is
the heart of sizing, it has no dependencies, and until now it could not be
tested without constructing the whole pipeline.

The stateful collaborators stay where they are for now. What changes is that
the calculation they feed is a function with a name, a signature and its own
tests, rather than twenty lines in the middle of a 300-line method.
"""
from tradexa.risk.sizing import RiskFactors, describe_factors, effective_risk

__all__ = ["RiskFactors", "effective_risk", "describe_factors"]
