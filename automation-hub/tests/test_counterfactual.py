"""Counterfactual tracker: every veto graded by what it blocked; costing
rules falsified in the learning book; wired through pipeline + engine."""
from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Bar
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.counterfactual import CounterfactualTracker
from services.learning import LearningBook
from services.signal_pipeline import SignalPipeline

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _bar(close, high=None, low=None, ts=TS):
    return Bar(ts, close, high if high is not None else close,
               low if low is not None else close, close, 1.0)


def _veto(t, rule="learning:regime:Ranging", entry=100.0, stop=95.0, target=115.0):
    t.record_veto(symbol="BTCUSDT", side="long", entry=entry, stop=stop,
                  target=target, rule=rule, detail="test")


# ─────────────────────────── tracker mechanics ───────────────────────────
def test_veto_that_would_have_lost_scores_as_saved():
    t = CounterfactualTracker()
    _veto(t)
    assert t.on_bar("BTCUSDT", _bar(96, high=101, low=94)) == 1   # hits the stop
    s = t.rule_scores()["learning:regime:Ranging"]
    assert s["saved_r"] > 0.9                                     # blocked a ~-1R loser
    assert s["vetoed_win_rate"] == 0.0


def test_veto_that_would_have_won_scores_as_cost():
    t = CounterfactualTracker()
    _veto(t)
    t.on_bar("BTCUSDT", _bar(114, high=116, low=101))             # hits 3R target
    s = t.rule_scores()["learning:regime:Ranging"]
    assert s["saved_r"] < -2.9                                    # blocked a ~3R winner


def test_pessimistic_both_touched_counts_the_stop():
    t = CounterfactualTracker()
    _veto(t)
    t.on_bar("BTCUSDT", _bar(100, high=120, low=94))              # touches both
    rec = t.resolved[-1]
    assert rec["exit_reason"] == "stop"


def test_timeout_settles_at_close():
    t = CounterfactualTracker()
    _veto(t)
    for i in range(200):
        assert t.on_bar("BTCUSDT", _bar(101, high=102, low=100.5)) in (0, 1)
    assert t.open == [] and t.resolved[-1]["exit_reason"] == "timeout"


def test_costing_rules_need_sample_and_threshold():
    t = CounterfactualTracker()
    for _ in range(4):                       # 4 blocked winners: still collecting
        _veto(t)
        t.on_bar("BTCUSDT", _bar(114, high=116, low=101))
    assert t.costing_rules() == []
    _veto(t)                                 # 5th resolves -> verdict flips
    t.on_bar("BTCUSDT", _bar(114, high=116, low=101))
    assert t.costing_rules() == ["learning:regime:Ranging"]
    rep = t.report()
    assert rep["total_saved_r"] < -10 and rep["rules"]


def test_persistence_roundtrip(tmp_path):
    p = str(tmp_path / "cf.json")
    t = CounterfactualTracker(p)
    _veto(t)
    t.on_bar("BTCUSDT", _bar(96, high=101, low=94))
    t2 = CounterfactualTracker(p)
    assert t2.rule_scores()["learning:regime:Ranging"]["vetoes_resolved"] == 1


# ─────────────────────── learning falsification ───────────────────────
def _teach_regime_block(book):
    trades = [{"symbol": "BTCUSDT", "status": "closed", "rr": -1.0, "pnl": -10,
               "alert_id": f"a{i}",
               "opened_at": (TS + timedelta(hours=5 * i)).isoformat(),
               "closed_at": (TS + timedelta(hours=5 * i + 2)).isoformat()}
              for i in range(5)]
    trades += [{"symbol": "ETHUSDT", "status": "closed", "rr": 2.0, "pnl": 20,
                "alert_id": f"b{i}",
                "opened_at": (TS + timedelta(hours=5 * i)).isoformat(),
                "closed_at": (TS + timedelta(hours=5 * i + 2)).isoformat()}
               for i in range(5)]
    events = {f"a{i}": {"confidence": 0.9, "regime": "Ranging"} for i in range(5)}
    events |= {f"b{i}": {"confidence": 0.9, "regime": "Trending"} for i in range(5)}
    book.update(list(reversed(trades)), events, now=TS + timedelta(days=1))
    return trades, events


