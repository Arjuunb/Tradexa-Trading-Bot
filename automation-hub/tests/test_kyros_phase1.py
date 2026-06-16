"""Kyros Phase 1 — webhook -> dedup -> risk -> paper execution -> ledger.

Covers the data-access layer (SqliteLedger), the paper engine (open/close/PnL),
duplicate protection, emergency controls, the signal pipeline decisions, and the
HTTP surface (secret gating + routes) via TestClient.

SQLite ledgers use ``:memory:`` so tests touch no files and stay isolated.
"""
import time

import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.auto_engine import AutoStrategyEngine
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
    webhook_api.engine = AutoStrategyEngine(
        webhook_api.pipeline, webhook_api.paper, led, symbols=["BTCUSDT"], interval=0.01)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(webhook_api.router)
    yield TestClient(app)
    webhook_api.engine.stop()


SECRET = "dev-webhook-secret"


def test_engine_endpoints_gated_and_status(client):
    assert client.post("/engine/start").status_code == 401      # secret required
    r = client.post("/engine/start", headers={"X-Webhook-Secret": SECRET})
    assert r.status_code == 200 and r.json()["status"]["running"] is True
    assert client.get("/engine/status").json()["running"] is True
    stopped = client.post("/engine/stop", headers={"X-Webhook-Secret": SECRET})
    assert stopped.json()["stopped"] is True


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


def test_live_summary_endpoints(client):
    # open then close a trade so there is realized P&L + history
    client.post("/webhook/tradingview", json=_alert(alert_id="o"),
                headers={"X-Webhook-Secret": SECRET})
    client.post("/webhook/tradingview", json=_alert(alert_id="c", side="CLOSE", entry=68000),
                headers={"X-Webhook-Secret": SECRET})

    risk = client.get("/risk/summary").json()
    assert "exposure_pct" in risk and risk["exposure_limit_pct"] == 0.05
    assert "trading_state" in risk

    eq = client.get("/paper/equity-curve").json()
    assert eq["starting_balance"] == 10_000 and len(eq["points"]) >= 2

    bots = client.get("/bots/live").json()
    assert isinstance(bots, list) and bots and bots[0]["strategy"]
    assert "win_rate" in bots[0] and "realized_pnl" in bots[0]


# ----------------------------------------------------- autonomous engine
from bot.types import Bar, Signal, SignalType  # noqa: E402
from datetime import datetime, timezone  # noqa: E402


class _StubStrategy:
    """Emits a queued signal per bar (None when empty)."""
    def __init__(self, signals):
        self._signals = list(signals)
        self.bars = []

    def on_bar(self, bar):
        self.bars.append(bar)
        return self._signals.pop(0) if self._signals else None


def _bar(close, high=None, low=None):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Bar(ts, close, high if high is not None else close,
               low if low is not None else close, close, 1.0)


def _engine(ledger, paper, **kw):
    pipe = SignalPipeline(ledger, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.05)
    return AutoStrategyEngine(pipe, paper, ledger, symbols=["BTCUSDT"], **kw)


def test_auto_engine_opens_then_stops_out(ledger, paper):
    eng = _engine(ledger, paper)
    sig = Signal(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), symbol="BTCUSDT",
                 type=SignalType.LONG, entry=100, stop_loss=95, take_profit=110, reason="x")
    eng._process_bar("BTCUSDT", _bar(100), _StubStrategy([sig]))
    assert len(paper.positions()) == 1
    # next bar dips through the stop -> closed at the stop price
    eng._process_bar("BTCUSDT", _bar(96, high=101, low=94), _StubStrategy([]))
    assert paper.positions() == []
    hist = paper.history()
    assert len(hist) == 1 and hist[0]["exit"] == 95
    assert hist[0]["pnl"] < 0


def test_auto_engine_take_profit_exit(ledger, paper):
    eng = _engine(ledger, paper)
    sig = Signal(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), symbol="BTCUSDT",
                 type=SignalType.LONG, entry=100, stop_loss=95, take_profit=110, reason="x")
    eng._process_bar("BTCUSDT", _bar(100), _StubStrategy([sig]))
    eng._process_bar("BTCUSDT", _bar(109, high=112, low=108), _StubStrategy([]))  # hits 110
    hist = paper.history()
    assert len(hist) == 1 and hist[0]["exit"] == 110 and hist[0]["pnl"] > 0


def test_auto_engine_lifecycle(ledger, paper):
    eng = _engine(ledger, paper, interval=0.01)
    assert eng.status()["running"] is False
    assert eng.start() is True
    assert eng.start() is False          # already running
    assert eng.stop() is True
    assert eng.stop() is False


