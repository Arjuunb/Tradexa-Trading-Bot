"""Order fill models (#9): perfect default + realistic friction in the paper engine."""
import pytest

from services.fill_model import PerfectFill, RealisticFill
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine


def test_perfect_fill_is_a_noop():
    f = PerfectFill().apply("buy", 100.0, 2.0)
    assert f["price"] == 100.0 and f["size"] == 2.0 and f["rejected"] is False


def test_realistic_fill_moves_price_against_you():
    m = RealisticFill(spread_pct=0.001, slippage_pct=0.0005, latency_pct=0.0)
    buy = m.apply("buy", 100.0, 1.0)
    sell = m.apply("sell", 100.0, 1.0)
    assert buy["price"] > 100.0          # pay up to buy
    assert sell["price"] < 100.0         # sell into the bid
    assert buy["cost_pct"] > 0


def test_realistic_partial_and_reject():
    part = RealisticFill(partial_fill_prob=1.0, partial_fraction=0.5)
    assert part.apply("buy", 100, 2.0)["size"] == 1.0          # partial
    rej = RealisticFill(reject_prob=1.0)
    assert rej.apply("buy", 100, 1.0)["rejected"] is True
    # exits never reject/partial
    assert rej.apply("sell", 100, 1.0, allow_reject=False)["rejected"] is False


def _engine(model=None):
    return PaperExecutionEngine(SqliteLedger(":memory:"), 10_000.0, fill_model=model)


def test_paper_engine_perfect_by_default_unchanged():
    eng = _engine()
    r = eng.open(symbol="BTCUSDT", side="BUY", size=1.0, entry=100.0, stop=95.0)
    assert r.action == "opened" and r.price == 100.0 and r.size == 1.0


def test_paper_engine_realistic_fills_cost_money():
    eng = _engine(RealisticFill(spread_pct=0.002, slippage_pct=0.0, latency_pct=0.0))
    r = eng.open(symbol="BTCUSDT", side="BUY", size=1.0, entry=100.0, stop=95.0)
    assert r.price > 100.0                                     # filled worse than requested
    c = eng.close(symbol="BTCUSDT", exit_price=100.0)
    assert c.action == "closed" and c.price < 100.0           # exit also crosses the spread
    assert c.pnl < 0                                          # round-trip friction -> a loss at flat price


def test_paper_engine_rejection():
    eng = _engine(RealisticFill(reject_prob=1.0))
    r = eng.open(symbol="ETHUSDT", side="SELL", size=1.0, entry=100.0, stop=105.0)
    assert r.action == "rejected" and r.size == 0.0
    assert eng.open_position("ETHUSDT") is None                # nothing opened


# ───────────────────────── endpoint ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"


def test_fill_model_endpoint(client):
    import webhook_api
    assert client.get("/execution/fill-model").json()["model"] in ("perfect", "realistic")
    assert client.post("/execution/fill-model", json={"model": "realistic"}).status_code == 401
    st = client.post("/execution/fill-model", json={"model": "realistic", "spread_pct": 0.001},
                     headers={"X-Webhook-Secret": SECRET}).json()
    assert st["model"] == "realistic"
    # reset to perfect so other tests using the shared engine are unaffected
    client.post("/execution/fill-model", json={"model": "perfect"}, headers={"X-Webhook-Secret": SECRET})
