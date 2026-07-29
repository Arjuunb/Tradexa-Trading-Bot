"""Characterization: the order risk gates fire in.

Phase 3 of the architecture consolidation moves risk logic behind a
``RiskManager`` port. Before anything moves, the CURRENT behaviour has to be
pinned — otherwise a drift is discovered in a live account rather than by a
test written against the old code.

48 tests across seven files already cover the individual rules (position caps,
daily loss, cooldown, exposure). This file covers the one thing none of them
do: **the sequence**.

Order is behaviour, not an implementation detail. When a signal would trip two
gates, the first one reached decides the reason the user sees, what the
decision log records, and what the counterfactual tracker grades. An extraction
that preserves every rule but reorders them changes all three while every
existing test still passes — which is exactly the kind of regression a
characterization test exists to catch.

These tests deliberately assert the CURRENT order, including anything odd about
it. They are a photograph, not a judgement: if the order should change, that is
a separate decision, made deliberately, updating this file in the same commit.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from services import signal_pipeline as sp

# The gate sequence as it stands today, read top-to-bottom out of
# SignalPipeline._process(). Regenerate with `_gate_sequence()` below if the
# order is changed ON PURPOSE — and say why in the commit.
#
# Changed once since this list was written: a second "risk" gate was added
# after the existing stop check, rejecting a stop on the WRONG SIDE of entry.
# The differential harness against the standalone engine found that a long
# with its stop above entry was accepted, sized from abs(entry - stop), and
# opened as a position whose stop was already through. This test failing is
# what forced that change to be declared rather than slipped in.
EXPECTED_GATE_ORDER = [
    "controls",             # global pause/stop beats everything
    "market_quality",
    "dedup",
    "execution",            # close-signal with no position
    "execution",            # already open (no pyramiding)
    "risk_guard",           # max open positions
    "correlation",
    "event_risk",
    "learning",
    "risk_guard",           # auto-halt
    "trading_day",
    "session",
    "daily_loss",
    "weekly_loss",
    "risk_guard",           # auto-halt re-check after loss gates
    "cooldown",
    "max_trades",
    "risk",                 # invalid stop (missing or equal to entry)
    "risk",                 # stop on the wrong side of entry — ADDED
    "sizing",
    "exposure",
    "portfolio_exposure",
    "risk_engine",          # the standalone RiskEngine's mandatory veto — ADDED
    "execution",            # rejected at fill
]


def _gate_sequence() -> list[str]:
    """The stage name of every ``reject(...)`` gate, in source order.

    Read from the AST rather than by running the pipeline: reaching the 22nd
    gate at runtime means satisfying the previous 21, so a behavioural probe
    could never observe the whole sequence. The source is the only place the
    full order is visible.

    Reads ``_process``, not ``process`` — the public method is a three-line
    ``with self._proc_lock:`` wrapper and contains no gates at all. Extracting
    from the wrapper silently yields an empty list, which would make every
    ordering assertion below vacuously true; `test_every_gate_name_is_accounted_for`
    is what catches that.
    """
    # dedent, not cleandoc: cleandoc is a DOCSTRING normaliser and strips the
    # first line's indentation only, leaving the body over-indented and
    # unparseable. textwrap.dedent removes the common prefix, which is what a
    # method's source needs.
    src = textwrap.dedent(inspect.getsource(sp.SignalPipeline._process))
    tree = ast.parse(src)
    # (lineno, stage), then sorted — ast.walk is BREADTH-first, not source
    # order, so appending in walk order yields a plausible-looking but wrong
    # sequence. It reported sizing before the loss gates on the first run,
    # which is the opposite of the truth. A characterization test that pins
    # the wrong order is worse than none: it would bless a real reordering
    # during the extraction as "unchanged".
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "reject" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((node.lineno, first.value))
    return [stage for _, stage in sorted(found)]


def test_the_gate_sequence_is_unchanged():
    """The characterization itself.

    If this fails after a refactor, a gate was added, removed or moved. That
    may be correct — but it is a behaviour change and must be an explicit one.
    """
    assert _gate_sequence() == EXPECTED_GATE_ORDER


def test_every_gate_name_is_accounted_for():
    """Guards the guard: an AST walk that silently matched nothing would make
    the ordering test vacuously true."""
    seq = _gate_sequence()
    assert len(seq) >= 20, f"only found {len(seq)} gates — the extractor is broken"


def test_controls_is_the_first_gate():
    """A global stop must beat every other consideration. If a later gate could
    reject first, a paused bot would report 'max positions reached' — and an
    operator would go looking for a position limit instead of the pause they
    themselves set."""
    assert _gate_sequence()[0] == "controls"


def test_dedup_precedes_every_risk_gate():
    """A duplicate webhook is not a risk decision. Letting risk see it first
    would count one alert twice against the daily trade cap."""
    seq = _gate_sequence()
    assert seq.index("dedup") < seq.index("risk_guard")
    assert seq.index("dedup") < seq.index("daily_loss")


def test_loss_limits_precede_sizing():
    """Sizing a trade the daily-loss gate is about to refuse is wasted work,
    and worse, it is how a 'size' appears in a decision log for a trade that
    was never allowed."""
    seq = _gate_sequence()
    assert seq.index("daily_loss") < seq.index("sizing")
    assert seq.index("weekly_loss") < seq.index("sizing")


def test_sizing_precedes_exposure():
    """Exposure is checked against a computed size, so the order is a data
    dependency, not a preference — reversing it would check exposure against
    nothing."""
    seq = _gate_sequence()
    assert seq.index("sizing") < seq.index("exposure")
    assert seq.index("exposure") < seq.index("portfolio_exposure")


def test_the_stop_is_validated_before_the_size_is_computed():
    """Position size is derived from the entry-to-stop distance. Computing it
    from a missing or equal stop is a divide-by-zero or an infinite size."""
    seq = _gate_sequence()
    assert seq.index("risk") < seq.index("sizing")


def test_auto_halt_is_checked_twice_and_that_is_deliberate():
    """The halt flag is re-read after the loss gates because those gates can
    SET it. A single check at the top would let the trade that trips the daily
    limit still execute.

    Pinned because it looks redundant, and the obvious 'cleanup' during an
    extraction is to delete the second one.
    """
    seq = _gate_sequence()
    halts = [i for i, s in enumerate(seq) if s == "risk_guard"]
    assert len(halts) >= 2
    assert any(seq.index("daily_loss") < i for i in halts), (
        "the second auto-halt check must come AFTER the loss gates that set it")


# ── behavioural confirmation ────────────────────────────────────────────────
# The tests above read the source. These prove the order is real at runtime,
# for the gates reachable without elaborate setup.

@pytest.fixture()
def pipeline():
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.controls import TradingControl
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    return sp.SignalPipeline(led, paper, TradingControl(), equity=10_000)


def _alert(alert_id="a1", **over):
    payload = {"alert_id": alert_id, "symbol": "BTCUSDT", "side": "BUY",
               "entry": 100.0, "stop": 95.0, "confidence": 0.9}
    payload.update(over)
    return payload


def test_a_paused_bot_reports_the_pause_not_a_later_rule(pipeline):
    """The runtime counterpart of `test_controls_is_the_first_gate`."""
    pipeline.controls.pause_all()
    result = pipeline.process(_alert())
    assert not result.accepted
    assert "paused" in result.reason.lower() or "controls" in str(result.stage or "").lower()


def test_a_duplicate_is_reported_as_a_duplicate_not_as_a_risk_rejection(pipeline):
    first = pipeline.process(_alert("dup-1"))
    second = pipeline.process(_alert("dup-1"))
    assert not second.accepted
    assert "duplicate" in second.reason.lower()
    # the first was judged on its own merits, not as a duplicate
    assert "duplicate" not in (first.reason or "").lower()


def test_an_invalid_stop_is_refused_before_any_size_is_computed(pipeline):
    """Entry equal to stop: the size formula would divide by zero."""
    result = pipeline.process(_alert("bad-stop", stop=100.0))
    assert not result.accepted
    assert "stop" in result.reason.lower()
