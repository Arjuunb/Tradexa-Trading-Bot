"""Broker Layer (#14): one interface, paper executable, live locked."""
import pytest

from services.broker import BrokerRegistry, PaperBroker, BrokerError


def test_registry_lists_all_venues():
    reg = BrokerRegistry()
    out = reg.list()
    kinds = {b["kind"] for b in out["brokers"]}
    assert {"paper", "binance", "bybit", "ibkr", "alpaca"} <= kinds
    assert out["active"] == "paper" and out["live_locked"] is True


def test_paper_is_connected_and_executable():
    p = PaperBroker()
    assert p.connected() is True
    fill = p.place_order("BTCUSDT", "buy", 0.5)
    assert fill["status"] == "filled" and fill["mode"] == "paper"
    with pytest.raises(BrokerError):
        p.place_order("BTCUSDT", "buy", 0)              # invalid qty


def test_real_venues_not_connected_without_keys(monkeypatch):
    for k in ("BINANCE_API_KEY", "BYBIT_API_KEY", "IBKR_API_KEY", "ALPACA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    reg = BrokerRegistry()
    for kind in ("binance", "bybit", "ibkr", "alpaca"):
        b = reg.get(kind)
        assert b.connected() is False
        with pytest.raises(BrokerError):
            b.place_order("BTCUSDT", "buy", 1)          # not connected -> refuse


def test_connected_venue_still_refuses_live(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "abc")
    b = BrokerRegistry().get("binance")
    assert b.connected() is True
    st = b.status()
    assert st["live_enabled"] is False                  # connected but live still locked
    with pytest.raises(BrokerError):
        b.place_order("BTCUSDT", "buy", 1)


def test_paper_place_fn_is_used():
    calls = []
    reg = BrokerRegistry(paper_place_fn=lambda *a, **k: calls.append(a) or {"ok": True})
    assert reg.active().place_order("ETHUSDT", "sell", 1)["ok"] is True
    assert calls


# ───────────────────────── endpoint ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_brokers_endpoint(client):
    body = client.get("/brokers").json()
    assert body["live_locked"] is True and any(b["kind"] == "paper" for b in body["brokers"])
