"""Phase 3 — exchange readiness: symbol filter compliance, idempotent orders,
startup reconciliation, testnet-first factory + readiness checklist."""
import os

import pytest

from bot.brokers.symbol_rules import SymbolRules, from_ccxt
from bot.types import Order, OrderType, Position, Side
from execution.live_readiness import (is_testnet, live_readiness,
                                      make_live_broker, reconcile_startup)


# ─────────────────────────── symbol rules (pure) ───────────────────────────
def test_rules_floor_qty_and_price_to_exchange_steps():
    r = SymbolRules("BTC/USDT", step_size=0.001, tick_size=0.1,
                    min_qty=0.001, min_notional=10.0)
    assert r.round_qty(0.0371294) == 0.037          # floored, never up
    assert r.round_price(64123.457) == 64123.4
    assert r.round_qty(0.0009) == 0.0               # below min lot


def test_rules_reject_below_min_notional():
    r = SymbolRules("XRP/USDT", step_size=1.0, min_qty=1.0, min_notional=10.0)
    qty, why = r.clamp(15.7, price=0.5)             # 15 * 0.5 = 7.5 < 10
    assert qty == 0.0 and "notional" in why
    qty2, why2 = r.clamp(25.0, price=0.5)           # 12.5 >= 10
    assert qty2 == 25.0 and why2 == ""


def test_rules_float_dust_is_handled():
    r = SymbolRules("ETH/USDT", step_size=0.01)
    # 0.29 / 0.01 = 28.999999... naive floor gives 0.28; must give 0.29
    assert r.round_qty(0.29) == 0.29


def test_from_ccxt_parses_both_precision_styles():
    tick_style = {"symbol": "BTC/USDT",
                  "precision": {"amount": 0.001, "price": 0.1},
                  "limits": {"amount": {"min": 0.001}, "cost": {"min": 5}}}
    r = from_ccxt(tick_style)
    assert r.step_size == 0.001 and r.tick_size == 0.1 and r.min_notional == 5
    places_style = {"symbol": "ETH/USDT",
                    "precision": {"amount": 3, "price": 2},
                    "limits": {"amount": {"min": None}, "cost": {}}}
    r2 = from_ccxt(places_style)
    assert r2.step_size == 0.001 and r2.tick_size == 0.01


# ─────────────────────── ccxt broker with a fake exchange ───────────────────────
class _FakeExchange:
    """Just enough of the ccxt surface for submit_order."""
    def __init__(self):
        self.orders = []
        self._i = 0

    def load_markets(self):
        return {}

    def market(self, symbol):
        return {"symbol": symbol,
                "precision": {"amount": 0.001, "price": 0.1},
                "limits": {"amount": {"min": 0.001}, "cost": {"min": 10}}}

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self._i += 1
        self.orders.append({"symbol": symbol, "type": type, "side": side,
                            "amount": amount, "price": price, "params": params or {}})
        return {"id": f"o{self._i}"}

    def cancel_order(self, order_id, symbol=None):
        pass


def _broker_with_fake():
    from bot.brokers.ccxt_broker import CCXTBroker
    b = CCXTBroker.__new__(CCXTBroker)          # skip __init__ (no network)
    b._x = _FakeExchange()
    b._exchange_id = "fake"
    b._quote = "USDT"
    b._brackets = {}
    b._rules = {}
    b._submitted_client_ids = set()
    return b


def test_broker_rounds_all_legs_and_passes_client_id():
    b = _broker_with_fake()
    order = Order(symbol="BTC/USDT", side=Side.BUY, qty=0.12349,
                  order_type=OrderType.LIMIT, limit_price=100.07,
                  stop_loss=95.123, take_profit=110.987, client_id="hub-1")
    entry_id = b.submit_order(order)
    assert entry_id == "o1"
    entry, sl, tp = b._x.orders
    assert entry["amount"] == 0.123 and entry["price"] == 100.0
    assert entry["params"]["clientOrderId"] == "hub-1"
    assert sl["params"]["stopPrice"] == 95.1
    assert tp["params"]["stopPrice"] == 110.9
    assert sl["amount"] == 0.123 and tp["amount"] == 0.123


def test_broker_rejects_below_min_notional():
    b = _broker_with_fake()
    tiny = Order(symbol="BTC/USDT", side=Side.BUY, qty=0.05,
                 order_type=OrderType.LIMIT, limit_price=100.0)  # 5 < 10 min
    with pytest.raises(ValueError, match="notional"):
        b.submit_order(tiny)
    assert b._x.orders == []                     # nothing reached the exchange


def test_broker_deduplicates_client_order_ids():
    b = _broker_with_fake()
    order = Order(symbol="BTC/USDT", side=Side.BUY, qty=0.5,
                  order_type=OrderType.LIMIT, limit_price=100.0, client_id="hub-7")
    first = b.submit_order(order)
    second = b.submit_order(order)               # same client id -> no resubmit
    assert first == "o1" and second == "duplicate:hub-7"
    assert len([o for o in b._x.orders if o["type"] == "limit"]) == 1


# ─────────────────────────── startup reconciliation ───────────────────────────
def test_reconcile_clean_when_views_agree():
    rep = reconcile_startup(
        [{"symbol": "BTCUSDT", "side": "long", "size": 0.5}],
        [Position(symbol="BTC/USDT", qty=0.5, avg_price=100.0)])
    assert rep["clean"] and rep["matched"] == ["BTCUSDT"]


def test_reconcile_reports_every_kind_of_mismatch():
    rep = reconcile_startup(
        [{"symbol": "BTCUSDT", "side": "long", "size": 0.5},
         {"symbol": "ETHUSDT", "side": "short", "size": 2.0}],
        [Position(symbol="BTC/USDT", qty=0.3, avg_price=100.0),
         Position(symbol="SOL/USDT", qty=10.0, avg_price=150.0)])
    assert not rep["clean"]
    assert rep["size_mismatch"][0]["symbol"] == "BTCUSDT"
    assert rep["missing_on_exchange"][0]["symbol"] == "ETHUSDT"
    assert rep["missing_locally"][0]["symbol"] == "SOLUSDT"


# ─────────────────────────── factory + readiness ───────────────────────────
def test_factory_refuses_without_keys(monkeypatch):
    monkeypatch.delenv("HUB_API_KEY", raising=False)
    monkeypatch.delenv("HUB_API_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="HUB_API_KEY"):
        make_live_broker()


def test_testnet_is_the_default(monkeypatch):
    monkeypatch.delenv("HUB_TESTNET", raising=False)
    assert is_testnet() is True
    monkeypatch.setenv("HUB_TESTNET", "0")
    assert is_testnet() is False


def test_readiness_reports_not_ready_without_keys(monkeypatch):
    monkeypatch.delenv("HUB_API_KEY", raising=False)
    monkeypatch.delenv("HUB_API_SECRET", raising=False)
    rep = live_readiness()
    assert rep["ready"] is False
    names = {c["check"]: c for c in rep["checks"]}
    assert names["api keys"]["ok"] is False
    assert names["testnet mode"]["blocking"] is False


def test_readiness_endpoint(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    monkeypatch.delenv("HUB_API_KEY", raising=False)
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    body = client.get("/execution/readiness").json()
    assert body["ready"] is False and body["testnet"] is True
    assert any(c["check"] == "api keys" for c in body["checks"])
