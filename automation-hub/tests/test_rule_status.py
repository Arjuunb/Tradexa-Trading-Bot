"""Decision transparency: a rule's verdict is five-valued, not a boolean.

The bug this file exists to prevent was live. When ``tradexa.risk`` was not
importable the pipeline recorded:

    Step("risk_engine", True, "tradexa.risk unavailable — veto not applied")

The detail string is honest and no machine reads it. Every consumer that
mattered — the dashboard, the decision store, any audit query — read
``passed=True`` and showed a green tick for a risk veto that never ran. The
distinction between "this rule approved the trade" and "this rule could not be
evaluated" is exactly the distinction a boolean cannot carry.
"""
from __future__ import annotations

import pytest

from services.signal_pipeline import PipelineResult, RuleStatus, SignalPipeline, Step


# ── the model ────────────────────────────────────────────────────────────────

def test_legacy_positional_construction_still_works():
    """~50 call sites build steps as Step(rule, bool, detail). None of them
    should have to change."""
    assert Step("dedup", True, "no duplicate").status == RuleStatus.PASSED
    assert Step("session", False, "outside hours").status == RuleStatus.FAILED


@pytest.mark.parametrize("status,expected_passed", [
    (RuleStatus.PASSED, True),
    (RuleStatus.WEAK, True),        # satisfied, but marginally
    (RuleStatus.FAILED, False),
    (RuleStatus.VETOED, False),
    (RuleStatus.UNAVAILABLE, False),
])
def test_passed_is_derived_from_status(status, expected_passed):
    assert Step("r", status=status, detail="d").passed is expected_passed


def test_unavailable_is_not_a_pass():
    """The specific regression. A rule that could not run has not approved
    anything, and must never read as though it had."""
    step = Step("risk_engine", status=RuleStatus.UNAVAILABLE, detail="module absent")
    assert step.passed is False
    assert step.status == RuleStatus.UNAVAILABLE


def test_status_wins_over_an_inconsistent_passed_argument():
    """If a caller supplies both, they cannot be allowed to disagree — that is
    how the original bug looked from the outside."""
    step = Step("risk_engine", passed=True, status=RuleStatus.UNAVAILABLE, detail="")
    assert step.passed is False


def test_status_survives_serialisation():
    """PipelineResult.to_dict is what reaches the API and the decision store."""
    result = PipelineResult(False, "risk_engine", "vetoed", steps=[
        Step("controls", True, "trading active"),
        Step("risk_engine", status=RuleStatus.VETOED, detail="daily loss limit"),
    ])
    steps = result.to_dict()["steps"]
    assert steps[0]["status"] == RuleStatus.PASSED
    assert steps[1]["status"] == RuleStatus.VETOED
    assert steps[1]["passed"] is False


# ── the pipeline emits them ──────────────────────────────────────────────────

def _pipeline():
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.controls import TradingControl

    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    return SignalPipeline(led, paper, TradingControl(), equity=10_000)


def test_an_absent_risk_engine_is_recorded_unavailable_not_passed():
    """The end-to-end version of the regression: run a trade that clears every
    other gate with the risk engine absent, and confirm the trail says so."""
    pipe = _pipeline()
    pipe.risk_engine = None                     # simulate the partial deployment

    result = pipe.process({"alert_id": "rs-1", "symbol": "ETHUSDT", "side": "buy",
                           "entry": 3000, "stop": 2900})

    risk_steps = [s for s in result.steps if s.rule == "risk_engine"]
    assert risk_steps, f"no risk_engine step recorded (stage={result.stage})"
    step = risk_steps[0]
    assert step.status == RuleStatus.UNAVAILABLE, (
        f"risk engine did not run but was recorded as {step.status!r}")
    assert step.passed is False, "an unrun veto must not read as a pass"
    assert "NOT applied" in step.detail


def test_a_failing_gate_is_recorded_failed():
    """A rule the trade genuinely did not satisfy — distinct from one that
    could not be evaluated."""
    pipe = _pipeline()
    pipe.controls.stop_all()                    # halt trading

    result = pipe.process({"alert_id": "rs-2", "symbol": "ETHUSDT", "side": "buy",
                           "entry": 3000, "stop": 2900})

    assert result.accepted is False
    failed = [s for s in result.steps if s.rule == result.stage]
    assert failed and failed[0].status == RuleStatus.FAILED
    assert failed[0].passed is False


def test_every_status_the_pipeline_emits_is_a_known_one():
    """Guards against a typo'd literal creeping in — a status string the UI
    has no case for renders as nothing at all."""
    pipe = _pipeline()
    pipe.risk_engine = None

    results = [
        pipe.process({"alert_id": "rs-3", "symbol": "ETHUSDT", "side": "buy",
                      "entry": 3000, "stop": 2900}),
        pipe.process({"alert_id": "rs-3", "symbol": "ETHUSDT", "side": "buy",
                      "entry": 3000, "stop": 2900}),          # duplicate alert_id
    ]
    seen = {s.status for r in results for s in r.steps}
    assert seen, "no steps recorded at all"
    unknown = seen - set(RuleStatus.ALL)
    assert not unknown, f"unknown rule statuses emitted: {unknown}"
