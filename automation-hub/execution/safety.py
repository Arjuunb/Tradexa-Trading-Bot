"""Execution-safety layer (Priority 3) + decision transparency (Priority 2).

Pure, dependency-free logic that decides whether an order is safe to send and
records WHY. Every order passes a series of pre-trade checks; the result is a
``Decision`` capturing each rule (passed/failed) and the verdict + reason, so
the bot never behaves like a black box.

Checks implemented here:
  - invalid-order validation
  - duplicate-order prevention
  - exchange-connectivity check
  - data-feed freshness (stale-data rejection)
  - slippage protection

Plus the operational guards an execution path needs:
  - ``RetryPolicy``    — exponential backoff for transient failures
  - ``CircuitBreaker`` — halts execution after repeated failures
  - ``reconcile``      — position reconciliation (internal vs broker)

Capital-protection limits (Priority 1) are enforced upstream by
``bot.risk.RiskManager`` / ``risk.guards``; this layer is the last line before
an order reaches a venue.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from bot.types import Order


# --------------------------------------------------------------- data model
@dataclass
class CheckResult:
    rule: str
    passed: bool
    detail: str = ""


@dataclass
class Decision:
    symbol: str
    side: str
    qty: float
    verdict: str                      # "allowed" | "rejected" | "blocked"
    reason: str
    checks: list[CheckResult] = field(default_factory=list)
    time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def allowed(self) -> bool:
        return self.verdict == "allowed"

    def to_event(self) -> dict:
        return {
            "type": "decision",
            "symbol": self.symbol, "side": self.side, "qty": self.qty,
            "verdict": self.verdict, "reason": self.reason,
            "checks": [{"rule": c.rule, "passed": c.passed, "detail": c.detail} for c in self.checks],
            "ts": self.time.isoformat(),
        }


@dataclass
class SafetyConfig:
    max_slippage_bps: float = 8.0       # reject if est. slippage exceeds this
    max_data_age_s: float = 30.0        # reject if latest data older than this
    circuit_threshold: int = 3          # consecutive failures before halting


@dataclass
class SafetyContext:
    order: Order
    expected_price: Optional[float] = None   # signal entry, for slippage est.
    quote_price: Optional[float] = None      # current quote, for slippage est.
    connected: Optional[bool] = None         # exchange reachable? None = unknown
    data_age_s: Optional[float] = None       # age of latest bar/quote (seconds)
    open_symbols: frozenset[str] = frozenset()  # symbols with a live position/order


# --------------------------------------------------------------- the gate
class ExecutionSafety:
    def __init__(self, config: SafetyConfig | None = None):
        self.config = config or SafetyConfig()

    def checks(self, ctx: SafetyContext) -> list[CheckResult]:
        o = ctx.order
        cfg = self.config
        out: list[CheckResult] = []

        # 1. invalid-order validation
        valid = o.qty > 0 and bool(o.symbol) and (o.limit_price is None or o.limit_price > 0)
        out.append(CheckResult("valid_order", valid,
                               "ok" if valid else f"bad qty/price/symbol (qty={o.qty})"))

        # 2. duplicate-order prevention
        dup = o.symbol in ctx.open_symbols
        out.append(CheckResult("no_duplicate_order", not dup,
                               "duplicate position/order open" if dup else "no open duplicate"))

        # 3. exchange connectivity (None = unknown -> pass)
        conn_ok = ctx.connected is not False
        out.append(CheckResult("exchange_connected", conn_ok,
                               "connected" if conn_ok else "exchange unreachable"))

        # 4. data-feed freshness
        fresh = ctx.data_age_s is None or ctx.data_age_s <= cfg.max_data_age_s
        out.append(CheckResult("data_feed_fresh", fresh,
                               "fresh" if fresh else f"stale data ({ctx.data_age_s:.0f}s > {cfg.max_data_age_s:.0f}s)"))

        # 5. slippage protection
        if ctx.expected_price and ctx.quote_price and ctx.expected_price > 0:
            bps = abs(ctx.quote_price - ctx.expected_price) / ctx.expected_price * 1e4
            ok = bps <= cfg.max_slippage_bps
            out.append(CheckResult("slippage_within_limit", ok,
                                   f"{bps:.1f} bps {'<=' if ok else '>'} {cfg.max_slippage_bps:.0f} bps cap"))
        else:
            out.append(CheckResult("slippage_within_limit", True, "no quote — skipped"))
        return out

    def evaluate(self, ctx: SafetyContext) -> Decision:
        checks = self.checks(ctx)
        failed = [c for c in checks if not c.passed]
        if failed:
            return Decision(ctx.order.symbol, ctx.order.side.value, ctx.order.qty,
                            "rejected", failed[0].detail, checks)
        return Decision(ctx.order.symbol, ctx.order.side.value, ctx.order.qty,
                        "allowed", "all execution-safety checks passed", checks)


# --------------------------------------------------------------- retry
@dataclass
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.5
    sleep: Callable[[float], None] = time.sleep

    def run(self, fn: Callable[[], object]) -> object:
        last: Optional[Exception] = None
        for i in range(self.attempts):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001 - retry transient errors
                last = e
                if i < self.attempts - 1:
                    self.sleep(self.base_delay * (2 ** i))
        assert last is not None
        raise last


# --------------------------------------------------------------- circuit breaker
class CircuitBreaker:
    """Trips after ``threshold`` consecutive failures and stays open until reset
    (so a flapping venue can't bleed the account)."""

    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self._fails = 0
        self._tripped = False

    @property
    def tripped(self) -> bool:
        return self._tripped

    def allow(self) -> bool:
        return not self._tripped

    def record_success(self) -> None:
        if not self._tripped:
            self._fails = 0

    def record_failure(self) -> None:
        self._fails += 1
        if self._fails >= self.threshold:
            self._tripped = True

    def reset(self) -> None:
        self._fails = 0
        self._tripped = False


# --------------------------------------------------------------- reconciliation
def reconcile(internal_qty: float, broker_qty: float, tol: float = 1e-9) -> CheckResult:
    """Compare the bot's internal position against the broker's. A mismatch
    means something filled/closed out-of-band — refuse to keep trading."""
    consistent = abs(internal_qty - broker_qty) <= tol
    return CheckResult(
        "position_reconciliation", consistent,
        "in sync" if consistent else f"desync: internal={internal_qty} broker={broker_qty}",
    )
