"""Real-order bridge.

Routes the decision engine's order events to a real exchange. The engine (paper
broker) remains the decision + sizing layer; this bridge mirrors each entry to
the live venue via ``ExecutionEngine`` as a bracket order (market + SL/TP). It
subscribes to the engine's EventBus, so it layers on without touching the
runner loop. With ``dry_run=True`` (default) it records intent without sending.

Exits are managed exchange-side by the attached SL/TP bracket; the engine's own
paper exits keep the decision-layer accounting in sync.
"""
from __future__ import annotations

from bot.types import Side

from execution.execution_engine import ExecutionEngine
from execution.orders import market_order


class RealOrderRouter:
    def __init__(self, engine: ExecutionEngine):
        self.engine = engine
        self._last_signal: dict[str, tuple] = {}   # symbol -> (sl, tp)
        self.submitted: list[dict] = []            # audit trail / for tests

    def attach(self, bus) -> None:
        bus.subscribe(self)

    def __call__(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "signal":
            self._last_signal[ev["symbol"]] = (ev.get("sl"), ev.get("tp"))
        elif t == "order":
            sym = ev["symbol"]
            sl, tp = self._last_signal.get(sym, (None, None))
            order = market_order(sym, Side(ev["side"]), ev["qty"],
                                 stop_loss=sl, take_profit=tp)
            oid = self.engine.submit(order)
            self.submitted.append({
                "broker_order_id": oid, "symbol": sym, "side": ev["side"],
                "qty": ev["qty"], "stop_loss": sl, "take_profit": tp,
            })
