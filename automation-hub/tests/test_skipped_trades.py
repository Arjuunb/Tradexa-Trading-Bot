"""Skipped-trade log: every rejected setup is captured with its failed gate,
exact reason, and (when available) the real market snapshot — searchable."""
import pytest

from data.skipped_store import SkippedTradeStore


# ─────────────────────────── store ───────────────────────────
def test_store_records_filters_and_searches():
    st = SkippedTradeStore(":memory:")
    st.record(symbol="BTCUSDT", side="BUY", stage="controls",
              reason="Trading paused — entry blocked", status="rejected")
    st.record(symbol="ETHUSDT", side="SELL", stage="risk_guard",
              reason="Max open positions (3) reached", entry=2000, stop=2100,
              snapshot={"price": 2000, "rsi": 71, "regime": "Ranging"})
    assert len(st.list()) == 2
    # newest first
    assert st.list()[0]["symbol"] == "ETHUSDT"
    # snapshot round-trips
    assert st.list(symbol="ETHUSDT")[0]["snapshot"]["rsi"] == 71
    # filter by failed gate
    assert len(st.list(stage="controls")) == 1
    # free-text search across reason/symbol/stage
    assert len(st.list(q="paused")) == 1
    assert len(st.list(q="max open")) == 1
    # summary counts per gate
    stages = {s["stage"]: s["count"] for s in st.summary()}
    assert stages == {"controls": 1, "risk_guard": 1}


# ─────────────────────────── pipeline integration ───────────────────────────
def _pipe():
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.controls import TradingControl
    from services.signal_pipeline import SignalPipeline
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    ctl = TradingControl()
    pipe = SignalPipeline(led, paper, ctl, equity=10_000, risk_per_trade_pct=0.01,
                          exposure_limit_pct=0.5, max_total_exposure_pct=1.0,
                          adaptive_risk=False, equity_throttle=False)
    pipe.skipped = SkippedTradeStore(":memory:")
    return pipe, ctl


def test_pipeline_records_skip_with_failed_gate_and_snapshot():
    pipe, ctl = _pipe()
    ctl.pause_all()  # force a rejection at the very first gate
    snap = {"price": 100, "rsi": 58, "regime": "Trending"}
    r = pipe.process({"alert_id": "s1", "symbol": "BTCUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0, "target": 115.0,
                      "snapshot": snap, "strategy": "Decision Brain", "timeframe": "4h"})
    assert r.accepted is False
    rows = pipe.skipped.list()
    assert len(rows) == 1
    row = rows[0]
    assert row["stage"] == "controls"                 # the real failed gate
    assert "paused" in row["reason"].lower()
    assert row["snapshot"] == snap                     # real snapshot, not faked
    assert row["strategy"] == "Decision Brain" and row["timeframe"] == "4h"


def test_pipeline_skip_without_snapshot_is_empty_not_faked():
    pipe, ctl = _pipe()
    ctl.stop_all()
    r = pipe.process({"alert_id": "s2", "symbol": "SOLUSDT", "side": "SELL",
                      "entry": 20.0, "stop": 21.0})
    assert r.accepted is False
    assert pipe.skipped.list()[0]["snapshot"] == {}    # honest empty, never invented


# ─────────────────────────── endpoints ───────────────────────────
def test_skipped_endpoints():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    assert "trades" in client.get("/skipped/trades").json()
    assert "stages" in client.get("/skipped/summary").json()
    # search param is accepted
    assert client.get("/skipped/trades?q=controls&limit=10&stage=controls").status_code == 200
