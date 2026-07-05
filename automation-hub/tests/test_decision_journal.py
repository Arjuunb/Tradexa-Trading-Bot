"""Decision Journal: real decision capture at entry, review + evolution at
close, honest 'Not checked', and the early-signal/evidence staging."""
import pytest

from data.journal_store import EVIDENCE_MIN, JournalStore
from services.decision_journal import (DecisionJournal, build_evolution,
                                       build_review, grade_trade, map_checklist)


# ─────────────────────────── pure builders ───────────────────────────
def test_map_checklist_splits_and_marks_not_checked():
    steps = [{"rule": "daily_loss", "passed": True, "detail": "today +0"},
             {"rule": "exposure", "passed": True, "detail": "within 5%"}]
    brain = [{"name": "EMA trend (fast vs slow)", "status": "Passed", "detail": "EMA12>EMA26"}]
    cl = map_checklist(steps, brain)
    names = {c["name"]: c["status"] for c in cl["entry_reads"]}
    # brain reads preserved; SMC reads the brain does not compute -> Not checked
    assert names["EMA trend (fast vs slow)"] == "Passed"
    assert names["Fair-value gap (FVG)"] == "Not checked"
    gates = {g["rule"]: g["status"] for g in cl["risk_gates"]}
    assert gates["daily_loss"] == "Passed" and gates["exposure"] == "Passed"


def test_grade_trade():
    assert grade_trade(result="win", actual_rr=2.5, planned_rr=3.0,
                       followed_strategy=True, risk_ok=True) == "A"
    assert grade_trade(result="win", actual_rr=0.5, planned_rr=3.0,
                       followed_strategy=True, risk_ok=True) == "B"
    assert grade_trade(result="loss", actual_rr=-0.5, planned_rr=3.0,
                       followed_strategy=True, risk_ok=True) == "C"
    assert grade_trade(result="loss", actual_rr=-1.0, planned_rr=3.0,
                       followed_strategy=True, risk_ok=True) == "D"
    # risk violated -> F regardless of P&L
    assert grade_trade(result="win", actual_rr=3.0, planned_rr=3.0,
                       followed_strategy=True, risk_ok=False) == "F"


def test_build_review_is_deterministic_and_honest():
    r = build_review(side="long", planned_rr=3.0, actual_rr=-1.0, result="loss",
                     exit_reason="stop-loss", quality_score=72, risk_ok=True,
                     followed_strategy=True)
    assert r["grade"] == "D" and r["risk_valid"] and r["exit_valid"]
    assert "stop did its job" in r["mistake"]
    bad = build_review(side="long", planned_rr=3.0, actual_rr=3.0, result="win",
                       exit_reason="target", quality_score=50, risk_ok=False,
                       followed_strategy=False)
    assert bad["grade"] == "F" and "bypass the Risk Manager" in bad["improvement"]


def test_build_evolution_respects_staging():
    early = build_evolution({"setup_key": "Brain|Trending|long", "trades": 3,
                             "win_rate": 66.0, "net_r": 4.0, "stage": "early-signal",
                             "note": "n"})
    assert early["confidence_direction"] == "hold"
    assert "early signal" in early["strength"]
    assert any("never increased automatically" in g.lower() for g in early["guardrails"])
    strong = build_evolution({"setup_key": "Brain|Trending|long", "trades": 60,
                              "win_rate": 55.0, "net_r": 40.0, "stage": "evidence",
                              "note": "n"})
    assert strong["confidence_direction"] == "increase (bounded)"


