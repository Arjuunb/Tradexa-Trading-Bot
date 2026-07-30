"""Every trade passes through the Risk Engine before execution.

The standalone engine's own 64 tests prove it decides correctly. They say
nothing about whether production asks it — an engine that is never consulted is
a very well-tested no-op. This file covers the wiring: that the live pipeline
calls it on every entry, that a refusal stops the trade, and that no path
reaches a fill without it.

The veto is deliberately NOT a second sizer. The pipeline keeps sizing because
it holds nine strategy-derived modifiers the engine cannot see without
depending on strategies. So what is asserted here is authority, not arithmetic:
the engine can say no, and no is final.
"""
from __future__ import annotations

import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services import signal_pipeline as sp

from tradexa.risk import RiskDecision, RuleResult


@pytest.fixture()
def pipeline():
    led = SqliteLedger(":memory:")
    return sp.SignalPipeline(led, PaperExecutionEngine(led), TradingControl(),
                             equity=10_000)


def _alert(alert_id="w1", **over):
    payload = {"alert_id": alert_id, "symbol": "BTCUSDT", "side": "BUY",
               "entry": 100.0, "stop": 95.0, "confidence": 0.9}
    payload.update(over)
    return payload


class _Recorder:
    """Stands in for the engine and records that it was asked."""

    def __init__(self, approve=True):
        self.approve = approve
        self.calls = []

    def evaluate(self, ctx):
        self.calls.append(ctx)
        if self.approve:
            return RiskDecision(approved=True, quantity=1.0, reason="approved",
                                limits_name="test")
        return RiskDecision(
            approved=False, rule="test_rule", reason="refused by the engine",
            checks=(RuleResult("test_rule", False, "refused by the engine"),),
            limits_name="test")


# ── the engine is consulted ─────────────────────────────────────────────────

def test_the_engine_is_built_and_attached(pipeline):
    assert pipeline.risk_engine is not None, (
        "the pipeline built no risk engine — every trade would skip the veto")


def test_every_accepted_trade_was_seen_by_the_engine(pipeline):
    rec = _Recorder()
    pipeline.risk_engine = rec
    result = pipeline.process(_alert())
    assert result.accepted
    assert len(rec.calls) == 1, "the engine was not consulted for an accepted trade"


def test_a_refusal_blocks_the_trade(pipeline):
    """The whole point. If the engine says no and a position opens anyway, the
    veto is decorative."""
    pipeline.risk_engine = _Recorder(approve=False)
    result = pipeline.process(_alert())
    assert not result.accepted
    assert result.stage == "risk_engine"
    assert "refused by the engine" in result.reason
    assert pipeline.paper.positions() == [], (
        "the engine refused and a position was opened anyway — the veto is bypassable")


def test_the_refusal_reason_names_the_rule(pipeline):
    """A rejection that says only 'blocked by risk' sends an operator hunting."""
    pipeline.risk_engine = _Recorder(approve=False)
    result = pipeline.process(_alert())
    assert "test_rule" in result.reason


def test_the_decision_trail_records_the_engine_step(pipeline):
    result = pipeline.process(_alert())
    stages = [s.rule for s in result.steps]
    assert "risk_engine" in stages, (
        "an accepted trade's trail does not show the engine ran — an audit "
        "could not tell whether it was consulted")


# ── the context the engine is given is truthful ─────────────────────────────

def test_the_context_carries_the_real_book(pipeline):
    rec = _Recorder()
    pipeline.process(_alert("first"))            # opens a real position
    pipeline.risk_engine = rec
    pipeline.process(_alert("second", symbol="ETHUSDT"))
    ctx = rec.calls[0]
    assert len(ctx.positions) == 1
    assert ctx.positions[0].symbol == "BTCUSDT"
    assert ctx.gross_exposure > 0, (
        "the engine was handed an empty book while a position was open — it "
        "would judge exposure against a state that does not exist")


def test_the_context_uses_the_same_loss_base_as_the_pipeline_gates(pipeline):
    """Both must measure the daily limit against the same denominator, or the
    same P&L clears one gate and trips the other."""
    rec = _Recorder()
    pipeline.risk_engine = rec
    pipeline.process(_alert())
    assert rec.calls[0].account.starting_equity == pipeline.paper.starting_balance


def test_the_context_direction_follows_the_signal(pipeline):
    rec = _Recorder()
    pipeline.risk_engine = rec
    pipeline.process(_alert("short-1", side="SELL", stop=105.0))
    assert rec.calls[0].proposal.direction.value == "short"


