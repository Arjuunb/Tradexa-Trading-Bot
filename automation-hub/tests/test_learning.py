"""Self-learning loop: mistake classification, bounded corrections that expire
and relax, live pipeline enforcement, persistence, endpoints."""
from datetime import datetime, timedelta, timezone

import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.learning import LearningBook, classify
from services.signal_pipeline import SignalPipeline

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _trade(sym="BTCUSDT", pnl=-10.0, rr=-1.0, opened=None, closed=None, alert=""):
    opened = opened or T0
    return {"symbol": sym, "pnl": pnl, "rr": rr, "status": "closed", "alert_id": alert,
            "opened_at": opened.isoformat(),
            "closed_at": (closed or opened + timedelta(hours=2)).isoformat()}


# ─────────────────────────── classification (pure) ───────────────────────────
def test_classify_symbol_leak():
    trades = [_trade("SOLUSDT", pnl=-10, opened=T0 + timedelta(hours=i * 5)) for i in range(5)]
    trades += [_trade("BTCUSDT", pnl=20, opened=T0 + timedelta(hours=i * 5)) for i in range(5)]
    kinds = {f["kind"]: f for f in classify(trades)}
    assert "symbol-leak" in kinds and kinds["symbol-leak"]["key"] == "SOLUSDT"
    assert "half risk" in kinds["symbol-leak"]["lesson"]


def test_classify_revenge_trades():
    trades, t = [], T0
    for _ in range(4):                       # loss, then re-entry 10 minutes later
        trades.append(_trade("BTCUSDT", pnl=-10, opened=t, closed=t + timedelta(minutes=30)))
        t = t + timedelta(minutes=40)        # opened 10m after the previous close
    kinds = {f["kind"] for f in classify(trades)}
    assert "revenge-trades" in kinds


def test_classify_regime_and_confidence_with_events():
    trades = [_trade("BTCUSDT", pnl=-10, alert=f"a{i}",
                     opened=T0 + timedelta(hours=5 * i)) for i in range(5)]
    trades += [_trade("ETHUSDT", pnl=25, alert=f"b{i}",
                      opened=T0 + timedelta(hours=5 * i)) for i in range(5)]
    events = {f"a{i}": {"confidence": 0.58, "regime": "High Volatility"} for i in range(5)}
    events |= {f"b{i}": {"confidence": 0.9, "regime": "Trending"} for i in range(5)}
    kinds = {f["kind"]: f for f in classify(trades, events)}
    assert kinds["regime-leak"]["key"] == "High Volatility"
    assert "low-conviction" in kinds


def test_classify_slipped_stops_and_quiet_on_healthy_record():
    slipped = [_trade(pnl=-18, rr=-1.8, opened=T0 + timedelta(hours=i)) for i in range(3)]
    assert any(f["kind"] == "slipped-stops" for f in classify(slipped))
    healthy = [_trade(pnl=30, rr=3.0, opened=T0 + timedelta(hours=i * 3)) for i in range(20)]
    assert classify(healthy) == []           # nothing to learn from winning


# ─────────────────────────── the learning book ───────────────────────────
def test_book_applies_bounded_corrections_and_relaxes_them(tmp_path):
    path = str(tmp_path / "learning.json")
    book = LearningBook(path)
    losers = [_trade("SOLUSDT", pnl=-10, opened=T0 + timedelta(hours=5 * i)) for i in range(6)]
    book.update(list(reversed(losers)), now=T0 + timedelta(days=2))
    assert book.risk_multiplier("SOLUSDT") == 0.5          # bounded at half risk
    assert any(h["action"] == "applied" for h in book.history)

    # persists across restarts
    book2 = LearningBook(path)
    assert book2.risk_multiplier("SOLUSDT") == 0.5

    # symbol recovers -> after expiry with no re-confirmation the rule relaxes
    winners = [_trade("SOLUSDT", pnl=30, opened=T0 + timedelta(days=3, hours=5 * i))
               for i in range(6)]
    book2.update(list(reversed(losers + winners)), now=T0 + timedelta(days=30))
    assert book2.risk_multiplier("SOLUSDT") == 1.0
    assert any(h["action"] == "relaxed" for h in book2.history)


