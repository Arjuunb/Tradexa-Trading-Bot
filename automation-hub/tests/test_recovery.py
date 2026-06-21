"""Strategy Health scorecard (#10) + Drawdown Recovery (#18)."""
import pytest

from services.recovery import (stability_score, confidence_score, health_scorecard,
                               drawdown_recovery)


def _trades(rs):
    return [{"pnl": r, "r": r} for r in rs]


def test_stability_higher_for_smooth_curve():
    smooth = _trades([1, 1, 1, 1, 1, 1, 1, 1])
    choppy = _trades([3, -2, 4, -3, 5, -4, 3, -2])
    assert stability_score(smooth) > stability_score(choppy)
    assert 0 <= stability_score(choppy) <= 100


def test_confidence_grows_with_sample_and_edge():
    few = _trades([1, 1, -1])
    many = _trades([2, -1, 2, -1, 2, -1, 2, -1, 2, -1] * 4)   # strong PF, big sample
    assert confidence_score(many) > confidence_score(few)
    assert confidence_score([]) == 0


def test_health_scorecard_flags_unhealthy_loser():
    losers = _trades([-1, -1, -1, 0.5, -1, -1, -1, -1, -1, -1])
    card = health_scorecard(losers)
    assert card["unhealthy"] is True
    for k in ("win_rate", "profit_factor", "expectancy", "max_drawdown",
              "stability_score", "confidence_score", "status"):
        assert k in card


def test_health_scorecard_healthy_winner():
    winners = _trades([2, -1, 2, 2, -1, 2, 2, -1, 2, 2, 2, -1])
    card = health_scorecard(winners)
    assert card["unhealthy"] is False and card["confidence_score"] > 0


def test_drawdown_recovery_modes_escalate():
    assert drawdown_recovery(10_000, 9_800)["mode"] == "normal"        # 2% dd
    assert drawdown_recovery(10_000, 9_200)["mode"] == "caution"       # 8%
    assert drawdown_recovery(10_000, 8_700)["mode"] == "recovery"      # 13%
    lock = drawdown_recovery(10_000, 7_500)                            # 25%
    assert lock["mode"] == "lockdown" and lock["risk_multiplier"] == 0.0
    # deeper drawdown never increases the risk multiplier
    mults = [drawdown_recovery(10_000, e)["risk_multiplier"] for e in (9_900, 9_300, 8_800, 8_000)]
    assert mults == sorted(mults, reverse=True)


def test_drawdown_recovery_actions_present_when_active():
    r = drawdown_recovery(10_000, 8_800)
    assert r["recovery_active"] is True and r["actions"]
    assert drawdown_recovery(10_000, 10_000)["actions"] == []


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_health_and_recovery_endpoints(client):
    card = client.get("/health/scorecard", params={"symbol": "BTCUSDT", "strategy": "EMA 8/30",
                                                   "timeframe": "15m", "limit": 600}).json()
    assert card["available"] is True
    assert "stability_score" in card and "confidence_score" in card and "unhealthy" in card
    rec = client.get("/risk/recovery").json()
    assert "mode" in rec and "risk_multiplier" in rec and "drawdown_pct" in rec and "actions" in rec