# ── behaviour is unchanged ──────────────────────────────────────────────────

def test_a_clean_trade_still_opens(pipeline):
    """The veto runs under parity limits: a subset of the gates above it. If it
    refuses an ordinary trade, the switch tightened live risk under the guise of
    a refactor."""
    result = pipeline.process(_alert())
    assert result.accepted, f"a clean trade was refused: {result.reason}"
    assert len(pipeline.paper.positions()) == 1


@pytest.mark.parametrize("confidence", [0.1, 0.5, 0.9, 1.0])
def test_the_veto_passes_at_every_conviction(pipeline, confidence):
    result = pipeline.process(_alert(f"c{confidence}", confidence=confidence))
    assert result.accepted, f"confidence {confidence} refused: {result.reason}"


def test_the_pipeline_still_sizes_the_trade_not_the_engine(pipeline):
    """The engine approves a quantity of its own; the pipeline's nine modifiers
    are what actually size the position. Asserted so a later 'simplification'
    that adopts the engine's size has to face this test first — it would
    silently discard the Kelly guard, the learning store and the allocator."""
    rec = _Recorder()            # approves 1.0 unit, deliberately unrealistic
    pipeline.risk_engine = rec
    result = pipeline.process(_alert())
    assert result.accepted
    assert float(result.fill["size"]) != pytest.approx(1.0), (
        "the fill took the engine's quantity — the pipeline's sizing modifiers "
        "were bypassed")


def test_an_unimportable_engine_announces_itself(capsys, monkeypatch):
    """The guarded import degrades quietly, and for one release that was the
    problem rather than the safety net: `tradexa` was missing from the installed
    package list, so production ran with no veto and nothing said so. Silence is
    the failure mode."""
    monkeypatch.setattr(sp, "_RiskEngine", None)
    led = SqliteLedger(":memory:")
    pipe = sp.SignalPipeline(led, PaperExecutionEngine(led), TradingControl())
    assert pipe.risk_engine is None
    out = capsys.readouterr().out
    assert "NOT being applied" in out
    assert "pyproject" in out, "the warning must say how to fix it"


def test_a_missing_engine_does_not_break_trading(pipeline):
    """A deployment shipping only automation-hub has no tradexa package. It must
    still trade, and the trail must SAY the veto was absent rather than looking
    identical to one where it ran and passed."""
    pipeline.risk_engine = None
    result = pipeline.process(_alert())
    assert result.accepted
    note = [s.detail for s in result.steps if s.rule == "risk_engine"]
    assert note and "unavailable" in note[0]


# ── no way round it ─────────────────────────────────────────────────────────

def test_the_veto_precedes_execution_in_the_source():
    """Structural, not behavioural: proves there is no ordering in which a fill
    happens before the engine has spoken."""
    import inspect
    src = inspect.getsource(sp.SignalPipeline._process)
    assert src.index("risk_engine") < src.index("self.paper.open("), (
        "the fill is issued before the risk engine is consulted")


def test_the_engine_limits_track_the_pipeline_config():
    """An operator who tightens a cap must tighten both paths at once. Limits
    copied by hand drift the first time one side is edited."""
    led = SqliteLedger(":memory:")
    pipe = sp.SignalPipeline(led, PaperExecutionEngine(led), TradingControl(),
                             equity=10_000, max_open_positions=7,
                             max_correlated_positions=5,
                             max_total_exposure_pct=0.42)
    limits = pipe.risk_engine.limits
    assert limits.max_open_positions == 7
    assert limits.max_correlated_positions == 5
    assert limits.max_total_exposure_pct == 0.42


def test_the_engine_never_enables_a_rule_the_pipeline_lacks():
    """Parity means SUBSET. These five rules have never existed in the pipeline;
    switching them on here would make the wiring a silent tightening of live
    risk rather than a refactor. Turning them on is `tradexa.risk.STRICT`, opted
    into deliberately."""
    led = SqliteLedger(":memory:")
    limits = sp.SignalPipeline(led, PaperExecutionEngine(led),
                               TradingControl()).risk_engine.limits
    for field in ("max_account_risk_pct", "max_leverage", "min_free_margin_pct",
                  "news_blackout_minutes", "max_volatility_pct"):
        assert getattr(limits, field) == 0, (
            f"{field} is enforced by the engine but not by the pipeline — the "
            "veto is no longer a subset and can refuse trades that used to pass")
