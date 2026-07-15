"""Trading modes (§7) + trade approval (§11) + risk presets (§9).

Semi-auto queues ENTRIES for approval and routes approved ones through the
unchanged risk pipeline; signal mode alerts only; exits are never gated. Risk
presets bundle risk-per-trade with matching drawdown / exposure guards.
"""
import pytest
from fastapi.testclient import TestClient

from bot.data.synthetic import generate_bars
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.approvals import ApprovalStore
from services.auto_engine import AutoStrategyEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline
from strategies.brain_strategy import DecisionBrain


# ─────────────────────────── ApprovalStore unit ───────────────────────────
def _payload(sym="BTCUSDT", side="BUY", entry=100.0, stop=95.0, target=115.0):
    return {"symbol": sym, "side": side, "entry": entry, "stop": stop,
            "target": target, "confidence": 0.8, "timeframe": "5m",
            "strategy": "Decision Brain", "reason": "test setup"}


def test_semi_idea_is_pending_signal_is_recent_only():
    st = ApprovalStore(clock=lambda: 1000.0)
    semi = st.create(_payload(), decision={"score": 82}, verdict=None, mode="semi")
    assert semi["status"] == "pending" and semi["planned_rr"] == 3.0
    assert semi["brain_score"] == 82
    assert st.counts()["pending"] == 1
    st.create(_payload(sym="ETHUSDT"), decision=None, verdict=None, mode="signal")
    assert st.counts()["pending"] == 1                 # signal never queues
    assert any(r["status"] == "signal" for r in st.list_recent())
    # private payload never leaks to the public view
    assert "_payload" not in semi


def test_approve_returns_payload_reject_records():
    st = ApprovalStore(clock=lambda: 0.0)
    idea = st.create(_payload(), decision=None, verdict=None, mode="semi")
    approved = st.approve(idea["id"])
    assert approved["_payload"]["symbol"] == "BTCUSDT"   # engine needs this
    assert st.counts()["pending"] == 0
    assert st.approve(idea["id"]) is None                # can't approve twice
    other = st.create(_payload(sym="SOLUSDT"), decision=None, verdict=None, mode="semi")
    assert st.reject(other["id"], "too risky")["status"] == "rejected"


def test_dedup_and_expiry():
    now = [0.0]
    st = ApprovalStore(ttl_s=100, clock=lambda: now[0])
    st.create(_payload(), decision=None, verdict=None, mode="semi")
    assert st.has_pending("BTCUSDT", "BUY") and not st.has_pending("BTCUSDT", "SELL")
    now[0] = 101.0
    expired = st.expire()
    assert len(expired) == 1 and expired[0]["status"] == "expired"
    assert st.counts()["pending"] == 0


# ─────────────────────────── engine integration ───────────────────────────
def _engine(mode="full"):
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000)
    eng = AutoStrategyEngine(pipe, paper, led, symbols=["BTCUSDT"], timeframe="5m",
                             strategy_factory=lambda s: DecisionBrain(s),
                             entry_mode="market")
    eng.approvals = ApprovalStore()
    eng.trading_mode = mode
    return eng, paper


def _feed(eng, seed=11, drift=0.0006):
    strat = DecisionBrain("BTCUSDT")
    for bar in generate_bars(n=700, timeframe="5m", drift_per_bar=drift,
                             vol_per_bar=0.006, seed=seed):
        eng._process_bar("BTCUSDT", bar, strat)


def test_full_mode_executes_entries():
    eng, paper = _engine("full")
    _feed(eng)
    assert eng.stats["trades"] >= 1                      # entries executed
    assert eng.approvals.counts()["pending"] == 0        # nothing queued


def test_semi_mode_queues_entries_instead_of_executing():
    eng, paper = _engine("semi")
    _feed(eng)
    # no ENTRY ever auto-executed -> no positions ever opened
    assert paper.open_position("BTCUSDT") is None
    # but the setups were captured for approval (pending + expired over the run)
    assert eng.approvals.counts()["pending"] + eng.approvals.counts()["recent"] >= 1


def test_approving_a_queued_idea_executes_it():
    eng, paper = _engine("semi")
    # queue one idea directly (deterministic, no dependence on brain timing)
    idea_pub = eng.approvals.create(
        {"alert_id": "x", "symbol": "BTCUSDT", "side": "BUY", "entry": 100.0,
         "stop": 95.0, "target": 115.0, "confidence": 1.0},
        decision=None, verdict=None, mode="semi")
    idea = eng.approvals.approve(idea_pub["id"])
    result = eng.execute_approved(idea)
    assert result["ok"] is True and result["action"] == "opened"
    assert paper.open_position("BTCUSDT") is not None     # real position now open


def test_signal_mode_records_but_never_opens():
    eng, paper = _engine("signal")
    _feed(eng)
    assert paper.open_position("BTCUSDT") is None
    assert eng.approvals.counts()["pending"] == 0         # signal is not approvable
    assert any(r["status"] == "signal" for r in eng.approvals.list_recent())


# ─────────────────────────────── endpoints ───────────────────────────────
@pytest.fixture()
def client():
    import app as app_module
    return TestClient(app_module.app)


def _secret():
    import webhook_api as _wa
    return {"X-Webhook-Secret": _wa.settings.webhook_secret}


def test_mode_endpoints_roundtrip(client):
    import webhook_api as _wa
    original = _wa.engine.trading_mode
    try:
        assert client.get("/engine/mode", headers=_secret()).json()["modes"] == ["full", "semi", "signal"]
        assert client.post("/engine/mode", json={"mode": "bogus"}, headers=_secret()).status_code == 400
        assert client.post("/engine/mode", json={"mode": "semi"}, headers=_secret()).status_code == 200
        assert client.get("/engine/mode", headers=_secret()).json()["mode"] == "semi"
    finally:
        _wa.engine.trading_mode = original


def test_approvals_endpoint_shape(client):
    r = client.get("/approvals", headers=_secret()).json()
    assert "pending" in r and "recent" in r and "mode" in r


def test_risk_preset_endpoints(client):
    import webhook_api as _wa
    p = _wa.pipeline
    saved = (p.risk_per_trade_pct, p.max_open_positions, p.max_daily_loss_pct,
             p.max_drawdown_pct, p.exposure_limit_pct)
    try:
        presets = client.get("/risk/presets", headers=_secret()).json()["presets"]
        assert set(presets) == {"conservative", "balanced", "aggressive"}
        assert presets["conservative"]["risk_per_trade_pct"] == 0.005
        assert client.post("/risk/preset", json={"name": "conservative"},
                           headers=_secret()).status_code == 200
        assert abs(p.risk_per_trade_pct - 0.005) < 1e-9
        assert client.get("/risk/presets", headers=_secret()).json()["active"] == "conservative"
        assert client.post("/risk/preset", json={"name": "nope"},
                           headers=_secret()).status_code == 400
    finally:
        (p.risk_per_trade_pct, p.max_open_positions, p.max_daily_loss_pct,
         p.max_drawdown_pct, p.exposure_limit_pct) = saved
