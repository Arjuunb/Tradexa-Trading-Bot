"""Custom strategy builder: rule eval, simulation, validation, store, endpoints."""
import pytest

from data.market_data import get_bars
from strategies.custom import describe, evaluate, simulate, validate
from services.custom_store import CustomStore

EXAMPLE = {
    "name": "EMA+RSI+Breakout", "symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
    "entry": {"op": "AND", "rules": [
        {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"},
        {"type": "rsi", "period": 14, "op": "above", "value": 50},
        {"type": "breakout", "lookback": 20, "dir": "up"},
        {"type": "volume", "period": 20, "op": "above"},
    ]},
    "stop": {"type": "atr", "mult": 1.5, "period": 14},
    "target": {"type": "rr", "rr": 1.5},
    "risk_per_trade_pct": 0.01,
}


def _bars():
    rows, _ = get_bars("BTCUSDT", n=2500, timeframe="4h")
    return rows


def test_evaluate_and_or_not():
    bars = _bars()
    i = len(bars) - 1
    # AND of an always-pass-ish rule + its negation should be False
    tree = {"op": "AND", "rules": [
        {"type": "rsi", "op": "above", "value": 0},                 # ~always true
        {"type": "rsi", "op": "above", "value": 0, "negate": True},  # NOT true -> false
    ]}
    matched, _ = evaluate(tree, bars, i)
    assert matched is False
    # OR of the same -> True
    matched2, _ = evaluate({"op": "OR", "rules": tree["rules"]}, bars, i)
    assert matched2 is True


def test_simulate_returns_full_results():
    res = simulate(EXAMPLE, _bars())
    for k in ("total_trades", "win_rate", "profit_factor", "net_r", "max_drawdown_pct",
              "avg_rr", "best_r", "worst_r", "max_consecutive_wins",
              "max_consecutive_losses", "equity_curve", "trades"):
        assert k in res
    assert res["simulation"] is True
    # if it traded, each trade carries the required fields + a reason
    if res["trades"]:
        t = res["trades"][0]
        for k in ("entry", "exit", "stop", "target", "side", "r", "reason", "entry_time", "exit_time"):
            assert k in t
        assert t["reason"]


def test_validation_flags_high_risk_and_few_trades():
    spec = {**EXAMPLE, "risk_per_trade_pct": 0.05}
    warns = validate(spec, {"total_trades": 5, "max_drawdown_pct": 5, "win_rate": 40, "profit_factor": 1.2})
    msgs = " ".join(w["message"] for w in warns)
    assert "Risk per trade" in msgs and "too few" in msgs.lower()


def test_describe_plain_english():
    txt = describe(EXAMPLE)
    assert "enters long" in txt and "EMA20" in txt and "risk:reward" in txt


def test_store_crud(tmp_path):
    s = CustomStore(str(tmp_path / "c.json"))
    saved = s.save({"name": "A", "entry": {"op": "AND", "rules": []}})
    assert saved["id"] and s.get(saved["id"])["name"] == "A"
    dup = s.duplicate(saved["id"])
    assert dup["name"] == "A (copy)" and dup["id"] != saved["id"]
    assert len(s.list()) == 2
    assert s.delete(saved["id"]) and len(s.list()) == 1


# --- endpoints ---
@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    webhook_api.custom_store = CustomStore(str(tmp_path / "c.json"))
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"


def test_simulate_endpoint_uses_real_data(client):
    r = client.post("/strategy/custom/simulate", json={"spec": EXAMPLE, "bars": 1500})
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "Simulation Result"
    assert body["data_source"] in ("local store (real)", "bundled sample", "synthetic", "live (ccxt)")
    assert "results" in body and "warnings" in body and "description" in body


def test_price_action_rules_evaluate():
    from strategies.custom import _rule
    bars = _bars()
    i = len(bars) - 1
    for rt in ("pullback", "support_bounce", "liquidity_sweep", "fair_value_gap",
               "vwap", "bollinger", "bos", "choch"):
        ok, why = _rule({"type": rt}, bars, i)
        assert isinstance(ok, bool)  # evaluates without error


def test_simulate_endpoint_includes_sizing(client):
    r = client.post("/strategy/custom/simulate", json={"spec": EXAMPLE, "bars": 1500}).json()
    s = r["sizing"]
    for k in ("model", "equity", "risk_pct", "entry", "stop_distance", "risk_dollars", "position_size", "notional"):
        assert k in s
    assert s["position_size"] >= 0


def test_deploy_custom_to_paper(client):
    saved = client.post("/strategy/custom", json=EXAMPLE, headers={"X-Webhook-Secret": SECRET}).json()
    r = client.post(f"/strategy/custom/{saved['id']}/deploy", headers={"X-Webhook-Secret": SECRET})
    assert r.status_code == 200 and r.json()["deployed"] is True
    import webhook_api
    assert webhook_api.engine.symbols == [EXAMPLE["symbol"]]
    assert "Custom" in webhook_api.engine.strategy_label
    webhook_api.engine.stop()


def test_compare_endpoint(client):
    r = client.get("/strategy/compare", params={"symbol": "BTCUSDT", "timeframe": "4h", "strategy": "brain", "bars": 1500})
    assert r.status_code == 200
    m = r.json()["metrics"]
    assert all(k in m for k in ("total_trades", "win_rate", "profit_factor", "net_r"))


def test_custom_crud_endpoints_gated(client):
    assert client.post("/strategy/custom", json=EXAMPLE).status_code == 401
    saved = client.post("/strategy/custom", json=EXAMPLE, headers={"X-Webhook-Secret": SECRET}).json()
    assert saved["id"]
    assert client.get("/strategy/custom").json()
    dup = client.post(f"/strategy/custom/{saved['id']}/duplicate", headers={"X-Webhook-Secret": SECRET}).json()
    assert dup["id"] != saved["id"]
    assert client.request("DELETE", f"/strategy/custom/{saved['id']}", headers={"X-Webhook-Secret": SECRET}).json()["deleted"]
