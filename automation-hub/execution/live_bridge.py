"""Real-order bridge with an execution-safety gate (Priority 3).

Routes the decision engine's order events to a real exchange. The engine (paper
broker) remains the decision + sizing layer; this bridge mirrors each entry to
the live venue via ``ExecutionEngine`` as a bracket order (market + SL/TP).

Every order now passes ``ExecutionSafety`` before it is sent (valid-order,
duplicate, connectivity, data-freshness, slippage), submission is wrapped in a
``RetryPolicy``, and repeated failures trip a ``CircuitBreaker`` that halts
execution. Each attempt records a ``Decision`` (rules passed/failed + verdict +
reason) and, when attached to a bus, publishes a ``decision`` event — so the
bot never behaves like a black box.

The gate is *lenient on unknowns*: if no quote / connectivity / data-age is
supplied, those checks pass, so paper/replay runs behave exactly as before.
Exits are managed exchange-side by the SL/TP bracket; ``trade_closed`` clears
the symbol so the next entry isn't seen as a duplicate.
"""
from __future__ import annotations

from typing import Callable, Optional

from bot.types import Side

from execution.execution_engine import ExecutionEngine
from execution.orders import market_order
from execution.safety import (
    CheckResult, CircuitBreaker, Decision, ExecutionSafety, RetryPolicy, SafetyContext,
)


class RealOrderRouter:
    def __init__(
        self,
        engine: ExecutionEngine,
        safety: ExecutionSafety | None = None,
        retry: RetryPolicy | None = None,
        quote_fn: Optional[Callable[[str], Optional[float]]] = None,
        connected_fn: Optional[Callable[[], Optional[bool]]] = None,
        data_age_fn: Optional[Callable[[], Optional[float]]] = None,
    ):
        self.engine = engine
        self.safety = safety or ExecutionSafety()
        self.retry = retry or RetryPolicy()
        self.circuit = CircuitBreaker(self.safety.config.circuit_threshold)
        self._quote_fn = quote_fn
        self._connected_fn = connected_fn
        self._data_age_fn = data_age_fn
        self._bus = None
        self._last_signal: dict[str, tuple] = {}    # symbol -> (sl, tp, entry)
        self._open_symbols: set[str] = set()        # symbols with a live order/position
        self.submitted: list[dict] = []             # audit trail / for tests
        self.decisions: list[Decision] = []         # every decision recorded

    def attach(self, bus) -> None:
        self._bus = bus
        bus.subscribe(self)

    # ------------------------------------------------------------------ events
    def __call__(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "signal":
            self._last_signal[ev["symbol"]] = (ev.get("sl"), ev.get("tp"), ev.get("entry"))
        elif t == "order":
            self._handle_order(ev)
        elif t == "trade_closed":
            self._open_symbols.discard(ev.get("symbol", ""))

    # ------------------------------------------------------------------ routing
    def _handle_order(self, ev: dict) -> None:
        sym = ev["symbol"]
        side = ev["side"]
        qty = ev["qty"]
        sl, tp, entry = self._last_signal.get(sym, (None, None, None))
        order = market_order(sym, Side(side), qty, stop_loss=sl, take_profit=tp)

        # Circuit breaker — refuse to keep trading through repeated failures.
        if not self.circuit.allow():
            self._record(Decision(
                sym, side, qty, "blocked",
                "Circuit breaker open — execution halted after repeated failures",
                [CheckResult("circuit_breaker", False, "open")],
            ))
            return

        ctx = SafetyContext(
            order=order, expected_price=entry,
            quote_price=self._quote_fn(sym) if self._quote_fn else None,
            connected=self._connected_fn() if self._connected_fn else None,
            data_age_s=self._data_age_fn() if self._data_age_fn else None,
            open_symbols=frozenset(self._open_symbols),
        )
        decision = self.safety.evaluate(ctx)
        if not decision.allowed:
            self._record(decision)
            return

        # Safe to send — submit with retry/backoff.
        try:
            oid = self.retry.run(lambda: self.engine.submit(order))
        except Exception as e:  # noqa: BLE001 - record + trip breaker, never crash
            self.circuit.record_failure()
            self._record(Decision(
                sym, side, qty, "rejected",
                f"Order submission failed after retries: {e}",
                decision.checks + [CheckResult("order_submission", False, str(e))],
            ))
            return

        self.circuit.record_success()
        self._open_symbols.add(sym)
        self.submitted.append({
            "broker_order_id": oid, "symbol": sym, "side": side,
            "qty": qty, "stop_loss": sl, "take_profit": tp,
        })
        self._record(decision)

    def _record(self, decision: Decision) -> None:
        self.decisions.append(decision)
        if self._bus is not None:
            self._bus.publish(decision.to_event())
