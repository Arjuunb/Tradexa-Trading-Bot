"""Tier 3 — portfolio intelligence: allocator (strategy pick + size tilt),
event-risk gate enforcement, shadow A/B mode."""
from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Bar, Signal, SignalType
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.allocator import adaptive_choice, allocation_report, risk_weights
from services.controls import TradingControl
from services.shadow import ShadowRun, live_stats_from_history
from services.signal_pipeline import SignalPipeline

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _bar(close, high=None, low=None, ts=TS):
    return Bar(ts, close, high if high is not None else close,
               low if low is not None else close, close, 1.0)


# ─────────────────────────── allocator ───────────────────────────
def _hist(sym, rrs):
    return [{"symbol": sym, "status": "closed", "rr": r} for r in rrs]


def test_risk_weights_tilt_only_up_on_evidence():
    w = risk_weights(_hist("BTCUSDT", [1.0] * 4), ["BTCUSDT", "ETHUSDT"])
    assert w == {"BTCUSDT": 1.0, "ETHUSDT": 1.0}       # <8 trades: no tilt
    strong = _hist("BTCUSDT", [3.0, -1.0] * 6)          # expectancy 1.0
    assert risk_weights(strong, ["BTCUSDT"])["BTCUSDT"] == 1.25
    losers = _hist("BTCUSDT", [-1.0] * 12)
    assert risk_weights(losers, ["BTCUSDT"])["BTCUSDT"] == 1.0  # penalty is learning's job


def test_adaptive_choice_uses_memory_or_falls_back():
    class _Mem:
        def recommendations(self):
            return {"best_strategy_by_symbol": {
                "BTCUSDT": {"strategy": "Trend Following", "net_r": 8.0},
                "SOLUSDT": {"strategy": "EMA 8/30", "net_r": -2.0}}}
    m = _Mem()
    assert adaptive_choice(m, "BTCUSDT") == "Trend Following"
    assert adaptive_choice(m, "SOLUSDT") == "Decision Brain"   # negative memory: fallback
    assert adaptive_choice(m, "XRPUSDT") == "Decision Brain"   # no sample: fallback


def test_allocation_report_shape():
    rep = allocation_report(_hist("BTCUSDT", [3.0, -1.0] * 6), ["BTCUSDT", "ETHUSDT"])
    assert rep["weights"]["BTCUSDT"] == 1.25
    assert rep["per_symbol"]["ETHUSDT"]["recent_trades"] == 0


# ─────────────────────────── event-risk gate ───────────────────────────
def _pipe(events):
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5,
                          max_total_exposure_pct=1.0,
                          adaptive_risk=False, equity_throttle=False)
    pipe.econ_events = lambda: events
    return pipe, paper


def _open(pipe, aid="e1"):
    return pipe.process({"alert_id": aid, "symbol": "BTCUSDT", "side": "BUY",
                         "entry": 100.0, "stop": 95.0, "confidence": 1.0})


def test_event_blackout_blocks_new_entries_but_not_exits():
    soon = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    pipe, paper = _pipe([{"name": "FOMC", "impact": "high", "time": soon}])
    r = _open(pipe)
    assert not r.accepted and r.stage == "event_risk" and "FOMC" in r.reason
    # exits still work during a blackout
    paper.open(symbol="BTCUSDT", side="BUY", size=1.0, entry=100, stop=95)
    close = pipe.process({"alert_id": "c1", "symbol": "BTCUSDT", "side": "CLOSE",
                          "entry": 101.0})
    assert close.accepted


def test_event_caution_halves_size_and_normal_is_untouched():
    caution = (datetime.now(timezone.utc) + timedelta(minutes=90)).isoformat()
    pipe, _ = _pipe([{"name": "CPI", "impact": "high", "time": caution}])
    r = _open(pipe)
    assert r.accepted
    risk_step = next(s for s in r.steps if s.rule == "risk")
    assert "event 0.50" in risk_step.detail
    far = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    pipe2, _ = _pipe([{"name": "CPI", "impact": "high", "time": far}])
    r2 = _open(pipe2)
    assert r2.accepted
    assert "event" not in next(s for s in r2.steps if s.rule == "risk").detail


# ─────────────────────────── shadow A/B ───────────────────────────
class _StubStrategy:
    def __init__(self, sigs):
        self._s = list(sigs)
        self.bars = []

    def on_bar(self, bar):
        return self._s.pop(0) if self._s else None


def _sig(entry=100.0, stop=95.0, tp=110.0):
    return Signal(timestamp=TS, symbol="BTCUSDT", type=SignalType.LONG,
                  entry=entry, stop_loss=stop, take_profit=tp, reason="x")


def test_shadow_tracks_virtual_trades_without_touching_paper():
    run = ShadowRun("cand", lambda s: _StubStrategy([_sig()]), ["BTCUSDT"])
    run.on_bar("BTCUSDT", _bar(100))                    # opens virtual long
    assert run.stats()["trades"] == 0
    run.on_bar("BTCUSDT", _bar(111, high=112, low=104))  # hits 110 target
    s = run.stats()
    assert s["trades"] == 1 and s["net_r"] > 1.9        # ~2R minus costs


def test_shadow_report_verdicts():
    run = ShadowRun("cand", lambda s: _StubStrategy([]), ["BTCUSDT"])
    rep = run.report({"trades": 0})
    assert rep["verdict"] == "collecting"
    run.trades = [{"r": 1.0}] * 25
    promote = run.report({"trades": 30, "expectancy_r": 0.2})
    assert promote["verdict"] == "promote"
    reject = run.report({"trades": 30, "expectancy_r": 2.0})
    assert reject["verdict"] == "reject"


def test_live_stats_since_filters_by_close_time():
    hist = [{"status": "closed", "rr": 1.0, "closed_at": "2026-01-02T00:00:00"},
            {"status": "closed", "rr": -1.0, "closed_at": "2025-12-01T00:00:00"}]
    all_time = live_stats_from_history(hist)
    recent = live_stats_from_history(hist, since_iso="2026-01-01T00:00:00")
    assert all_time["trades"] == 2 and recent["trades"] == 1


def test_shadow_broken_candidate_never_raises():
    class _Boom:
        def on_bar(self, bar):
            raise RuntimeError("candidate bug")
    run = ShadowRun("boom", lambda s: _Boom(), ["BTCUSDT"])
    run.on_bar("BTCUSDT", _bar(100))                    # must not raise
    assert run.stats()["trades"] == 0


# ─────────────────────────── endpoints ───────────────────────────
def test_tier3_endpoints():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    rep = client.get("/allocation/report").json()
    assert "weights" in rep and "per_symbol" in rep
    assert client.post("/shadow/start").status_code == 401       # secret required
    assert client.get("/shadow/report").json()["active"] in (True, False)
    ok = client.post("/shadow/start", params={"strategy": "Decision Brain"},
                     headers={"X-Webhook-Secret": "dev-webhook-secret"}).json()
    assert ok["started"] is True
    rep2 = client.get("/shadow/report").json()
    assert rep2["active"] is True and rep2["verdict"] == "collecting"
    assert client.post("/shadow/stop", headers={"X-Webhook-Secret": "dev-webhook-secret"}
                       ).json()["stopped"] is True