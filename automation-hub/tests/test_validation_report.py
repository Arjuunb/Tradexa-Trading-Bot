"""Phase 9: daily paper-validation report + persistence-survives-restart.
Real data only; the report never unlocks live trading."""
import pytest

from services.validation_report import build_daily_report


def _validation(sample=40, eligible=False):
    return {"sample_size": sample, "min_review": 30, "min_evidence": 50,
            "metrics": {"win_rate": 55, "profit_factor": 1.5, "expectancy": 8,
                        "avg_rr": 1.2, "max_drawdown_pct": 9, "sharpe_ratio": 0.3,
                        "sortino_ratio": 0.8},
            "best_symbol": {"name": "BTCUSDT", "net_pnl": 100},
            "worst_symbol": {"name": "ETHUSDT", "net_pnl": -20},
            "best_strategy": None, "worst_strategy": None,
            "skipped_total": 6, "skipped_by_category": [{"category": "risk", "count": 6}],
            "safety": {"live_allowed": False, "hard_locked": True, "passed": 4, "total": 6},
            "live_review": {"eligible": eligible, "stage": "not-eligible", "reasons": ["…"]}}


def test_report_always_states_live_locked():
    r = build_daily_report(validation=_validation(eligible=True), recent={}, previous={},
                           risk_events=[], health_errors=[])
    assert r["live_trading"] == "LOCKED"
    assert "never unlocks live" in r["note"]
    # even when the review verdict is 'eligible', the report never flips live on
    assert r["safety"]["hard_locked"] is True


def test_trend_improving_stable_weakening():
    imp = build_daily_report(validation=_validation(),
                             recent={"n": 20, "win_rate": 60, "profit_factor": 1.8, "expectancy": 10},
                             previous={"n": 20, "win_rate": 50, "profit_factor": 1.4, "expectancy": 6},
                             risk_events=[], health_errors=[])
    assert imp["trend"]["direction"] == "improving"
    weak = build_daily_report(validation=_validation(),
                              recent={"n": 20, "win_rate": 45, "profit_factor": 1.1, "expectancy": 2},
                              previous={"n": 20, "win_rate": 55, "profit_factor": 1.6, "expectancy": 9},
                              risk_events=[], health_errors=[])
    assert weak["trend"]["direction"] == "weakening"
    none = build_daily_report(validation=_validation(), recent={}, previous={},
                              risk_events=[], health_errors=[])
    assert none["trend"]["direction"] == "not-enough-history"


def test_report_carries_real_counts():
    r = build_daily_report(validation=_validation(sample=42), recent={"n": 1}, previous={"n": 1},
                           risk_events=[{"stage": "risk_guard"}], health_errors=[{"message": "x"}])
    assert r["closed_trades"]["count"] == 42
    assert r["skipped"]["total"] == 6
    assert len(r["risk_events"]) == 1 and len(r["health_errors"]) == 1


def test_daily_report_endpoint():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    r = TestClient(app).get("/validation/daily-report").json()
    assert r["live_trading"] == "LOCKED"
    assert r["live_review"]["eligible"] is False


# ─────────────────────── persistence survives a restart ───────────────────────
def test_stores_persist_across_restart(tmp_path):
    """A 'restart' = a fresh store instance pointing at the same file. Paper
    skip log, decision journal and safety state must all survive it."""
    from data.skipped_store import SkippedTradeStore
    from data.journal_store import JournalStore
    from services.safety_gate import SafetyState

    skip_db = str(tmp_path / "skipped.db")
    jrnl_db = str(tmp_path / "journal.db")
    safe_js = str(tmp_path / "safety.json")

    # write via the first instances
    SkippedTradeStore(skip_db).record(symbol="BTCUSDT", side="BUY", stage="risk_guard",
                                      reason="max positions")
    js = JournalStore(jrnl_db)
    js.record_entry({"trade_id": "t1", "mode": "paper", "symbol": "BTCUSDT", "side": "long",
                     "strategy": "Decision Brain", "timeframe": "4h", "entry": 100, "stop": 95,
                     "target": 115, "size": 1.0, "risk_amount": 5, "planned_rr": 3.0,
                     "confidence": 0.8, "brain_score": 0.5, "regime": "Trending", "sections": {}})
    ts = SafetyState(safe_js).mark_emergency_stop_tested()

    # restart: brand-new instances on the same paths
    assert len(SkippedTradeStore(skip_db).list()) == 1
    assert JournalStore(jrnl_db).get("t1") is not None
    assert SafetyState(safe_js).emergency_stop_tested_at() == ts
