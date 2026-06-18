"""SMC strategy: signal correctness, the generic built-in simulator, registry
wiring, and the /strategy/builtin/simulate + compare endpoints."""
import pytest

from bot.types import SignalType
from data.market_data import get_bars
from strategies.custom import simulate_strategy
from strategies.smc_strategy import SMCStrategy


def _bars(tf="4h", n=2500):
    return get_bars("BTCUSDT", n=n, timeframe=tf)[0]


def test_no_signal_before_warmup():
    s = SMCStrategy("BTCUSDT")
    out = [s.on_bar(b) for b in _bars()[:50]]
    assert all(x is None for x in out)


def test_signal_brackets_are_consistent():
    s = SMCStrategy("BTCUSDT")
    sig = None
    for b in _bars():
        got = s.on_bar(b)
        if got is not None:
            sig = got
            break
    if sig is not None:  # this data may or may not trigger; validate when it does
        assert 0.0 <= sig.confidence <= 1.0
        if sig.type == SignalType.LONG:
            assert sig.stop_loss < sig.entry < sig.take_profit
        else:
            assert sig.take_profit < sig.entry < sig.stop_loss


def test_simulate_strategy_shape():
    res = simulate_strategy(SMCStrategy("BTCUSDT"), _bars())
    for k in ("total_trades", "win_rate", "profit_factor", "net_r", "max_drawdown_pct",
              "expectancy_r", "sharpe", "equity_curve", "trades", "blocked"):
        assert k in res
    assert res["blocked"] == []
    for t in res["trades"]:
        if t["side"] == "long":
            assert t["stop"] < t["entry"] <= t["target"] or t["target"] < t["entry"]  # long bracket
            assert t["stop"] < t["entry"] < t["target"]
        else:
            assert t["target"] < t["entry"] < t["stop"]
        assert t["exit_reason"] in ("stop", "target")


def test_registry_smc_is_ready():
    from bots.registry import STRATEGIES, build_strategy
    assert STRATEGIES["smc"][2] is True
    strat = build_strategy("smc", "BTCUSDT")
    assert strat.name == "smc"


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_builtin_simulate_endpoint(client):
    body = client.get("/strategy/builtin/simulate", params={"strategy": "smc", "bars": 1500}).json()
    assert body["label"] == "Simulation Result"
    assert "results" in body and "diagnosis" in body["results"]
    assert body["brain"]["quality_filter"] is False


def test_smc_in_compare_endpoint(client):
    body = client.get("/strategy/compare", params={"symbol": "BTCUSDT", "timeframe": "4h",
                                                   "strategy": "smc", "bars": 1500}).json()
    assert all(k in body["metrics"] for k in ("total_trades", "win_rate", "profit_factor"))


def test_smc_listed_in_catalog(client):
    keys = [s["key"] for s in client.get("/strategy/list").json()["strategies"]]
    assert "smc" in keys
