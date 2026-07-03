"""Positive-pattern learning: the bot studies its WINNERS too — bounded
size-ups on proven patterns, with defense always outranking offense."""
from datetime import datetime, timedelta, timezone

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.learning import MAX_BOOST, LearningBook, classify
from services.signal_pipeline import SignalPipeline

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _trade(i, sym="BTCUSDT", rr=2.5, alert=""):
    pnl = rr * 10
    return {"symbol": sym, "pnl": pnl, "rr": rr, "status": "closed",
            "alert_id": alert or f"t{i}",
            "opened_at": (TS + timedelta(hours=5 * i)).isoformat(),
            "closed_at": (TS + timedelta(hours=5 * i + 2)).isoformat()}


def _winning_history():
    """10 strong Trending winners at conviction 0.8; 6 mediocre low-conv trades."""
    trades = [_trade(i, rr=2.5, alert=f"w{i}") for i in range(10)]
    trades += [_trade(10 + i, rr=(0.3 if i % 2 == 0 else -1.0), alert=f"m{i}")
               for i in range(6)]
    events = {f"w{i}": {"confidence": 0.8, "regime": "Trending"} for i in range(10)}
    events |= {f"m{i}": {"confidence": 0.6, "regime": "Low Volatility"} for i in range(6)}
    return trades, events


# ─────────────────────────── classification ───────────────────────────
def test_classify_finds_edge_regime_and_conviction():
    trades, events = _winning_history()
    kinds = {f["kind"]: f for f in classify(trades, events)}
    assert kinds["edge-regime"]["key"] == "Trending"
    assert "size them up" in kinds["edge-regime"]["lesson"]
    assert kinds["edge-conviction"]["key"] == "confidence>=0.75"


def test_no_edge_findings_without_sample_or_margin():
    # only 5 winners: below the 8-trade bar -> silence
    trades = [_trade(i, rr=2.5, alert=f"w{i}") for i in range(5)]
    events = {f"w{i}": {"confidence": 0.8, "regime": "Trending"} for i in range(5)}
    kinds = {f["kind"] for f in classify(trades, events)}
    assert "edge-regime" not in kinds and "edge-conviction" not in kinds
    # high-conviction NOT clearly better than the rest -> no conviction edge
    trades2 = [_trade(i, rr=0.6, alert=f"a{i}") for i in range(10)]
    trades2 += [_trade(10 + i, rr=0.5, alert=f"b{i}") for i in range(6)]
    events2 = {f"a{i}": {"confidence": 0.8, "regime": "Trending"} for i in range(10)}
    events2 |= {f"b{i}": {"confidence": 0.6, "regime": "Trending"} for i in range(6)}
    kinds2 = {f["kind"] for f in classify(trades2, events2)}
    assert "edge-conviction" not in kinds2


# ─────────────────────────── the book ───────────────────────────
def test_book_applies_bounded_boosts():
    book = LearningBook()
    trades, events = _winning_history()
    book.update(list(reversed(trades)), events, now=TS + timedelta(days=1))
    assert book.boost_multiplier(regime="Trending") == MAX_BOOST
    assert book.boost_multiplier(regime="Ranging") == 1.0
    assert book.boost_multiplier(confidence=0.8) == MAX_BOOST
    assert book.boost_multiplier(confidence=0.6) == 1.0
    # boosts never stack past the cap
    assert book.boost_multiplier(regime="Trending", confidence=0.9) == MAX_BOOST


def test_boost_expires_when_pattern_fades():
    book = LearningBook()
    trades, events = _winning_history()
    book.update(list(reversed(trades)), events, now=TS + timedelta(days=1))
    assert book.boost_multiplier(regime="Trending") == MAX_BOOST
    # a month later the pattern has genuinely faded (expectancy well below
    # the bar) and is not re-confirmed -> the boost expires
    losers = [_trade(50 + i, rr=-1.0, alert=f"l{i}") for i in range(20)]
    events |= {f"l{i}": {"confidence": 0.8, "regime": "Trending"} for i in range(20)}
    book.update(list(reversed(trades + losers)), events, now=TS + timedelta(days=40))
    assert book.boost_multiplier(regime="Trending") == 1.0


# ─────────────────────────── pipeline enforcement ───────────────────────────
def _pipe():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5,
                          max_total_exposure_pct=1.0,
                          adaptive_risk=False, equity_throttle=False)
    pipe.learning = LearningBook()
    trades, events = _winning_history()
    pipe.learning.update(list(reversed(trades)), events, now=TS)
    return pipe, paper


def test_pipeline_sizes_up_the_proven_pattern():
    pipe, paper = _pipe()
    r = pipe.process({"alert_id": "e1", "symbol": "BTCUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0, "confidence": 1.0,
                      "regime": "Trending"})
    assert r.accepted
    risk_step = next(s for s in r.steps if s.rule == "risk")
    assert "edge 1.25" in risk_step.detail
    assert abs(r.fill["size"] - 25.0) < 0.5     # 1% x 1.25 boost -> 25 units
    # an unproven regime gets normal size (confidence above the learned
    # floor but below the boost threshold)
    r2 = pipe.process({"alert_id": "e2", "symbol": "ETHUSDT", "side": "BUY",
                       "entry": 100.0, "stop": 95.0, "confidence": 0.70,
                       "regime": "Ranging"})
    assert r2.accepted and "edge" not in next(
        s for s in r2.steps if s.rule == "risk").detail


def test_defense_outranks_offense():
    pipe, paper = _pipe()
    # put BTCUSDT on probation (learned 0.5x) — the boost must stand down
    pipe.learning.adjustments["symbol:BTCUSDT"] = {
        "type": "risk_multiplier", "symbol": "BTCUSDT", "multiplier": 0.5,
        "lesson": "t", "expires_at": "2099-01-01T00:00:00+00:00",
        "learned_at": TS.isoformat(), "evidence": {}}
    r = pipe.process({"alert_id": "d1", "symbol": "BTCUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0, "confidence": 1.0,
                      "regime": "Trending"})
    assert r.accepted
    detail = next(s for s in r.steps if s.rule == "risk").detail
    assert "learned 0.50" in detail and "edge" not in detail
    assert abs(r.fill["size"] - 10.0) < 0.5     # halved, never boosted