"""On-chart drag-to-adjust stop-loss / take-profit.

Covers the new POST /paper/stop-target endpoint and the engine's thread-safe
apply_manual_levels / managed_snapshot, which back the on-chart drag feature.
Everything runs on an isolated in-memory paper engine so the shared account is
never touched. Paper only — this never routes a live order."""
import pytest


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


# ----------------------------------------------------------------- endpoint

def test_stop_target_endpoint(client):
    import webhook_api as wa
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    orig_paper = wa.paper
    wa.paper = PaperExecutionEngine(SqliteLedger(":memory:"), starting_balance=10_000)
    try:
        wa.paper.open(symbol="BTCUSDT", side="long", size=0.5, entry=100.0, stop=95.0)
        sec = {"X-Webhook-Secret": wa.settings.webhook_secret}

        # move the stop up (trail toward break-even) — persists to the ledger
        r = client.post("/paper/stop-target", json={"symbol": "BTCUSDT", "stop": 98.0}, headers=sec)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True and r.json()["stop"] == 98.0
        pos = wa.paper.open_position("BTCUSDT")
        assert pos["stop"] == 98.0                       # durably persisted

        # set a take-profit — held in engine memory, surfaced on /paper/positions
        r = client.post("/paper/stop-target", json={"symbol": "BTCUSDT", "target": 130.0}, headers=sec)
        assert r.status_code == 200 and r.json()["target"] == 130.0
        listed = next(p for p in client.get("/paper/positions").json() if p["symbol"] == "BTCUSDT")
        assert listed.get("target") == 130.0

        # both at once
        r = client.post("/paper/stop-target", json={"symbol": "BTCUSDT", "stop": 99.0, "target": 140.0}, headers=sec)
        assert r.status_code == 200 and r.json()["stop"] == 99.0 and r.json()["target"] == 140.0
    finally:
        wa.paper = orig_paper
        try:
            for s in ("BTCUSDT", "ETHUSDT"):
                wa.engine._targets.pop(s, None)
                wa.engine._managed.pop(s, None)
        except Exception:
            pass


def test_stop_target_guards(client):
    import webhook_api as wa
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    orig_paper = wa.paper
    wa.paper = PaperExecutionEngine(SqliteLedger(":memory:"), starting_balance=10_000)
    try:
        wa.paper.open(symbol="ETHUSDT", side="long", size=1.0, entry=2000.0, stop=1900.0)
        sec = {"X-Webhook-Secret": wa.settings.webhook_secret}

        assert client.post("/paper/stop-target", json={"symbol": "ETHUSDT"}, headers=sec).status_code == 400   # nothing to change
        assert client.post("/paper/stop-target", json={"symbol": "ETHUSDT", "stop": -1}, headers=sec).status_code == 400
        assert client.post("/paper/stop-target", json={"symbol": "NOPE", "stop": 10}, headers=sec).status_code == 404
        assert client.post("/paper/stop-target", json={"symbol": "", "stop": 10}, headers=sec).status_code == 400
        assert client.post("/paper/stop-target", json={"symbol": "ETHUSDT", "stop": 10}).status_code == 401  # secret required

        # for a long, a stop at/above the target is nonsensical → 400
        client.post("/paper/stop-target", json={"symbol": "ETHUSDT", "target": 2200.0}, headers=sec)
        assert client.post("/paper/stop-target", json={"symbol": "ETHUSDT", "stop": 2300.0}, headers=sec).status_code == 400
    finally:
        wa.paper = orig_paper
        try:
            for s in ("BTCUSDT", "ETHUSDT"):
                wa.engine._targets.pop(s, None)
                wa.engine._managed.pop(s, None)
        except Exception:
            pass


# ----------------------------------------------------------- engine internals

def test_apply_manual_levels_enforced_next_bar():
    """A manually moved stop lands in the live managed state and the very next
    bar's exit check triggers against it — the engine really enforces the drag."""
    from services.auto_engine import AutoStrategyEngine
    from services.trade_manager import ManagedTrade

    eng = AutoStrategyEngine.__new__(AutoStrategyEngine)  # bare instance — no thread
    import threading
    eng._managed = {}
    eng._targets = {}
    eng._adjust_lock = threading.Lock()

    # a live long: entry 100, stop 90, target 130
    eng._managed["BTCUSDT"] = ManagedTrade(side="long", entry=100.0, stop=90.0, target=130.0, risk=10.0)

    applied = eng.apply_manual_levels("BTCUSDT", stop=99.0)
    mt = eng._managed["BTCUSDT"]
    assert applied["stop"] == 99.0
    assert mt.stop == 99.0 and mt.risk == pytest.approx(1.0)   # risk redefined by new stop
    assert mt.be is False

    # the shared TradeManager now exits at the moved stop on a bar that dips to 98
    from services.trade_manager import TradeManager
    act = TradeManager().on_bar(mt, high=101.0, low=98.0, close=100.0)
    assert act.exit_price == 99.0 and act.exit_reason == "stop"


def test_managed_snapshot_exposes_target():
    from services.auto_engine import AutoStrategyEngine
    from services.trade_manager import ManagedTrade
    import threading
    eng = AutoStrategyEngine.__new__(AutoStrategyEngine)
    eng._managed = {"SOLUSDT": ManagedTrade(side="short", entry=150.0, stop=160.0, target=120.0, risk=10.0)}
    eng._targets = {}
    eng._adjust_lock = threading.Lock()
    snap = eng.managed_snapshot()
    assert snap["SOLUSDT"]["target"] == 120.0 and snap["SOLUSDT"]["side"] == "short"

    # target-only update on a symbol with no managed trade still remembered
    eng.apply_manual_levels("DOGEUSDT", target=0.5)
    assert eng.managed_snapshot()["DOGEUSDT"]["target"] == 0.5
