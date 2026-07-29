"""The Risk Engine.

Standalone and strategy-independent. It imports no strategy, no exchange, no
database and no web framework — only its own rules and the domain models. A
test enforces that, because "independent" claimed in a docstring is a
convention, and a convention is what gets broken by the first deadline.

The contract:

    decision = engine.evaluate(context)

    decision.approved      may this trade happen
    decision.quantity      how large, if so
    decision.rule          which rule refused it, if not
    decision.reason        why, in words an operator can act on
    decision.violations    EVERY failing rule, not just the first
    decision.checks        every rule's verdict, pass or fail
    decision.limits        the limits in force when the decision was made

Two properties are worth stating because they are unusual and deliberate.

**A rejection reports every reason, not the first.** Being refused, fixing one
thing, and being refused again for a second is worse than being told both at
once. The blocking rules are independent, so all of them are evaluated.

**An approval carries its size.** Approval and sizing are one decision.
Returning a bare "yes" is what forces size to be recomputed somewhere else and
drift from the rule that authorised it.

The engine never mutates anything. It reads a context and returns a verdict.
Whether that verdict is honoured is the executor's business — but the executor
is given no way to obtain a size without one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from tradexa.risk.context import RiskContext
from tradexa.risk.limits import RiskLimits
from tradexa.risk.rules import (
    BLOCKING_RULES, QUANTITY_RULES, RuleResult, volatility_adjustment,
)
from tradexa.risk.sizing import RiskFactors, effective_risk


@dataclass(frozen=True)
class RiskDecision:
    """The verdict, with the whole trail behind it."""

    approved: bool
    quantity: float = 0.0
    risk_amount: float = 0.0
    risk_pct: float = 0.0
    rule: Optional[str] = None
    reason: str = ""
    checks: tuple[RuleResult, ...] = ()
    limits_name: str = ""
    evaluated_ms: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def violations(self) -> tuple[RuleResult, ...]:
        """Every rule that refused. A single-reason rejection is a guess about
        which one the operator cares about."""
        return tuple(c for c in self.checks if c.failed)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Passing rules whose detail is worth surfacing — a rule that passed
        while noting something (unstopped positions, an unevaluated cluster)
        is the early warning a limit is about to bite."""
        return tuple(c.detail for c in self.checks
                     if c.passed and c.context.get("evaluated") is False)

    @property
    def notional(self) -> float:
        return self.quantity * float(self.context.get("entry", 0.0))

    def explain(self) -> str:
        """One line an operator can read. Names every failing rule, because
        a rejection that says only 'blocked by risk' sends someone hunting."""
        if self.approved:
            return (f"APPROVED {self.quantity:.6f} units "
                    f"(risk {self.risk_amount:.2f}, {self.risk_pct*100:.2f}% of equity)")
        return "REJECTED — " + "; ".join(f"{v.rule}: {v.detail}" for v in self.violations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "quantity": self.quantity,
            "risk_amount": self.risk_amount,
            "risk_pct": self.risk_pct,
            "rule": self.rule,
            "reason": self.reason,
            "violations": [{"rule": v.rule, "detail": v.detail} for v in self.violations],
            "checks": [{"rule": c.rule, "passed": c.passed, "detail": c.detail}
                       for c in self.checks],
            "limits": self.limits_name,
            "evaluated_ms": round(self.evaluated_ms, 3),
        }