def test_counterfactual_evidence_falsifies_a_learned_rule():
    book = LearningBook()
    trades, events = _teach_regime_block(book)
    assert "regime:Ranging" in book.adjustments
    # the tracker measured the blocked Ranging trades winning -> falsify NOW,
    # even though the loss pattern is still in the trade history
    book.update(list(reversed(trades)), events, now=TS + timedelta(days=2),
                costing_rules=["learning:regime:Ranging"])
    assert "regime:Ranging" not in book.adjustments
    assert any(h["action"] == "falsified" for h in book.history)


def test_gate_exposes_the_rule_key_that_fired():
    book = LearningBook()
    _teach_regime_block(book)
    why = book.gate(symbol="BTCUSDT", regime="Ranging")
    assert why is not None and book.last_gate_key == "regime:Ranging"
    book.gate(symbol="BTCUSDT", regime="Trending")
    assert book.last_gate_key is None


# ─────────────────────── pipeline + engine wiring ───────────────────────
def test_pipeline_records_graded_vetoes_with_attribution():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          adaptive_risk=False, equity_throttle=False)
    pipe.learning = LearningBook()
    _teach_regime_block(pipe.learning)
    pipe.counterfactual = CounterfactualTracker()
    r = pipe.process({"alert_id": "v1", "symbol": "BTCUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0, "target": 115.0,
                      "confidence": 0.9, "regime": "Ranging"})
    assert not r.accepted and r.stage == "learning"
    assert len(pipe.counterfactual.open) == 1
    v = pipe.counterfactual.open[0]
    assert v["rule"] == "learning:regime:Ranging" and v["target"] == 115.0
    # mechanical rejects (invalid stop, dedup, data quality) are NOT graded —
    # there is no judgment to grade
    r2 = pipe.process({"alert_id": "v2", "symbol": "ETHUSDT", "side": "BUY",
                       "entry": 100.0, "stop": None, "confidence": 0.9})
    assert not r2.accepted and len(pipe.counterfactual.open) == 1


def test_engine_resolves_vetoes_and_grades_missed_limits():
    from bot.types import Signal, SignalType
    from services.auto_engine import AutoStrategyEngine
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000)
    eng = AutoStrategyEngine(pipe, paper, led, symbols=["BTCUSDT"], entry_mode="limit")
    eng.counterfactual = CounterfactualTracker()
    pipe.counterfactual = eng.counterfactual

    class _Stub:
        def __init__(self, sigs): self._s = list(sigs)
        def on_bar(self, bar): return self._s.pop(0) if self._s else None

    sig = Signal(timestamp=TS, symbol="BTCUSDT", type=SignalType.LONG,
                 entry=100.0, stop_loss=95.0, take_profit=110.0, reason="x")
    eng._process_bar("BTCUSDT", _bar(100), _Stub([sig]))          # parks limit
    for px in (101, 103, 106):                                    # runs away 3 bars
        eng._process_bar("BTCUSDT", _bar(px, high=px + 1, low=px - 0.5), _Stub([]))
    assert len(eng.counterfactual.open) == 1                      # missed entry tracked
    assert eng.counterfactual.open[0]["rule"] == "limit-ttl"
    eng._process_bar("BTCUSDT", _bar(111, high=112, low=105), _Stub([]))  # target hit
    s = eng.counterfactual.rule_scores()["limit-ttl"]
    assert s["vetoes_resolved"] == 1 and s["saved_r"] < 0         # the miss cost R


# ─────────────────────────── endpoint ───────────────────────────
def test_counterfactual_endpoint():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    body = client.get("/counterfactual/report").json()
    assert "total_saved_r" in body and "rules" in body