"""Live/backtest parity (TradeBrain quality gate in the live engine) and the
TTL cache that keeps heavy analysis endpoints from starving the engine."""
import time
from datetime import datetime, timezone

import pytest

from bot.types import Bar, Signal, SignalType
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.counterfactual import CounterfactualTracker
from services.signal_pipeline import SignalPipeline
from services.ttl_cache import cached, clear

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ─────────────────── quality-gate parity in the live engine ───────────────────
class _Stub:
    """Strategy stub with a real bar history (the gate needs 60+ bars)."""
    def __init__(self, sigs, bars=None):
        self._s = list(sigs)
        self.bars = list(bars or [])

    def on_bar(self, bar):
        self.bars.append(bar)
        return self._s.pop(0) if self._s else None


def _engine(min_score=60):
    from services.auto_engine import AutoStrategyEngine
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          exposure_limit_pct=0.5, max_total_exposure_pct=1.0)
    eng = AutoStrategyEngine(pipe, paper, led, symbols=["BTCUSDT"],
                             entry_mode="market")
    eng.min_quality_score = min_score
    return eng, paper, led


def _history(n=90):
    from bot.data.synthetic import generate_bars
    return generate_bars(n=n, timeframe="1h", seed=7)


def _sig(entry=100.0, stop=95.0, tp=102.0):
    return Signal(timestamp=TS, symbol="BTCUSDT", type=SignalType.LONG,
                  entry=entry, stop_loss=stop, take_profit=tp, reason="x")


def test_quality_gate_blocks_the_same_setups_backtests_block():
    # rr 0.4 (tp 102 vs stop 95) is a HARD block for TradeBrain (min_rr 1.0) —
    # every simulator rejects it; the live engine must too
    eng, paper, led = _engine()
    eng.counterfactual = CounterfactualTracker()
    stub = _Stub([_sig(tp=102.0)], bars=_history())
    eng._process_bar("BTCUSDT", _history(91)[-1], stub)
    assert paper.positions() == []                       # no trade opened
    assert eng.stats["rejections"] == 1
    assert any(l["stage"] == "brain" for l in led.get_logs())
    # the veto is graded like every other gate
    assert eng.counterfactual.open[0]["rule"] == "quality-score"


def test_quality_gate_disabled_or_warming_up_lets_signals_through():
    # min_quality_score=0 disables the gate entirely
    eng, paper, _ = _engine(min_score=0)
    stub = _Stub([_sig(tp=102.0)], bars=_history())
    eng._process_bar("BTCUSDT", _history(91)[-1], stub)
    assert paper.open_position("BTCUSDT") is not None
    # under 60 bars of history the gate stands down (warmup, fail-open)
    eng2, paper2, _ = _engine(min_score=60)
    stub2 = _Stub([_sig(tp=102.0)], bars=_history(10))
    eng2._process_bar("BTCUSDT", _history(11)[-1], stub2)
    assert paper2.open_position("BTCUSDT") is not None


def test_min_quality_score_is_runtime_settable():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    r = client.post("/settings", json={"min_quality_score": 70},
                    headers={"X-Webhook-Secret": "dev-webhook-secret"})
    assert r.status_code == 200
    assert webhook_api.engine.min_quality_score == 70
    assert client.get("/settings").json()["editable"]["min_quality_score"] == 70
    assert client.post("/settings", json={"min_quality_score": 150},
                       headers={"X-Webhook-Secret": "dev-webhook-secret"}).status_code == 400
    client.post("/settings", json={"min_quality_score": 60},
                headers={"X-Webhook-Secret": "dev-webhook-secret"})


# ─────────────────────────── ttl cache ───────────────────────────
def test_cached_serves_within_ttl_and_recomputes_after():
    clear()
    calls = []

    def compute():
        calls.append(1)
        return {"available": True, "n": len(calls)}

    a = cached("k1", ttl=60, fn=compute)
    b = cached("k1", ttl=60, fn=compute)
    assert a == b and len(calls) == 1                    # served from cache
    c = cached("k2", ttl=60, fn=compute)
    assert c["n"] == 2                                   # different key computes


def test_cached_never_caches_failures():
    clear()
    calls = []

    def flaky():
        calls.append(1)
        return {"available": False, "detail": "no data"}

    cached("f1", ttl=60, fn=flaky)
    cached("f1", ttl=60, fn=flaky)
    assert len(calls) == 2                               # failures retry immediately


def test_league_endpoint_is_cached(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    import services.strategy_league as sl
    clear()
    calls = []
    monkeypatch.setattr(sl, "league",
                        lambda **kw: (calls.append(1) or {"available": True, "table": []}))
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    client.get("/strategy/league", params={"symbols": "BTCUSDT", "bars": 800})
    client.get("/strategy/league", params={"symbols": "BTCUSDT", "bars": 800})
    assert len(calls) == 1                               # second hit from cache