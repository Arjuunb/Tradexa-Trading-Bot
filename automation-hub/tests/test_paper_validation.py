"""Paper-trading validation readiness (Phase 8): multi-factor eligibility that
never unlocks live on one good metric, plus honest skip categorisation."""
import pytest

from data.skipped_store import category_for
from services.paper_validation import (MIN_EVIDENCE, MIN_REVIEW,
                                        build_paper_validation)

READY = {"requirements": [
    {"key": "max_daily_loss", "passed": True}, {"key": "max_drawdown", "passed": True},
    {"key": "decision_logging", "passed": True}, {"key": "emergency_stop_tested", "passed": True},
    {"key": "broker_connected", "passed": False}, {"key": "paper_record", "passed": True}],
    "live_allowed": False, "hard_locked": True, "passed": 5, "total": 6}


def _perf(trades=40, pf=1.6, exp=12.0, **k):
    return {"trades": trades, "profit_factor": pf, "expectancy": exp,
            "win_rate": 58.0, "max_drawdown_pct": 8.0, "sharpe_ratio": 0.4,
            "sortino_ratio": 1.0, **k}


def _build(**over):
    base = dict(perf=_perf(), avg_rr=1.3, per_symbol=[{"name": "BTCUSDT", "net_pnl": 200},
                {"name": "ETHUSDT", "net_pnl": -50}], per_strategy=[{"name": "Decision Brain", "net_r": 12}],
                skipped_total=5, skipped_by_category=[{"category": "risk", "count": 5}], readiness=READY)
    base.update(over)
    return build_paper_validation(**base)


def test_category_mapping_is_real_never_faked():
    assert category_for("controls") == "safety"
    assert category_for("market_quality") == "quality"
    assert category_for("dedup") == "duplicate"
    assert category_for("session") == "session"
    assert category_for("daily_loss") == "risk"
    assert category_for("learning") == "signal"
    assert category_for("totally-unknown-gate") == "other"   # honest fallback


def test_eligible_when_sample_edge_and_safety_all_met():
    r = _build()
    assert r["live_review"]["eligible"] is True
    assert r["live_review"]["stage"] == "ready-for-review (early)"   # 40 trades
    # live is NEVER unlocked by this verdict
    assert r["safety"]["hard_locked"] is True and r["safety"]["live_allowed"] is False
    assert "stays LOCKED" in r["live_review"]["note"]


def test_evidence_stage_at_50_plus():
    assert _build(perf=_perf(trades=60))["live_review"]["stage"] == "ready-for-review (evidence)"


def test_insufficient_sample_blocks_regardless_of_metrics():
    # gorgeous metrics but only 5 trades -> not eligible
    r = _build(perf=_perf(trades=5, pf=5.0, exp=99.0))
    assert r["live_review"]["eligible"] is False
    assert r["live_review"]["stage"] == "insufficient-sample"


def test_one_good_metric_cannot_unlock_review():
    # enough trades, but no proven edge (pf < 1) -> not eligible
    assert _build(perf=_perf(trades=40, pf=0.8, exp=-2.0))["live_review"]["eligible"] is False
    # enough trades + edge, but a safety guard off -> not eligible
    bad_safety = dict(READY, requirements=[{"key": "max_daily_loss", "passed": False},
        {"key": "max_drawdown", "passed": True}, {"key": "decision_logging", "passed": True},
        {"key": "emergency_stop_tested", "passed": True}])
    assert _build(readiness=bad_safety)["live_review"]["eligible"] is False


def test_best_worst_picks_are_real():
    r = _build()
    assert r["best_symbol"]["name"] == "BTCUSDT" and r["worst_symbol"]["name"] == "ETHUSDT"
    assert r["best_strategy"]["name"] == "Decision Brain"


def test_thresholds_match_journal_staging():
    assert MIN_REVIEW == 30 and MIN_EVIDENCE == 50


def test_validation_endpoint():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    j = client.get("/validation/paper").json()
    assert j["safety"]["hard_locked"] is True
    assert j["live_review"]["eligible"] is False           # no trades in a fresh store
    assert set(j["metrics"]) >= {"win_rate", "profit_factor", "expectancy",
                                 "max_drawdown_pct", "avg_rr", "sharpe_ratio", "sortino_ratio"}
