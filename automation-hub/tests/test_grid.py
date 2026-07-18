"""Server-side grid engine + endpoints (paper). Pure fill logic is deterministic;
the runner lifecycle is exercised against the API with guaranteed teardown."""
import pytest

from services.grid_engine import GridBot, level_prices


def test_levels_arithmetic_and_geometric():
    a = level_prices(100, 110, 11, False)
    assert a[0] == 100 and a[-1] == 110 and len(a) == 11
    assert abs((a[1] - a[0]) - 1.0) < 1e-9                      # even $1 steps
    g = level_prices(100, 200, 5, True)
    assert g[0] == 100 and abs(g[-1] - 200) < 1e-6
    r = g[1] / g[0]
    assert abs((g[2] / g[1]) - r) < 1e-9                        # constant ratio


def test_seed_and_roundtrip():
    b = GridBot(symbol="BTCUSDT", timeframe="5m", lower=100, upper=110, levels=11,
                geometric=False, investment=1000, leverage=1, fee_pct=0.04, start_price=105)
    lots, cost = b.inventory()
    assert lots == 5 and abs(cost - 500) < 1                    # upper half seeded (~half the capital)
    assert b.buys == 5 and b.realized == 0.0
    fills = b.on_candle(100, 110, 108, "2026-07-18T00:00:00")   # full sweep down then up
    assert b.completed == 10 and b.realized > 0                 # every gap round-tripped, net positive
    assert any(f["side"] == "SELL" for f in fills)
    assert b.inventory()[0] == 0                                # everything sold at the top


def test_fees_below_step_can_lose():
    # tiny grid step vs a big fee -> a completed grid can be a net loss (honest)
    b = GridBot(symbol="BTCUSDT", timeframe="5m", lower=100, upper=100.1, levels=2,
                geometric=False, investment=1000, leverage=1, fee_pct=1.0, start_price=100.05)
    b.on_candle(100, 100.1, 100.05, "t")
    assert b.realized < 0


def test_snapshot_resume_preserves_state():
    b = GridBot(symbol="ETHUSDT", timeframe="1m", lower=1000, upper=1100, levels=11,
                geometric=False, investment=500, leverage=1, fee_pct=0.04, start_price=1050)
    b.on_candle(1000, 1100, 1080, "t1")
    b2 = GridBot.from_dict(b.to_dict())
    assert b2.realized == b.realized and b2.completed == b.completed
    assert b2.buys == b.buys and b2.sells == b.sells and len(b2.gaps) == len(b.gaps)
    assert b2.unrealized(1080) == b.unrealized(1080)


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_grid_endpoints_lifecycle(client):
    import webhook_api as wa
    sec = {"X-Webhook-Secret": wa.settings.webhook_secret}
    try:
        assert client.get("/grid/status").json()["running"] is False
        assert client.post("/grid/start", json={"symbol": "BTCUSDT"}).status_code == 401  # secret required
        r = client.post("/grid/start", json={
            "symbol": "BTCUSDT", "timeframe": "5m", "lower": 60000, "upper": 66000,
            "levels": 20, "geometric": False, "investment": 1000, "leverage": 2, "fee_pct": 0.04,
        }, headers=sec)
        assert r.status_code == 200 and r.json()["started"] is True
        st = client.get("/grid/status").json()
        assert st["running"] is True and st["symbol"] == "BTCUSDT" and st["levels"] == 20
        # bad config -> 400
        assert client.post("/grid/start", json={"symbol": "BTCUSDT", "lower": 100},
                           headers=sec).status_code == 400
    finally:
        client.post("/grid/stop", headers=sec)                 # never leak the thread / persisted file
    assert client.get("/grid/status").json()["running"] is False
