"""Kyros Phase 1 — webhook -> dedup -> risk -> paper execution -> ledger.

Covers the data-access layer (SqliteLedger), the paper engine (open/close/PnL),
duplicate protection, emergency controls, the signal pipeline decisions, and the
HTTP surface (secret gating + routes) via TestClient.

SQLite ledgers use ``:memory:`` so tests touch no files and stay isolated.
"""
import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.dedup import DuplicateGuard
from services.signal_pipeline import SignalPipeline


@pytest.fixture()
def ledger():
    return SqliteLedger(":memory:")


@pytest.fixture()
def paper(ledger):
    return PaperExecutionEngine(ledger, starting_balance=10_000)


@pytest.fixture()
def pipeline(ledger, paper):
    return SignalPipeline(
        ledger, paper, TradingControl(),
        equity=10_000, risk_per_trade_pct=0.01,
        exposure_limit_pct=0.05, dedup_window_s=300,
    )


def _alert(alert_id="a1", symbol="BTCUSDT", side="BUY", entry=67_500, stop=66_800):
    return {"alert_id": alert_id, "symbol": symbol, "side": side,
            "entry": entry, "stop": stop, "timestamp": "2026-06-16T00:00:00Z"}


# ----------------------------------------------------------------- ledger
def test_ledger_creates_all_tables(ledger):
    tables = {r["name"] for r in ledger._c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"webhook_events", "positions", "paper_trades", "bot_logs", "alerts"} <= tables


def test_ledger_webhook_seen_window_and_status(ledger):
    ledger.insert_webhook_event(alert_id="dup", symbol="BTCUSDT", side="BUY",
                                entry=1, stop=0, payload={}, status="accepted")
    assert ledger.webhook_seen("dup", "2000-01-01T00:00:00+00:00") is True
    # rejected events do not count as "seen" (so a real signal can retry)
    ledger.insert_webhook_event(alert_id="rej", symbol="BTCUSDT", side="BUY",
                                entry=1, stop=0, payload={}, status="rejected")
    assert ledger.webhook_seen("rej", "2000-01-01T00:00:00+00:00") is False
    # future window excludes older events
    assert ledger.webhook_seen("dup", "2999-01-01T00:00:00+00:00") is False


def test_ledger_logs_and_alerts(ledger):
    ledger.log(level="info", stage="test", message="hello", symbol="BTCUSDT")
    ledger.add_alert(severity="warning", category="risk", title="t", detail="d")
    assert ledger.get_logs()[0]["message"] == "hello"
    assert ledger.get_alerts()[0]["title"] == "t"


# ----------------------------------------------------------------- paper engine
def test_paper_long_pnl_and_balance(paper):
    paper.open(symbol="BTCUSDT", side="BUY", size=2, entry=100, stop=90)
    assert len(paper.positions()) == 1
    fill = paper.close(symbol="BTCUSDT", exit_price=110)
    assert fill.pnl == pytest.approx(20.0)        # (110-100)*2
    assert paper.realized_pnl() == pytest.approx(20.0)
    assert paper.balance() == pytest.approx(10_020.0)
    assert paper.positions() == []
    assert len(paper.history()) == 1


def test_paper_short_pnl(paper):
    paper.open(symbol="ETHUSDT", side="SELL", size=3, entry=100, stop=110)
    fill = paper.close(symbol="ETHUSDT", exit_price=90)
    assert fill.pnl == pytest.approx(30.0)        # (100-90)*3 short


def test_paper_unrealized_and_equity(paper):
    paper.open(symbol="BTCUSDT", side="BUY", size=1, entry=100, stop=90)
    assert paper.unrealized_pnl({"BTCUSDT": 120}) == pytest.approx(20.0)
    assert paper.equity({"BTCUSDT": 120}) == pytest.approx(10_020.0)


def test_paper_close_with_no_position_is_noop(paper):
    fill = paper.close(symbol="NOPE", exit_price=100)
    assert fill.action == "noop"


def test_paper_rr_computation(paper):
    paper.open(symbol="BTCUSDT", side="BUY", size=1, entry=100, stop=90)
    fill = paper.close(symbol="BTCUSDT", exit_price=120)  # +20 move / 10 risk = 2R
    trade = paper.history()[0]
    assert trade["rr"] == pytest.approx(2.0)
    assert fill.pnl == pytest.approx(20.0)


# ----------------------------------------------------------------- dedup
def test_dedup_detects_repeat(ledger):
    guard = DuplicateGuard(ledger, window_seconds=300)
    assert guard.is_duplicate("x") is False
    ledger.insert_webhook_event(alert_id="x", symbol="BTCUSDT", side="BUY",
                                entry=1, stop=0, payload={}, status="accepted")
    assert guard.is_duplicate("x") is True
    assert guard.is_duplicate("") is False        # empty id never duplicate


# ----------------------------------------------------------------- controls
def test_controls_state_transitions():
    c = TradingControl()
    assert c.trading_allowed() and c.state == "Active"
    c.pause_all()
    assert not c.trading_allowed() and c.state == "Paused"
    c.resume()
    assert c.trading_allowed()
    c.stop_all()
    assert not c.trading_allowed() and c.state == "Stopped"
    c.resume()
    assert c.trading_allowed()