def test_auto_engine_produces_real_trades(ledger, paper):
    eng = _engine(ledger, paper, interval=0.0, warmup=150, live_bars=120)
    eng.start()
    deadline = time.time() + 4
    while time.time() < deadline and eng.stats["bars"] < 200:
        time.sleep(0.02)
    eng.stop()
    assert eng.stats["bars"] > 0
    assert eng.stats["signals"] > 0
    # real strategy signals became real paper trades + decision logs
    assert ledger.get_logs(500)
    assert paper.history() or paper.positions()


# ----------------------------------------------------- decision brain
from strategies.brain_strategy import DecisionBrain  # noqa: E402


def _trend_bars(n, start=100.0, step=0.6, noise=0.05):
    """Steadily rising bars (clear uptrend) with tiny noise."""
    bars = []
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        price += step
        hi = price + noise
        lo = price - noise
        bars.append(Bar(ts, price - step, hi, lo, price, 1.0))
    return bars


def test_brain_goes_long_in_uptrend():
    brain = DecisionBrain("BTCUSDT")
    sig = None
    for b in _trend_bars(120):
        sig = brain.on_bar(b) or sig
    assert sig is not None
    assert sig.type == SignalType.LONG
    assert 0.0 < sig.confidence <= 1.0
    assert "conviction" in sig.reason and "RSI" in sig.reason


def test_brain_holds_on_flat_market():
    brain = DecisionBrain("BTCUSDT")
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    decisions = [brain.on_bar(Bar(ts, 100, 100.1, 99.9, 100.0, 1.0)) for _ in range(120)]
    # a flat market gives no conviction -> the brain declines to trade
    assert all(d is None for d in decisions)


def test_brain_confidence_scales_size(ledger, paper):
    pipe = SignalPipeline(ledger, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.02, exposure_limit_pct=0.5)
    hi = pipe.process({"alert_id": "hi", "symbol": "BTCUSDT", "side": "BUY",
                       "entry": 100, "stop": 50, "confidence": 1.0})
    lo = pipe.process({"alert_id": "lo", "symbol": "ETHUSDT", "side": "BUY",
                       "entry": 100, "stop": 50, "confidence": 0.4})
    assert hi.accepted and lo.accepted
    hi_size = next(p["size"] for p in paper.positions() if p["symbol"] == "BTCUSDT")
    lo_size = next(p["size"] for p in paper.positions() if p["symbol"] == "ETHUSDT")
    assert hi_size > lo_size      # higher conviction -> bigger position


# ----------------------------------------------------- dashboard wiring (UI)
@pytest.fixture()
def hub_client():
    """Logged-in dashboard client with the Kyros singletons swapped for an
    isolated in-memory ledger/paper/controls so UI pages reflect live state."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    import webhook_api
    from bots.manager import BotManager
    from dashboard.stream import HubEventHub

    hub_app.manager = BotManager()
    hub_app.hub_events = HubEventHub()
    hub_app._sessions.clear()

    led = SqliteLedger(":memory:")
    webhook_api.ledger = led
    webhook_api.controls = TradingControl()
    webhook_api.paper = PaperExecutionEngine(led, 10_000)
    webhook_api.pipeline = SignalPipeline(
        led, webhook_api.paper, webhook_api.controls,
        equity=10_000, risk_per_trade_pct=0.01, exposure_limit_pct=0.05)
    webhook_api.engine = AutoStrategyEngine(
        webhook_api.pipeline, webhook_api.paper, led, symbols=["BTCUSDT"], interval=0.01)

    c = TestClient(hub_app.app, follow_redirects=False)
    r = c.post("/login", data={"username": "admin", "password": "admin"})
    assert r.status_code == 303
    yield c
    webhook_api.engine.stop()


def test_paper_page_reflects_open_position(hub_client):
    hub_client.post("/webhook/tradingview", json=_alert(),
                    headers={"X-Webhook-Secret": SECRET})
    body = hub_client.get("/paper-trading").text
    assert "BTCUSDT" in body and "Open Positions" in body
    assert "Emergency Controls" in body


def test_ui_emergency_controls_block_entries(hub_client):
    r = hub_client.post("/paper-trading/pause")
    assert r.status_code == 303
    assert webhook_api_state(hub_client) == "Paused"
    # paused -> a new webhook entry is rejected
    res = hub_client.post("/webhook/tradingview", json=_alert(),
                          headers={"X-Webhook-Secret": SECRET}).json()
    assert res["accepted"] is False and res["stage"] == "controls"
    hub_client.post("/paper-trading/resume")
    assert webhook_api_state(hub_client) == "Active"


def webhook_api_state(hub_client) -> str:
    return hub_client.get("/controls/state").json()["state"]


def test_alerts_and_logs_pages(hub_client):
    hub_client.post("/webhook/tradingview", json=_alert(),
                    headers={"X-Webhook-Secret": SECRET})
    alerts = hub_client.get("/alerts").text
    assert "Paper trade opened" in alerts
    logs = hub_client.get("/logs").text
    assert "Decision Log" in logs and "execution" in logs
