"""Self-improvement loop, rounds 2+3: learning context survives restarts
(#4) and the self-retune pipeline proposes validated upgrades (#2)."""
from datetime import datetime, timedelta, timezone

import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ─────────────────── #4: context survives restarts ───────────────────
def test_ledger_returns_webhook_events_with_parsed_payload():
    led = SqliteLedger(":memory:")
    led.insert_webhook_event(alert_id="a1", symbol="BTCUSDT", side="BUY",
                             entry=100.0, stop=95.0,
                             payload={"confidence": 0.8, "regime": "Trending"},
                             status="accepted")
    evs = led.get_webhook_events()
    assert len(evs) == 1
    assert evs[0]["payload"]["regime"] == "Trending"


def test_alert_context_rehydrates_after_restart(tmp_path):
    db = str(tmp_path / "led.db")
    led = SqliteLedger(db)
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          adaptive_risk=False, equity_throttle=False)
    r = pipe.process({"alert_id": "ctx1", "symbol": "BTCUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0, "confidence": 0.71,
                      "regime": "Trending"})
    assert r.accepted

    # "restart": a brand-new pipeline over the same ledger
    led2 = SqliteLedger(db)
    paper2 = PaperExecutionEngine(led2)
    pipe2 = SignalPipeline(led2, paper2, TradingControl(), equity=10_000)
    ctx = pipe2.alert_context()
    assert ctx["ctx1"] == {"confidence": 0.71, "regime": "Trending"}
    # rejected events never enter the learning context
    pipe2.process({"alert_id": "ctx2", "symbol": "BTCUSDT", "side": "BUY",
                   "entry": 100.0, "stop": None, "regime": "Ranging"})
    assert "ctx2" not in pipe2.alert_context()


# ─────────────────── #2: self-retune pipeline ───────────────────
def test_retune_search_is_honest_without_real_data(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config.settings, "market_db", str(tmp_path / "empty.db"))
    monkeypatch.setenv("HUB_REQUIRE_REAL_DATA", "1")
    from services.retune import evaluate_candidates
    rep = evaluate_candidates(symbols=("BTCUSDT",), timeframe="1h")
    assert rep["available"] is False and rep["verdict"] == "no-real-data"


def test_retune_search_ranks_on_train_and_judges_on_test():
    # synthetic allowed here (require_real=False) — the DECISION LOGIC is
    # under test; production calls keep require_real=True
    from services.retune import evaluate_candidates
    rep = evaluate_candidates(symbols=("ZZZUSDT",), timeframe="1h",
                              bars=2600, require_real=False)
    assert rep["available"] is True
    assert rep["verdict"] in ("candidate-found", "keep-incumbent",
                              "insufficient-trades")
    assert rep["incumbent"] == {"conviction_threshold": 0.56, "rr_target": 3.0}
    assert rep["best_candidate"] != rep["incumbent"]
    assert len(rep["train_ranking"]) == 5
    assert "candidate" in rep["test_net_r"] and "incumbent" in rep["test_net_r"]


def test_retune_gated_by_track_verdict_and_force():
    from services.retune import retune

    class _Eng:
        symbols = ["ZZZUSDT"]
        shadow = None
    skipped = retune(_Eng(), None, track_verdict="on-track")
    assert skipped["ran"] is False and "divergence" in skipped["detail"]


def test_retune_starts_shadow_when_candidate_wins(monkeypatch):
    from services import retune as rt

    class _Eng:
        symbols = ["ZZZUSDT"]
        shadow = None
    eng = _Eng()
    sent = []
    monkeypatch.setattr(rt, "evaluate_per_symbol", lambda **kw: {
        "available": True, "verdict": "candidate-found",
        "detail": "1 symbol has a validated per-symbol config",
        "winners": {"ZZZUSDT": {"conviction_threshold": 0.62, "rr_target": 3.5}},
        "per_symbol": {}, "incumbent": rt.INCUMBENT})
    res = rt.retune(eng, lambda k, t, d: sent.append(t), force=True)
    assert res["verdict"] == "candidate-found"
    assert eng.shadow is not None and "ZZZUSDT" in eng.shadow.name
    assert sent and "Retune" in sent[0]
    # the shadow candidate really runs the retuned params
    strat = eng.shadow._strats["ZZZUSDT"]
    assert strat.params["conviction_threshold"] == 0.62
    assert strat.params["rr_target"] == 3.5


def test_retune_keeps_incumbent_without_shadow(monkeypatch):
    from services import retune as rt

    class _Eng:
        symbols = ["ZZZUSDT"]
        shadow = None
    eng = _Eng()
    monkeypatch.setattr(rt, "evaluate_per_symbol", lambda **kw: {
        "available": True, "verdict": "keep-incumbent", "detail": "no winner",
        "winners": {}, "per_symbol": {}})
    res = rt.retune(eng, None, force=True)
    assert res["verdict"] == "keep-incumbent" and eng.shadow is None


# ─────────────────── endpoints ───────────────────
def test_retune_endpoints():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    assert client.post("/retune/run").status_code == 401   # secret required
    rep = client.get("/retune/report").json()
    assert "ran" in rep or "verdict" in rep