# ----------------------------------------------------------------- pipeline
def test_pipeline_opens_paper_trade(pipeline, paper):
    res = pipeline.process(_alert())
    assert res.accepted and res.stage == "execution"
    assert len(paper.positions()) == 1
    assert res.fill["action"] == "opened"


def test_pipeline_rejects_duplicate(pipeline):
    assert pipeline.process(_alert(alert_id="dup")).accepted
    res = pipeline.process(_alert(alert_id="dup"))
    assert not res.accepted and res.stage == "dedup"


def test_pipeline_rejects_when_paused(pipeline):
    pipeline.controls.pause_all()
    res = pipeline.process(_alert())
    assert not res.accepted and res.stage == "controls"


def test_pipeline_rejects_invalid_stop(pipeline):
    res = pipeline.process(_alert(stop=None))
    assert not res.accepted and res.stage == "risk"
    res2 = pipeline.process(_alert(alert_id="a2", stop=67_500))  # stop == entry
    assert not res2.accepted and res2.stage == "risk"


def test_pipeline_no_pyramiding(pipeline):
    assert pipeline.process(_alert(alert_id="a1")).accepted
    res = pipeline.process(_alert(alert_id="a2"))  # same symbol, already open
    assert not res.accepted and res.stage == "execution"
    assert "pyramiding" in res.reason


def test_pipeline_close_signal(pipeline, paper):
    pipeline.process(_alert(alert_id="open"))
    res = pipeline.process(_alert(alert_id="close", side="CLOSE", entry=68_000))
    assert res.accepted and res.reason == "position closed"
    assert paper.positions() == []
    assert len(paper.history()) == 1


def test_pipeline_opposite_side_closes(pipeline, paper):
    pipeline.process(_alert(alert_id="long"))
    res = pipeline.process(_alert(alert_id="flip", side="SELL", entry=68_000))
    assert res.accepted and res.reason == "position closed"
    assert paper.positions() == []


def test_pipeline_exposure_cap(ledger, paper):
    # Tiny stop distance -> huge risk-based size, must be capped by exposure limit.
    pipe = SignalPipeline(ledger, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.05)
    res = pipe.process(_alert(entry=100, stop=99.9))
    assert res.accepted
    pos = paper.positions()[0]
    # exposure cap = 5% * 10_000 / 100 = 5 units max
    assert pos["size"] == pytest.approx(5.0)
    assert any(s.rule == "exposure" for s in res.steps)


def test_pipeline_records_webhook_event_and_log(pipeline, ledger):
    pipeline.process(_alert())
    events = ledger._c.execute("SELECT * FROM webhook_events").fetchall()
    assert len(events) == 1 and events[0]["status"] == "accepted"
    assert ledger.get_logs()  # an execution log was written


# ----------------------------------------------------------------- HTTP surface
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import webhook_api

    # Fresh in-memory ledger + paper + pipeline per test.
    led = SqliteLedger(":memory:")
    webhook_api.ledger = led
    webhook_api.controls = TradingControl()
    webhook_api.paper = PaperExecutionEngine(led, 10_000)
    webhook_api.pipeline = SignalPipeline(
        led, webhook_api.paper, webhook_api.controls,
        equity=10_000, risk_per_trade_pct=0.01, exposure_limit_pct=0.05)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"


def test_webhook_rejects_missing_secret(client):
    r = client.post("/webhook/tradingview", json=_alert())
    assert r.status_code == 401


def test_webhook_rejects_wrong_secret(client):
    r = client.post("/webhook/tradingview", json=_alert(),
                    headers={"X-Webhook-Secret": "nope"})
    assert r.status_code == 401


def test_webhook_accepts_valid_signal(client):
    r = client.post("/webhook/tradingview", json=_alert(),
                    headers={"X-Webhook-Secret": SECRET})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["accepted"] is True
    # account endpoint reflects the open position
    acct = client.get("/paper/account").json()
    assert acct["open_positions"] == 1


def test_webhook_invalid_payload_is_422(client):
    r = client.post("/webhook/tradingview", json={"symbol": "BTCUSDT"},
                    headers={"X-Webhook-Secret": SECRET})
    assert r.status_code == 422


def test_controls_endpoints_gated_and_work(client):
    assert client.post("/controls/pause-all").status_code == 401
    r = client.post("/controls/pause-all", headers={"X-Webhook-Secret": SECRET})
    assert r.json()["state"] == "Paused"
    # paused -> webhook rejects the entry
    res = client.post("/webhook/tradingview", json=_alert(),
                      headers={"X-Webhook-Secret": SECRET}).json()
    assert res["accepted"] is False and res["stage"] == "controls"
    client.post("/controls/resume", headers={"X-Webhook-Secret": SECRET})
    assert client.get("/controls/state").json()["state"] == "Active"


def test_ledger_read_endpoints(client):
    client.post("/webhook/tradingview", json=_alert(),
                headers={"X-Webhook-Secret": SECRET})
    assert client.get("/paper/positions").json()
    assert isinstance(client.get("/paper/trades").json(), list)
    assert client.get("/ledger/logs").json()
    assert isinstance(client.get("/ledger/alerts").json(), list)