# ─────────────────────────── store + staging ───────────────────────────
def test_store_roundtrip_and_evolution_staging():
    st = JournalStore(":memory:")
    st.record_entry({"trade_id": "t1", "mode": "paper", "symbol": "BTCUSDT",
                     "side": "long", "strategy": "Decision Brain", "timeframe": "4h",
                     "entry": 100, "stop": 95, "target": 115, "size": 2.0,
                     "risk_amount": 10, "planned_rr": 3.0, "confidence": 0.8,
                     "brain_score": 0.5, "regime": "Trending",
                     "sections": {"checklist": {"entry_reads": []}}})
    st.add_event("t1", "trade-opened", "long 2 @ 100")
    j = st.get("t1")
    assert j["status"] == "open" and j["symbol"] == "BTCUSDT"
    assert j["events"][0]["kind"] == "trade-opened"
    st.close_trade("t1", exit=115, pnl=30, actual_rr=3.0, result="win", grade="A",
                   extra_sections={"review": {"grade": "A"}})
    assert st.get("t1")["status"] == "closed" and st.get("t1")["grade"] == "A"
    # evolution staging: early-signal until 30, evidence at 50+
    for i in range(EVIDENCE_MIN):
        s = st.update_evolution("Brain|Trending|long", "Brain", "Trending", "long", 1.0)
    assert s["stage"] == "evidence" and s["trades"] == EVIDENCE_MIN
    assert st.evolution()[0]["setup_key"] == "Brain|Trending|long"


# ─────────────────────────── pipeline integration ───────────────────────────
def _pipe_with_journal():
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.controls import TradingControl
    from services.signal_pipeline import SignalPipeline
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5,
                          max_total_exposure_pct=1.0, adaptive_risk=False,
                          equity_throttle=False)
    pipe.journal = DecisionJournal(JournalStore(":memory:"))
    return pipe, paper


def test_pipeline_records_full_journal_on_open_and_close():
    pipe, paper = _pipe_with_journal()
    snap = {"price": 100, "rsi": 58, "atr": 1.2, "regime": "Trending"}
    checklist = [{"name": "EMA trend (fast vs slow)", "status": "Passed", "detail": "up"}]
    r = pipe.process({"alert_id": "a1", "symbol": "BTCUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0, "target": 115.0, "confidence": 0.8,
                      "regime": "Trending", "strategy": "Decision Brain", "timeframe": "4h",
                      "brain_score": 0.5, "snapshot": snap, "brain_checklist": checklist,
                      "mode": "paper", "open_trades": 0})
    assert r.accepted
    tid = r.fill["trade_id"]
    j = pipe.journal.store.get(tid)
    assert j is not None and j["status"] == "open"
    # real sections captured
    assert j["sections"]["entry_decision"]["confidence_score"] == 0.8
    assert j["sections"]["market_snapshot"]["rsi"] == 58
    assert any(g["rule"] == "daily_loss" or g["rule"] == "exposure"
               for g in j["sections"]["checklist"]["risk_gates"])
    # honesty: FVG etc. are Not checked, not invented
    assert any(c["status"] == "Not checked" for c in j["sections"]["checklist"]["entry_reads"])
    assert [e["kind"] for e in j["events"]][:3] == ["setup-detected", "risk-check-passed", "trade-opened"]

    # close it — review + evolution generated from the real outcome
    c = pipe.process({"alert_id": "c1", "symbol": "BTCUSDT", "side": "CLOSE",
                      "entry": 115.0, "exit_reason": "take-profit"})
    assert c.accepted
    jc = pipe.journal.store.get(tid)
    assert jc["status"] == "closed" and jc["result"] == "win"
    assert jc["sections"]["exit_decision"]["exit_reason"] == "take-profit"
    assert jc["sections"]["review"]["grade"] in ("A", "B")
    assert "evolution" in jc["sections"]
    assert jc["sections"]["evolution"]["take_similar_again"] is True


# ─────────────────────────── endpoints ───────────────────────────
def test_journal_endpoints():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    assert "trades" in client.get("/journal/trades").json()
    assert "setups" in client.get("/journal/evolution").json()
    assert client.get("/journal/does-not-exist").status_code == 404


def test_decision_store_does_not_shadow_the_human_journal():
    """The decision-journal store and the human trade-journal store share the
    class name ``JournalStore`` — guard against one silently replacing the other
    (which would break /journal, /journal/from-replay, PATCH/DELETE)."""
    pytest.importorskip("fastapi")
    import webhook_api
    # two distinct stores, each with its own API surface
    assert webhook_api.journal_store is not webhook_api.decision_journal_store
    assert hasattr(webhook_api.journal_store, "add_from_trades")  # human journal
    assert hasattr(webhook_api.decision_journal_store, "evolution")  # decision journal
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    # old human-journal endpoint still returns its own shape, not decision rows
    assert "entries" in client.get("/journal").json()