def test_book_gate_blocks_learned_regime_and_low_confidence():
    book = LearningBook()
    trades = [_trade("BTCUSDT", pnl=-10, alert=f"a{i}",
                     opened=T0 + timedelta(hours=5 * i)) for i in range(5)]
    trades += [_trade("ETHUSDT", pnl=25, alert=f"b{i}",
                      opened=T0 + timedelta(hours=5 * i)) for i in range(5)]
    events = {f"a{i}": {"confidence": 0.55, "regime": "Ranging"} for i in range(5)}
    events |= {f"b{i}": {"confidence": 0.9, "regime": "Trending"} for i in range(5)}
    book.update(list(reversed(trades)), events, now=T0 + timedelta(days=1))
    assert book.gate(symbol="BTCUSDT", regime="Ranging") is not None
    assert book.gate(symbol="BTCUSDT", regime="Trending", confidence=0.9) is None
    assert book.gate(symbol="BTCUSDT", regime="", confidence=0.5) is not None  # floor


# ─────────────────────────── pipeline enforcement ───────────────────────────
def _pipe_with_book():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, adaptive_risk=False,
                          equity_throttle=False, max_total_exposure_pct=1.0,
                          exposure_limit_pct=0.5)
    pipe.learning = LearningBook()
    return pipe, paper


def test_pipeline_rejects_learned_regime_and_halves_probation_risk():
    pipe, paper = _pipe_with_book()
    # teach it: SOL bleeds, and 'Choppy' regime bleeds (via events)
    losers = [_trade("SOLUSDT", pnl=-10, alert=f"a{i}",
                     opened=T0 + timedelta(hours=5 * i)) for i in range(6)]
    winners = [_trade("BTCUSDT", pnl=25, alert=f"b{i}",
                      opened=T0 + timedelta(hours=5 * i)) for i in range(6)]
    events = {f"a{i}": {"confidence": 0.9, "regime": "Choppy"} for i in range(6)}
    events |= {f"b{i}": {"confidence": 0.9, "regime": "Trending"} for i in range(6)}
    pipe.learning.update(list(reversed(losers + winners)), events, now=T0)

    blocked = pipe.process({"alert_id": "x1", "symbol": "ETHUSDT", "side": "BUY",
                            "entry": 100.0, "stop": 95.0, "confidence": 0.9,
                            "regime": "Choppy"})
    assert not blocked.accepted and blocked.stage == "learning"

    ok = pipe.process({"alert_id": "x2", "symbol": "SOLUSDT", "side": "BUY",
                       "entry": 100.0, "stop": 95.0, "confidence": 1.0,
                       "regime": "Trending"})
    assert ok.accepted
    risk_step = next(s for s in ok.steps if s.rule == "risk")
    assert "learned 0.50" in risk_step.detail            # probation risk
    assert abs(ok.fill["size"] - 10.0) < 0.3             # half of the normal 20


def test_pipeline_relearns_after_each_close():
    pipe, paper = _pipe_with_book()
    assert pipe.learning.updated_at is None
    pipe.process({"alert_id": "o1", "symbol": "BTCUSDT", "side": "BUY",
                  "entry": 100.0, "stop": 95.0, "confidence": 1.0})
    pipe.process({"alert_id": "c1", "symbol": "BTCUSDT", "side": "CLOSE", "entry": 96.0})
    assert pipe.learning.updated_at is not None          # learned from the close


# ─────────────────────────── endpoint ───────────────────────────
def test_learning_report_endpoint():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    body = client.get("/learning/report").json()
    assert "lessons" in body and "active_adjustments" in body and "evolution" in body
    assert client.post("/learning/run").status_code == 401   # secret required