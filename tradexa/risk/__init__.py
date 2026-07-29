"""Risk — the standalone Risk Engine.

Completely independent of strategies. It imports no strategy, no exchange, no
database and no web framework; everything it needs arrives in a ``RiskContext``
the caller assembles. ``tests/test_risk_engine_standalone.py`` enforces that by
walking the package's imports, because independence claimed in a docstring is a
convention and conventions break at the first deadline.

    from tradexa.risk import RiskEngine, RiskContext, TradeProposal, RiskLimits

    engine = RiskEngine(RiskLimits(max_daily_loss_pct=0.03))
    decision = engine.evaluate(context)
    if decision.approved:
        execute(decision.quantity)
    else:
        log(decision.explain())        # names EVERY failing rule

``evaluate`` is the only way to obtain an approved size, which is what makes
"no strategy may bypass risk" structural rather than a rule someone has to
remember.
"""
from tradexa.risk.context import (
    AccountState, Direction, MarketConditions, OpenPosition, RiskContext,
    TradeProposal,
)
from tradexa.risk.engine import RiskDecision, RiskEngine
from tradexa.risk.limits import CONSERVATIVE, PIPELINE_PARITY, STRICT, RiskLimits
from tradexa.risk.rules import BLOCKING_RULES, QUANTITY_RULES, RuleResult
from tradexa.risk.sizing import RiskFactors, describe_factors, effective_risk

__all__ = [
    "RiskEngine", "RiskDecision",
    "RiskContext", "TradeProposal", "AccountState", "OpenPosition",
    "MarketConditions", "Direction",
    "RiskLimits", "CONSERVATIVE", "PIPELINE_PARITY", "STRICT",
    "RuleResult", "BLOCKING_RULES", "QUANTITY_RULES",
    "RiskFactors", "effective_risk", "describe_factors",
]
