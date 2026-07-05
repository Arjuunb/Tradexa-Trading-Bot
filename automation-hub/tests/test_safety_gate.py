"""Live-trading readiness gate: honest, enforced, locked-by-default. Live is
never allowed unless every real requirement passes and the hard lock is off."""
import pytest

from services.safety_gate import (MIN_PAPER_TRADES, SafetyState,
                                   build_live_readiness)


def _kwargs(**over):
    base = dict(hard_locked=False, closed_paper_trades=MIN_PAPER_TRADES,
                max_daily_loss_pct=0.03, max_drawdown_pct=0.2,
                broker_connected=True, decision_logging=True,
                emergency_stop_tested_at="2026-01-01T00:00:00+00:00")
    base.update(over)
    return base


def test_all_pass_and_not_locked_allows_live():
    r = build_live_readiness(**_kwargs())
    assert r["live_allowed"] is True
    assert r["passed"] == r["total"] == 6


def test_hard_lock_forbids_live_even_when_all_requirements_pass():
    r = build_live_readiness(**_kwargs(hard_locked=True))
    assert r["live_allowed"] is False           # locked by design wins
    assert r["passed"] == 6                       # but the checklist is honest
    assert "locked by design" in r["locked_reason"]


def test_each_missing_requirement_blocks_live():
    # paper record below the minimum
    assert build_live_readiness(**_kwargs(closed_paper_trades=MIN_PAPER_TRADES - 1))["live_allowed"] is False
    # emergency stop never tested
    assert build_live_readiness(**_kwargs(emergency_stop_tested_at=None))["live_allowed"] is False
    # risk guards disabled
    assert build_live_readiness(**_kwargs(max_daily_loss_pct=0))["live_allowed"] is False
    assert build_live_readiness(**_kwargs(max_drawdown_pct=0))["live_allowed"] is False
    # no live broker
    assert build_live_readiness(**_kwargs(broker_connected=False))["live_allowed"] is False
    # decision logging off
    assert build_live_readiness(**_kwargs(decision_logging=False))["live_allowed"] is False


def test_requirement_details_are_specific():
    r = build_live_readiness(**_kwargs(closed_paper_trades=5))
    paper = next(x for x in r["requirements"] if x["key"] == "paper_record")
    assert paper["passed"] is False and "5 closed" in paper["detail"]


def test_safety_state_roundtrip(tmp_path):
    st = SafetyState(str(tmp_path / "safety.json"))
    assert st.emergency_stop_tested_at() is None
    ts = st.mark_emergency_stop_tested()
    assert st.emergency_stop_tested_at() == ts
    # persists across reload
    st2 = SafetyState(str(tmp_path / "safety.json"))
    assert st2.emergency_stop_tested_at() == ts


# ─────────────────────────── endpoints ───────────────────────────
def test_safety_endpoints():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)

    r = client.get("/safety/live-readiness").json()
    assert r["hard_locked"] is True and r["live_allowed"] is False
    assert r["default_mode"] == "paper"
    assert {req["key"] for req in r["requirements"]} == {
        "paper_record", "emergency_stop_tested", "max_daily_loss",
        "max_drawdown", "broker_connected", "decision_logging"}

    # the kill-switch test requires the webhook secret
    assert client.post("/safety/test-emergency-stop").status_code == 401
    ok = client.post("/safety/test-emergency-stop",
                     headers={"X-Webhook-Secret": webhook_api.settings.webhook_secret}).json()
    assert ok["verified"] is True and ok["state_after"] == "Active"
    # and it flips the checklist item to passed
    after = client.get("/safety/live-readiness").json()
    estop = next(x for x in after["requirements"] if x["key"] == "emergency_stop_tested")
    assert estop["passed"] is True
