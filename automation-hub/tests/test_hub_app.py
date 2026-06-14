"""Phase 1 end-to-end: login -> create bot -> start (paper) -> dashboard.

Skips cleanly if FastAPI isn't installed (so the parent engine's suite still
runs without the hub extra).
"""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import app as hub_app  # noqa: E402
from bots.manager import BotManager  # noqa: E402


@pytest.fixture()
def client():
    # Fresh manager + sessions per test.
    hub_app.manager = BotManager()
    hub_app._sessions.clear()
    return TestClient(hub_app.app, follow_redirects=False)


def _login(client) -> None:
    r = client.post("/login", data={"username": "admin", "password": "admin"})
    assert r.status_code == 303
    token = r.cookies.get(hub_app.COOKIE)
    assert token and token in hub_app._sessions


def test_dashboard_requires_login(client):
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_rejects_bad_password(client):
    r = client.post("/login", data={"username": "admin", "password": "nope"})
    assert r.status_code == 303
    assert "error" in r.headers["location"]


def test_full_phase1_flow(client):
    _login(client)

    # Dashboard renders with the spec's KPI labels + sidebar.
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "Automation Hub" in body
    for label in ("Running Bots", "Paper Bots", "Alerts",
                  "Active Bots", "Risk Center", "Recent Activity"):
        assert label in body
    assert "P&amp;L" in body  # Today's P&L KPI (HTML-escaped)
    for nav in ("Overview", "Bots", "Strategies", "Paper Trading",
                "Live Trading", "Risk Center", "Analytics", "Logs",
                "Notifications", "Settings"):
        assert nav in body

    # Create an EMA bot.
    r = client.post("/bots", data={
        "name": "EMA Trend Bot", "strategy": "ema", "exchange": "binance",
        "symbol": "BTCUSDT", "timeframe": "1h", "mode": "paper",
        "risk_per_trade": "1.0", "max_daily_loss": "3.0",
    })
    assert r.status_code == 303
    bots = hub_app.manager.list()
    assert len(bots) == 1
    bot = bots[0]
    assert bot.config.strategy == "ema"

    # Start it -> paper run executes, runtime gets populated.
    r = client.post(f"/bots/{bot.id}/start")
    assert r.status_code == 303
    assert bot.runtime.state.value == "Paper Mode"
    assert "num_trades" in bot.runtime.metrics
    assert bot.runtime.equity_curve

    # Pause it.
    r = client.post(f"/bots/{bot.id}/pause")
    assert r.status_code == 303
    assert bot.runtime.state.value == "Paused"

    # Emergency stop halts everything.
    client.post(f"/bots/{bot.id}/start")
    r = client.post("/emergency-stop")
    assert r.status_code == 303
    assert bot.runtime.state.value == "Stopped"


def test_secondary_pages_render(client):
    _login(client)
    for path in ("/bots", "/bots/new", "/strategies", "/paper-trading",
                 "/risk-center", "/analytics", "/logs", "/live-trading",
                 "/notifications", "/settings"):
        assert client.get(path).status_code == 200


def test_health_open(client):
    assert client.get("/health").json()["status"] == "ok"
