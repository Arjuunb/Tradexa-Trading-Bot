"""Strategy retune gate (Phase 10): never retune from a small sample; promotion
needs evidence; only a critical-bug override bypasses the sample gate."""
import pytest

from services.retune_gate import (MIN_EVIDENCE, MIN_REVIEW,
                                   evaluate_retune_gate)


def test_below_review_blocks_retune():
    g = evaluate_retune_gate(closed_paper_trades=10)
    assert g["allowed"] is False and g["promotion_allowed"] is False
    assert g["stage"] == "insufficient-sample"
    assert "no retune from a small sample" in g["reason"].lower()


def test_early_review_runs_no_retune_no_promotion():
    g = evaluate_retune_gate(closed_paper_trades=35)
    assert g["stage"] == "early-review"
    assert g["allowed"] is False and g["promotion_allowed"] is False


def test_evidence_level_allows_search_and_promotion_consideration():
    g = evaluate_retune_gate(closed_paper_trades=60)
    assert g["stage"] == "evidence"
    assert g["allowed"] is True and g["promotion_allowed"] is True


def test_critical_bug_override_bypasses_sample_gate_but_not_promotion():
    g = evaluate_retune_gate(closed_paper_trades=3, critical_bug=True)
    assert g["allowed"] is True                    # a broken path may be fixed
    assert g["promotion_allowed"] is False         # but never auto-promoted
    assert g["stage"] == "critical-bug-override"


def test_thresholds_match_validation_staging():
    assert MIN_REVIEW == 30 and MIN_EVIDENCE == 50


# ─────────────────────────── endpoints ───────────────────────────
def test_retune_gate_and_run_endpoints():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    sec = {"X-Webhook-Secret": webhook_api.settings.webhook_secret}

    g = client.get("/retune/gate").json()
    assert g["stage"] == "insufficient-sample" and g["allowed"] is False

    # a fresh store has no closed trades -> retune is refused by the gate
    r = client.post("/retune/run", headers=sec).json()
    assert r["ran"] is False and r["blocked"] is True
    assert r["gate"]["stage"] == "insufficient-sample"

    # and it requires the secret
    assert client.post("/retune/run").status_code == 401
