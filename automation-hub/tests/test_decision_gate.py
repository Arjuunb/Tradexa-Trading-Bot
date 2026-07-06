"""Decision Brain gate (unified decision object): low confidence/score rejected,
high score accepted, reasons persisted, daily-loss + cooldown block trading, and
the engine never routes a rejected decision."""
import pytest

from data.decision_store import DecisionStore
from services.decision_gate import build_decision
from strategies.brain import BrainVerdict


def _verdict(**over):
    base = dict(allowed=True, score=78, regime="Trending", htf_bias="bullish",
                setup_type="trend",
                components={"volume": 5.0, "rr_quality": 12.0, "momentum": 9.0},
                passed=["HTF bullish vs long", "reward:risk 2.40"],
                failed=[], blocks=[])
    base.update(over)
    return BrainVerdict(**base)


def _decision(**over):
    kw = dict(symbol="BTCUSDT", timeframe="4h", strategy="Decision Brain",
              side="long", confidence=0.8, verdict=_verdict(), min_score=60)
    kw.update(over)
    return build_decision(**kw)


# ───────────────────────── accept / reject rules ─────────────────────────
def test_high_confidence_trade_accepted():
    d = _decision()
    assert d["decision"] == "accepted"
    # the full required object is present and real
    assert d["symbol"] == "BTCUSDT" and d["timeframe"] == "4h"
    assert d["strategy"] == "Decision Brain" and d["regime"] == "Trending"
    assert d["htf_bias"] == "bullish"
    assert d["setup_quality_score"] == 78.0
    assert d["volume_score"] == 5.0 and d["rr_score"] == 12.0
    assert d["confidence"] == 0.8
    assert d["passed_rules"] and d["failed_rules"] == []
    assert "78" in d["reason"]


def test_low_confidence_trade_rejected():
    # low quality score -> rejected with the exact failed rules in the reason
    d = _decision(verdict=_verdict(score=41, failed=["RSI 38", "regime Ranging"]))
    assert d["decision"] == "rejected"
    assert "41" in d["reason"] and "below minimum 60" in d["reason"]
    assert "RSI 38" in d["reason"]


def test_hard_block_rejects_regardless_of_score():
    d = _decision(verdict=_verdict(score=95, allowed=False,
                                   blocks=["reward:risk 0.80 below 1.0"]))
    assert d["decision"] == "rejected"
    assert d["reason"].startswith("Hard block")
    assert "reward:risk 0.80" in d["reason"]
    assert "reward:risk 0.80 below 1.0" in d["failed_rules"]


def test_gate_stood_down_is_honest_not_fabricated():
    d = _decision(verdict=None)
    assert d["decision"] == "accepted"
    assert d["setup_quality_score"] is None      # no invented score
    assert "not evaluated" in d["reason"]


# ───────────────────────── durable storage ─────────────────────────
def test_decision_reason_is_saved_and_listable():
    st = DecisionStore(":memory:")
    did = st.record(_decision(verdict=_verdict(score=41, failed=["RSI 38"])))
    saved = st.get(did)
    assert saved["decision"] == "rejected"
    assert "below minimum 60" in saved["reason"]          # reason persisted
    assert saved["failed_rules"] == ["RSI 38"]
    assert saved["executed"] is False
    # accepted one too, then filters work
    st.record(_decision())
    assert len(st.list()) == 2
    assert len(st.list(decision="rejected")) == 1
    assert st.list(decision="accepted")[0]["setup_quality_score"] == 78.0
    # executed flag flips after the pipeline actually opens the trade
    st.mark_executed(did)
    assert st.get(did)["executed"] is True


def test_store_survives_restart(tmp_path):
    p = str(tmp_path / "decisions.db")
    DecisionStore(p).record(_decision())
    assert len(DecisionStore(p).list()) == 1     # fresh instance, same file


# ─────────────── risk gates still block trading (pipeline layer) ───────────────
def _pipe(**kw):
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.controls import TradingControl
    from services.signal_pipeline import SignalPipeline
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, 10_000)
    base = dict(equity=10_000, risk_per_trade_pct=0.01, exposure_limit_pct=0.5,
                max_total_exposure_pct=1.0, adaptive_risk=False, equity_throttle=False)
    base.update(kw)
    return SignalPipeline(led, paper, TradingControl(), **base), paper


def test_max_daily_loss_blocks_trading():
    pipe, paper = _pipe(max_daily_loss_pct=0.01)     # 1% of 10k = $100/day
    # open (exposure cap sizes this to ~50 units), then close for a -$150 day
    r0 = pipe.process({"alert_id": "l1", "symbol": "BTCUSDT", "side": "BUY",
                       "entry": 100.0, "stop": 99.0})
    assert r0.accepted
    paper.close(symbol="BTCUSDT", exit_price=95.0)   # 25 units x -5.0 = -125
    # next entry must be blocked by the daily-loss gate
    r = pipe.process({"alert_id": "l2", "symbol": "ETHUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0})
    assert r.accepted is False and r.stage == "daily_loss"


def test_cooldown_after_loss_blocks_trading():
    pipe, paper = _pipe(cooldown_after_loss_min=60)
    pipe.process({"alert_id": "c1", "symbol": "BTCUSDT", "side": "BUY",
                  "entry": 100.0, "stop": 99.0})
    r0 = pipe.process({"alert_id": "c1x", "symbol": "BTCUSDT", "side": "CLOSE",
                       "entry": 95.0})
    assert r0.accepted                                  # the losing close itself
    r = pipe.process({"alert_id": "c2", "symbol": "ETHUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0})
    assert r.accepted is False and r.stage == "cooldown"
