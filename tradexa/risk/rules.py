"""The rules. Each one is pure, named, and independently testable.

A rule takes a ``RiskContext`` and ``RiskLimits`` and returns a ``RuleResult``.
It never reads a clock, a database or a feed — everything it needs is in the
context — so every edge case is a two-line test rather than a fixture that has
to manufacture an account into a database first.

Rules come in two kinds, and the distinction is what lets the engine give a
COMPLETE answer rather than only the first objection:

*Blocking rules* answer "may this trade happen at all?". They are independent
of each other, so the engine evaluates all of them and reports every failure.
Being told a trade was refused for one reason, fixing it, and being refused
again for a second is a worse experience than being told both at once.

*Sizing rules* answer "how large?". They form a chain — each scales the size
the previous produced — so they run in order and only after the blocking rules
have passed. Sizing a trade that is about to be refused is wasted work, and
worse, it puts a size in the decision log for a trade that never existed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from tradexa.risk.context import Direction, RiskContext
from tradexa.risk.limits import RiskLimits


@dataclass(frozen=True)
class RuleResult:
    """One rule's verdict.

    ``passed`` and ``detail`` are both always populated — a rule that passes
    still explains what it measured, because "daily loss -1.2% of -3.0%" is the
    line that tells an operator how close they are, and a decision log
    containing only failures cannot answer that.
    """

    rule: str
    passed: bool
    detail: str = ""
    #: Multiplier a sizing rule applies. 1.0 for blocking rules.
    scale: float = 1.0
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.passed


def _ok(rule: str, detail: str = "", **ctx: Any) -> RuleResult:
    return RuleResult(rule=rule, passed=True, detail=detail, context=ctx)


def _fail(rule: str, detail: str, **ctx: Any) -> RuleResult:
    return RuleResult(rule=rule, passed=False, detail=detail, context=ctx)


# ═══════════════════════════════════════════════════ blocking rules

def kill_switch(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """The operator's stop, and every circuit breaker's landing point.

    Evaluated before anything else and never overridable. A halt that a
    well-sized trade could argue past is not a halt.
    """
    if ctx.kill_switch_engaged:
        return _fail("kill_switch",
                     ctx.kill_switch_reason or "Kill switch engaged — entries blocked",
                     reason=ctx.kill_switch_reason)
    return _ok("kill_switch", "armed, not tripped")


def trade_validation(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """Is this a coherent trade at all?

    Runs early because everything downstream divides by the stop distance. A
    missing stop is not a small position — it is a division by zero or an
    infinite one, depending on which way the arithmetic falls.
    """
    p = ctx.proposal
    if p.entry <= 0:
        return _fail("trade_validation", f"Entry price must be positive (got {p.entry})",
                     entry=p.entry)
    if p.stop <= 0:
        return _fail("trade_validation", "Stop loss is missing or not positive",
                     stop=p.stop)
    if not p.stop_distance:
        return _fail("trade_validation", "Stop equals entry — the position would be unsizeable",
                     entry=p.entry, stop=p.stop)
    if not p.stop_is_valid:
        side = "below" if p.direction is Direction.LONG else "above"
        return _fail("trade_validation",
                     f"Stop {p.stop} is on the wrong side of entry {p.entry} — "
                     f"a {p.direction.value} stop must be {side} entry",
                     entry=p.entry, stop=p.stop, direction=p.direction.value)
    if ctx.account.equity <= 0:
        return _fail("trade_validation", "Account equity is zero or negative",
                     equity=ctx.account.equity)
    return _ok("trade_validation",
               f"{p.direction.value} {p.symbol} @ {p.entry}, stop {p.stop} "
               f"({p.stop_distance:.4f} away)")


def max_drawdown(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """Peak-to-trough equity protection.

    Blocks NEW entries only. It must never close existing positions: forcing
    exits at the worst moment is how a drawdown guard turns a bad week into a
    realised loss.
    """
    if limits.max_drawdown_pct <= 0:
        return _ok("max_drawdown", "disabled")
    dd = ctx.account.drawdown_pct
    if dd >= limits.max_drawdown_pct:
        return _fail("max_drawdown",
                     f"Drawdown {dd*100:.1f}% has reached the "
                     f"{limits.max_drawdown_pct*100:.1f}% limit — new entries blocked",
                     drawdown_pct=dd, limit=limits.max_drawdown_pct)
    return _ok("max_drawdown", f"{dd*100:.1f}% of {limits.max_drawdown_pct*100:.1f}%",
               drawdown_pct=dd)


def daily_drawdown(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """The daily loss limit, measured against equity at the start of the day."""
    if limits.max_daily_loss_pct <= 0:
        return _ok("daily_drawdown", "disabled")
    base = ctx.account.starting_equity or ctx.account.equity
    allowed = limits.max_daily_loss_pct * base
    lost = -ctx.account.realized_pnl_today
    if lost >= allowed:
        return _fail("daily_drawdown",
                     f"Daily loss {lost:.2f} has reached the {allowed:.2f} limit "
                     f"({limits.max_daily_loss_pct*100:.1f}% of {base:.2f})",
                     lost=lost, allowed=allowed)
    return _ok("daily_drawdown", f"{lost:.2f} of {allowed:.2f} used",
               lost=lost, allowed=allowed)


def weekly_drawdown(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """The weekly loss limit. Separate from daily because a run of small daily
    losses can stay under the daily cap every day and still empty an account
    inside a week."""
    if limits.max_weekly_loss_pct <= 0:
        return _ok("weekly_drawdown", "disabled")
    base = ctx.account.starting_equity or ctx.account.equity
    allowed = limits.max_weekly_loss_pct * base
    lost = -ctx.account.realized_pnl_week
    if lost >= allowed:
        return _fail("weekly_drawdown",
                     f"Weekly loss {lost:.2f} has reached the {allowed:.2f} limit "
                     f"({limits.max_weekly_loss_pct*100:.1f}% of {base:.2f})",
                     lost=lost, allowed=allowed)
    return _ok("weekly_drawdown", f"{lost:.2f} of {allowed:.2f} used",
               lost=lost, allowed=allowed)


def max_account_risk(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """Total risk at stake across every open position.

    Per-trade limits alone let a book stack up: six trades at 1% each is 6% on
    one adverse move, and no individual trade broke a rule.
    """
    if limits.max_account_risk_pct <= 0:
        return _ok("max_account_risk", "disabled")
    allowed = limits.max_account_risk_pct * ctx.account.equity
    at_risk = ctx.open_risk
    unstopped = [p.symbol for p in ctx.positions if p.stop is None]
    if at_risk >= allowed:
        return _fail("max_account_risk",
                     f"Open risk {at_risk:.2f} has reached the {allowed:.2f} ceiling",
                     at_risk=at_risk, allowed=allowed)
    detail = f"{at_risk:.2f} of {allowed:.2f} at risk"
    if unstopped:
        # Reported, never treated as zero risk — an unstopped position has
        # unbounded downside, and counting it as 0 is how a book looks safe
        # while carrying the most dangerous thing in it.
        detail += f" ({len(unstopped)} unstopped position(s) not counted: {', '.join(unstopped)})"
    return _ok("max_account_risk", detail, at_risk=at_risk, allowed=allowed,
               unstopped=unstopped)


def max_open_positions(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    if limits.max_open_positions <= 0:
        return _ok("max_open_positions", "disabled")
    count = len(ctx.positions)
    if count >= limits.max_open_positions:
        return _fail("max_open_positions",
                     f"{count} positions open, limit is {limits.max_open_positions}",
                     open=count, limit=limits.max_open_positions)
    return _ok("max_open_positions", f"{count} of {limits.max_open_positions} used",
               open=count)


def correlation_limit(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """Same-direction positions within one correlation cluster.

    Three simultaneous crypto longs are not diversification — they are one
    3x-sized bet on the same market, and they lose together.
    """
    if limits.max_correlated_positions <= 0:
        return _ok("correlation_limit", "disabled")
    cluster = ctx.market.cluster
    if not cluster:
        # No cluster known means the rule cannot judge. Passing WITH that stated
        # is honest; silently passing would let an unclassified symbol dodge the
        # limit and look like it was checked.
        return _ok("correlation_limit", "no cluster assigned — not evaluated",
                   evaluated=False)
    same = ctx.positions_in_cluster(cluster, ctx.proposal.direction)
    if len(same) >= limits.max_correlated_positions:
        return _fail("correlation_limit",
                     f"{len(same)} {ctx.proposal.direction.value} positions already open in "
                     f"cluster '{cluster}', limit is {limits.max_correlated_positions}",
                     cluster=cluster, count=len(same),
                     symbols=[p.symbol for p in same])
    return _ok("correlation_limit",
               f"{len(same)} of {limits.max_correlated_positions} in '{cluster}'",
               cluster=cluster, count=len(same))


def session_filter(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """Trading hours and days, in UTC.

    Both are checked here because they answer one question — "is the desk open
    right now?" — and splitting them would make a weekend rejection and a
    3am rejection arrive from different rules for the same reason.
    """
    hour, weekday = ctx.now.hour, ctx.now.weekday()

    if limits.trading_days_mask != 127:
        if not (limits.trading_days_mask >> weekday) & 1:
            day = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[weekday]
            return _fail("session_filter", f"{day} is not an allowed trading day",
                         weekday=weekday)

    start, end = limits.session_start_hour, limits.session_end_hour
    if (start, end) != (0, 24):
        # A window that wraps midnight (21:00–06:00) is expressed start > end.
        inside = (start <= hour < end) if start <= end else (hour >= start or hour < end)
        if not inside:
            return _fail("session_filter",
                         f"{hour:02d}:00 UTC is outside the "
                         f"{start:02d}:00–{end:02d}:00 session",
                         hour=hour, start=start, end=end)
    return _ok("session_filter", f"{hour:02d}:00 UTC, within session", hour=hour)


def news_blackout(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """Refuse entries around scheduled high-impact events.

    Spreads widen and stops slip through; an edge measured on normal conditions
    does not survive them. ``None`` means no event is known, which is different
    from an event zero minutes away — conflating them would either blackout
    permanently or never.
    """
    if limits.news_blackout_minutes <= 0:
        return _ok("news_blackout", "disabled")
    mins = ctx.market.minutes_to_news
    if mins is None:
        return _ok("news_blackout", "no scheduled event known", evaluated=False)
    if abs(mins) <= limits.news_blackout_minutes:
        when = "in" if mins >= 0 else "since"
        return _fail("news_blackout",
                     f"High-impact event {when} {abs(mins):.0f} minutes — inside the "
                     f"{limits.news_blackout_minutes}-minute blackout",
                     minutes_to_news=mins, window=limits.news_blackout_minutes)
    return _ok("news_blackout", f"nearest event {abs(mins):.0f} minutes away",
               minutes_to_news=mins)


def volatility_ceiling(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """Refuse a market that is too disorderly to trade at all.

    Separate from the volatility SIZING rule: this is a hard "not here",
    that one is "smaller here". A single rule doing both would have to choose,
    and reducing size in a market where the stop is meaningless is the wrong
    choice.
    """
    if limits.max_volatility_pct <= 0:
        return _ok("volatility_ceiling", "disabled")
    atr = ctx.market.atr_pct
    if atr >= limits.max_volatility_pct:
        return _fail("volatility_ceiling",
                     f"Volatility {atr*100:.2f}% is at or above the "
                     f"{limits.max_volatility_pct*100:.2f}% ceiling",
                     atr_pct=atr, limit=limits.max_volatility_pct)
    return _ok("volatility_ceiling", f"{atr*100:.2f}% of {limits.max_volatility_pct*100:.2f}%",
               atr_pct=atr)


#: Order matters only for readability — these are independent and the engine
#: evaluates all of them. Kill switch is listed first because it is the one a
#: reader should see first, and the engine short-circuits on it regardless.
BLOCKING_RULES = (
    kill_switch,
    trade_validation,
    max_drawdown,
    daily_drawdown,
    weekly_drawdown,
    max_account_risk,
    max_open_positions,
    correlation_limit,
    session_filter,
    news_blackout,
    volatility_ceiling,
)


# ═══════════════════════════════════════════════════ sizing rules

def volatility_adjustment(ctx: RiskContext, limits: RiskLimits) -> RuleResult:
    """Scale size down when the market is more volatile than the reference.

    Fixed-fraction sizing already adapts through the stop distance — a wider
    stop buys fewer units. This is the second-order adjustment for a regime
    where the whole market is unstable, not just this setup.

    Floored rather than allowed to reach zero: sizing a signal that cleared
    every gate down to nothing converts a "yes" into a "no" after the decision
    was made, silently.
    """
    if limits.volatility_reference_pct <= 0 or ctx.market.atr_pct <= 0:
        return RuleResult("volatility_adjustment", True, "no volatility reading", scale=1.0)
    ratio = limits.volatility_reference_pct / ctx.market.atr_pct
    scale = max(limits.min_volatility_scale, min(1.0, ratio))
    if scale >= 1.0:
        return RuleResult("volatility_adjustment", True,
                          f"vol {ctx.market.atr_pct*100:.2f}% at or below reference",
                          scale=1.0, context={"atr_pct": ctx.market.atr_pct})
    return RuleResult("volatility_adjustment", True,
                      f"vol {ctx.market.atr_pct*100:.2f}% vs reference "
                      f"{limits.volatility_reference_pct*100:.2f}% → size × {scale:.2f}",
                      scale=scale,
                      context={"atr_pct": ctx.market.atr_pct, "scale": scale})


def position_exposure_cap(ctx: RiskContext, limits: RiskLimits,
                          qty: float) -> RuleResult:
    """Cap ONE position's notional as a fraction of equity.

    Independent of the risk-based size: a tight stop can justify a large
    position on risk grounds and still put an unacceptable share of the account
    into one instrument.
    """
    if limits.max_position_exposure_pct <= 0:
        return RuleResult("position_exposure", True, "disabled", scale=1.0)
    entry = ctx.proposal.entry
    max_notional = limits.max_position_exposure_pct * ctx.account.equity
    notional = qty * entry
    if notional <= max_notional:
        return RuleResult("position_exposure", True,
                          f"{notional:.2f} within {max_notional:.2f}", scale=1.0,
                          context={"notional": notional, "cap": max_notional})
    scale = max_notional / notional if notional else 0.0
    return RuleResult("position_exposure", True,
                      f"capped from {notional:.2f} to {max_notional:.2f} "
                      f"({limits.max_position_exposure_pct*100:.0f}% of equity)",
                      scale=scale,
                      context={"notional": notional, "cap": max_notional, "scale": scale})


def portfolio_exposure_cap(ctx: RiskContext, limits: RiskLimits,
                           qty: float) -> RuleResult:
    """Cap TOTAL open notional across the book.

    Fails rather than scales when there is no budget left: a zero-size trade is
    not a smaller trade, it is a refusal, and reporting it as an approval of
    size 0 would put a phantom trade in the log.
    """
    if limits.max_total_exposure_pct <= 0:
        return RuleResult("portfolio_exposure", True, "disabled", scale=1.0)
    budget = limits.max_total_exposure_pct * ctx.account.equity - ctx.gross_exposure
    if budget <= 0:
        return _fail("portfolio_exposure",
                     f"Portfolio exposure {ctx.gross_exposure:.2f} is already at the "
                     f"{limits.max_total_exposure_pct*100:.0f}% cap",
                     exposure=ctx.gross_exposure, budget=budget)
    notional = qty * ctx.proposal.entry
    if notional <= budget:
        return RuleResult("portfolio_exposure", True,
                          f"{notional:.2f} within remaining budget {budget:.2f}",
                          scale=1.0, context={"budget": budget})
    scale = budget / notional if notional else 0.0
    return RuleResult("portfolio_exposure", True,
                      f"capped to the remaining {budget:.2f} notional budget",
                      scale=scale, context={"budget": budget, "scale": scale})


def leverage_validation(ctx: RiskContext, limits: RiskLimits,
                        qty: float) -> RuleResult:
    """Gross notional over equity, after this trade, against the leverage cap."""
    if limits.max_leverage <= 0:
        return RuleResult("leverage", True, "disabled", scale=1.0)
    equity = ctx.account.equity
    if equity <= 0:
        return _fail("leverage", "No equity to lever", equity=equity)
    projected = ctx.gross_exposure + qty * ctx.proposal.entry
    lev = projected / equity
    if lev <= limits.max_leverage:
        return RuleResult("leverage", True,
                          f"{lev:.2f}x of {limits.max_leverage:.2f}x", scale=1.0,
                          context={"leverage": lev})
    allowed_notional = limits.max_leverage * equity - ctx.gross_exposure
    if allowed_notional <= 0:
        return _fail("leverage",
                     f"Already at {ctx.gross_exposure/equity:.2f}x, limit is "
                     f"{limits.max_leverage:.2f}x",
                     leverage=ctx.gross_exposure / equity, limit=limits.max_leverage)
    scale = allowed_notional / (qty * ctx.proposal.entry)
    return RuleResult("leverage", True,
                      f"capped to stay within {limits.max_leverage:.2f}x leverage",
                      scale=scale, context={"leverage": lev, "scale": scale})


def margin_validation(ctx: RiskContext, limits: RiskLimits,
                      qty: float) -> RuleResult:
    """Free margin remaining AFTER the trade.

    Checked on what is left rather than what is used: a trade that fits exactly
    is one adverse tick from a margin call, and the buffer is the whole point.
    """
    if limits.min_free_margin_pct <= 0:
        return RuleResult("margin", True, "disabled", scale=1.0)
    equity = ctx.account.equity
    required = max(0.0, limits.min_free_margin_pct * equity)
    #: On a cash account (max_leverage <= 1) the notional IS the margin.
    cost = qty * ctx.proposal.entry / max(1.0, limits.max_leverage)
    remaining = ctx.account.free_margin - cost
    if remaining >= required:
        return RuleResult("margin", True,
                          f"{remaining:.2f} free after the trade, {required:.2f} required",
                          scale=1.0, context={"remaining": remaining, "required": required})
    affordable = ctx.account.free_margin - required
    if affordable <= 0:
        return _fail("margin",
                     f"Free margin {ctx.account.free_margin:.2f} is already at or below "
                     f"the {required:.2f} buffer",
                     free_margin=ctx.account.free_margin, required=required)
    scale = affordable / cost if cost else 0.0
    return RuleResult("margin", True,
                      f"capped to preserve the {required:.2f} free-margin buffer",
                      scale=min(1.0, scale),
                      context={"required": required, "scale": scale})


#: Sizing rules that need a quantity, applied in order. Each scales what the
#: previous produced, so the tightest constraint wins without any of them
#: needing to know about the others.
QUANTITY_RULES = (
    position_exposure_cap,
    portfolio_exposure_cap,
    leverage_validation,
    margin_validation,
)

__all__ = [
    "RuleResult", "BLOCKING_RULES", "QUANTITY_RULES",
    "kill_switch", "trade_validation", "max_drawdown", "daily_drawdown",
    "weekly_drawdown", "max_account_risk", "max_open_positions",
    "correlation_limit", "session_filter", "news_blackout",
    "volatility_ceiling", "volatility_adjustment", "position_exposure_cap",
    "portfolio_exposure_cap", "leverage_validation", "margin_validation",
]
