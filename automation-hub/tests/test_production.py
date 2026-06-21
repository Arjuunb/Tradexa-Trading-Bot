"""Production Readiness (#19)."""
from datetime import datetime, timedelta, timezone

import pytest

from services.production import readiness, freshness_summary, memory_mb


def _cov(n_with_data, last_age_s=120):
    last = (datetime.now(timezone.utc) - timedelta(seconds=last_age_s)).isoformat()
    rows = [{"symbol": f"S{i}", "timeframe": "1d", "candles": 100, "last": last} for i in range(n_with_data)]
    rows += [{"symbol": "EMPTY", "timeframe": "1d", "candles": 0, "last": None}]
    return rows


def test_healthy_when_all_pass():
    r = readiness(api_ok=True, db_ok=True, db_detail="ok", coverage=_cov(3),
                  strategy_errors=0, order_errors=0, uptime_s=500, engine_running=True)
    assert r["status"] == "healthy"
    assert all(c["ok"] for c in r["checks"])
    assert r["summary"].startswith("6/6")


def test_degraded_on_errors_or_no_data():
    r = readiness(api_ok=True, db_ok=True, db_detail="ok", coverage=_cov(0),
                  strategy_errors=2, order_errors=1, uptime_s=10, engine_running=False)
    assert r["status"] == "degraded"
    names = {c["name"]: c for c in r["checks"]}
    assert names["Data freshness"]["ok"] is False
    assert names["Strategy errors"]["ok"] is False and names["Engine"]["ok"] is False


def test_down_when_db_unreachable():
    r = readiness(api_ok=True, db_ok=False, db_detail="boom", coverage=[],
                  strategy_errors=0, order_errors=0, uptime_s=5, engine_running=True)
    assert r["status"] == "down"
    assert any(c["name"] == "Database" and c["level"] == "down" for c in r["checks"])


def test_freshness_summary_counts_and_age():
    f = freshness_summary(_cov(2, last_age_s=300))
    assert f["with_data"] == 2 and f["datasets"] == 3
    assert f["freshest_age_s"] is not None and f["freshest_age_s"] >= 290


def test_memory_mb_returns_number_or_none():
    m = memory_mb()
    assert m is None or m > 0


# ───────────────────────── endpoint ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_production_endpoint(client):
    r = client.get("/production/readiness").json()
    assert "status" in r and "checks" in r and len(r["checks"]) == 6
    assert "memory_mb" in r and "uptime_s" in r and "data_freshness" in r