class RiskEngine:
    """Evaluates a proposed trade against a set of limits.

    Holds no mutable trading state. Two calls with the same context return the
    same decision, which is what makes a rejection reproducible — an engine
    that remembers things between calls cannot be asked "why did it say no?"
    after the fact.
    """

    def __init__(self, limits: Optional[RiskLimits] = None, *,
                 blocking_rules: Sequence[Any] = BLOCKING_RULES,
                 quantity_rules: Sequence[Any] = QUANTITY_RULES,
                 logger: Any = None) -> None:
        self.limits = limits or RiskLimits()
        self._blocking = tuple(blocking_rules)
        self._quantity = tuple(quantity_rules)
        self._log = logger

    # ---------------------------------------------------------------- public
    def evaluate(self, ctx: RiskContext) -> RiskDecision:
        """The only way to obtain an approved size."""
        started = time.perf_counter()
        checks: list[RuleResult] = []

        # 1. Kill switch, alone and first. Nothing may argue past a halt, and
        #    nothing after it is worth computing.
        halt = self._blocking[0](ctx, self.limits)
        checks.append(halt)
        if halt.failed:
            return self._reject(ctx, checks, started)

        # 2. Every other blocking rule. ALL of them run — a trade refused for
        #    three reasons should say three, not make the operator discover
        #    them one deploy at a time.
        for rule in self._blocking[1:]:
            checks.append(self._safe(rule, ctx))
        if any(c.failed for c in checks):
            return self._reject(ctx, checks, started)

        # 3. Size it. Only now: sizing a trade about to be refused is wasted
        #    work, and it puts a quantity in the log for a trade that never was.
        vol = self._safe(volatility_adjustment, ctx)
        checks.append(vol)
        qty, risk_amount, risk_pct = self._size(ctx, vol.scale)

        if qty <= 0:
            checks.append(RuleResult("sizing", False,
                                     "Computed position size is zero"))
            return self._reject(ctx, checks, started)

        # 4. Quantity-dependent caps, each scaling what the last produced, so
        #    the tightest constraint wins without any rule knowing the others.
        for rule in self._quantity:
            result = self._safe_qty(rule, ctx, qty)
            checks.append(result)
            if result.failed:
                return self._reject(ctx, checks, started)
            qty *= result.scale

        if qty <= 0:
            checks.append(RuleResult("sizing", False,
                                     "Exposure and margin limits leave zero size"))
            return self._reject(ctx, checks, started)

        # Risk is recomputed from the FINAL quantity. Reporting the pre-cap
        # figure would overstate what is actually at stake on a capped trade.
        final_risk = qty * ctx.proposal.stop_distance
        return RiskDecision(
            approved=True, quantity=qty, risk_amount=final_risk,
            risk_pct=final_risk / ctx.account.equity if ctx.account.equity else 0.0,
            reason="approved", checks=tuple(checks),
            limits_name=self.limits.name,
            evaluated_ms=(time.perf_counter() - started) * 1000,
            context={"entry": ctx.proposal.entry, "symbol": ctx.proposal.symbol},
        )

    def is_halted(self, ctx: RiskContext) -> bool:
        """Satisfies the ``RiskManager`` port's halt check."""
        return bool(ctx.kill_switch_engaged)

    # --------------------------------------------------------------- private
    def _size(self, ctx: RiskContext, vol_scale: float) -> tuple[float, float, float]:
        """Risk-based position size, using the shared sizing arithmetic.

        Reuses ``tradexa.risk.sizing`` rather than restating the formula — the
        live pipeline composes its factors through the same function, so the
        standalone engine and production cannot compute different sizes from
        the same inputs.
        """
        base = min(self.limits.risk_per_trade_pct, self.limits.max_risk_per_trade_pct)
        factors = RiskFactors(confidence=ctx.proposal.confidence, context=vol_scale)
        risk_pct = min(effective_risk(base, factors), self.limits.max_risk_per_trade_pct)
        risk_amount = risk_pct * ctx.account.equity
        distance = ctx.proposal.stop_distance
        qty = risk_amount / distance if distance > 0 else 0.0
        return qty, risk_amount, risk_pct

    def _safe(self, rule: Any, ctx: RiskContext) -> RuleResult:
        """Run a rule; a rule that raises FAILS CLOSED.

        A risk check that errors has not approved anything. Treating an
        exception as a pass is how a broken volatility feed silently disables
        the guard that depends on it.
        """
        try:
            return rule(ctx, self.limits)
        except Exception as exc:  # noqa: BLE001 — fail closed, never open
            name = getattr(rule, "__name__", "rule")
            if self._log is not None:
                try:
                    self._log.error("risk.rule_failed", rule=name,
                                    error=type(exc).__name__, message=str(exc))
                except Exception:  # noqa: BLE001
                    pass
            return RuleResult(name, False,
                              f"Rule raised {type(exc).__name__}: {exc} — "
                              "refusing the trade rather than assuming it is safe")

    def _safe_qty(self, rule: Any, ctx: RiskContext, qty: float) -> RuleResult:
        try:
            return rule(ctx, self.limits, qty)
        except Exception as exc:  # noqa: BLE001 — fail closed
            name = getattr(rule, "__name__", "rule")
            return RuleResult(name, False,
                              f"Rule raised {type(exc).__name__}: {exc} — "
                              "refusing the trade rather than assuming it is safe")

    def _reject(self, ctx: RiskContext, checks: list[RuleResult],
                started: float) -> RiskDecision:
        failed = [c for c in checks if c.failed]
        first = failed[0] if failed else None
        return RiskDecision(
            approved=False, quantity=0.0,
            rule=first.rule if first else None,
            reason="; ".join(f.detail for f in failed) or "rejected",
            checks=tuple(checks), limits_name=self.limits.name,
            evaluated_ms=(time.perf_counter() - started) * 1000,
            context={"entry": ctx.proposal.entry, "symbol": ctx.proposal.symbol},
        )


__all__ = ["RiskEngine", "RiskDecision"]
