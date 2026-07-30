"""The execution engine on the live path.

`test_paper_venue.py` proves the port fits a real executor. This proves
production uses it — an engine nothing calls is a very well-tested no-op, which
is exactly what the risk engine was for a whole release.

The safety property is that routing through the engine changed no fill. The
executor underneath is the same object with the same arguments; what the engine
adds is around the fill, not to it.
"""
from __future__ import annotations

import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services import signal_pipeline as sp
from services.controls import TradingControl


def _pipeline():
    led = SqliteLedger(":memory:")
    return sp.SignalPipeline(led, PaperExecutionEngine(led), TradingControl(),
                             equity=10_000)


def _alert(alert_id="e1", **over):
    payload = {"alert_id": alert_id, "symbol": "BTCUSDT", "side": "BUY",
               "entry": 100.0, "stop": 95.0, "confidence": 0.9}
    payload.update(over)
    return payload


def test_the_engine_is_built_and_attached():
    assert _pipeline()._exec_engine is not None


def test_an_accepted_trade_goes_through_the_engine():
    pipe = _pipeline()
    result = pipe.process(_alert())
    assert result.accepted
    assert len(pipe._exec_engine.open_orders()) + len(
        [r for r in pipe._exec_engine._records.values()]) >= 1


def test_the_fill_is_identical_to_the_direct_path():
    """The safety property. The engine is around the fill, not in it — a
    different price or size here would mean the wiring changed trading."""
    through = _pipeline()
    direct = _pipeline()
    direct._exec_engine = None                     # the pre-wiring path

    a = through.process(_alert("same"))
    b = direct.process(_alert("same"))
    assert a.accepted and b.accepted
    assert a.fill["size"] == pytest.approx(b.fill["size"])
    assert a.fill["price"] == pytest.approx(b.fill["price"])
    assert a.fill["action"] == b.fill["action"]


def test_the_engine_records_the_order_and_its_fill():
    pipe = _pipeline()
    pipe.process(_alert())
    record = next(iter(pipe._exec_engine._records.values()))
    assert record.filled_qty > 0
    assert record.average_price == pytest.approx(100.0, rel=0.05)


def test_latency_is_measured_on_the_live_path():
    pipe = _pipeline()
    pipe.process(_alert())
    assert pipe._exec_engine.metrics.percentile("paper.submit", 50) is not None


def test_the_engines_book_reconciles_against_the_executor():
    """If the two disagree here they will disagree against an exchange too."""
    pipe = _pipeline()
    pipe.process(_alert())
    assert pipe._exec_engine.reconcile_venue("paper").clean


def test_a_missing_engine_still_trades():
    """A deployment without tradexa must trade identically rather than not at
    all — the fallback is the exact call the wiring replaced."""
    pipe = _pipeline()
    pipe._exec_engine = None
    assert pipe.process(_alert()).accepted


def test_an_engine_fault_falls_back_rather_than_dropping_the_signal():
    """A fault in the execution layer must not become a dropped trade. The
    executor underneath is the same object either way."""
    class Broken:
        def submit(self, *a, **k):
            raise RuntimeError("engine exploded")

    pipe = _pipeline()
    pipe._exec_engine = Broken()
    result = pipe.process(_alert())
    assert result.accepted, "an engine fault dropped a signal"
    assert len(pipe.paper.positions()) == 1


def test_a_duplicate_intent_is_stopped_at_the_execution_layer():
    """Defence in depth. The dedup gate catches a repeated alert_id first, so
    reaching the engine's guard means a signal arrived by a route that bypassed
    it — and it must still not open a second position."""
    pipe = _pipeline()
    pipe.process(_alert("first"))
    pipe.dedup.is_duplicate = lambda _aid: False    # simulate the bypass
    second = pipe.process(_alert("first"))
    assert not second.accepted
    assert len(pipe.paper.positions()) == 1
