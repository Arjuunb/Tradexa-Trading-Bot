"""Market-quality gate — strong, fail-closed pre-trade safety checks."""
from datetime import datetime, timedelta, timezone

import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.market_quality import MarketQualityConfig, MarketQualityGate
from services.signal_pipeline import SignalPipeline


@pytest.fixture()
def gate():
    return MarketQualityGate()


def test_valid_entry_passes(gate):
    assert gate.check(entry=100.0, stop=98.0).ok


def test_rejects_non_finite_or_negative_entry(gate):
    assert not gate.check(entry=float("nan"), stop=98.0).ok
    assert not gate.check(entry=float("inf"), stop=98.0).ok
    assert not gate.check(entry=0.0, stop=98.0).ok
    assert not gate.check(entry=-5.0, stop=98.0).ok


def test_rejects_nan_stop(gate):
    assert not gate.check(entry=100.0, stop=float("nan")).ok


def test_rejects_stop_too_tight(gate):
    # 0.01% away -> would size a massive position from (likely) bad data
    v = gate.check(entry=100.0, stop=99.99)
    assert not v.ok and "tight" in v.reason


def test_rejects_stop_too_wide(gate):
    v = gate.check(entry=100.0, stop=50.0)   # 50% > 25% cap
    assert not v.ok and "wide" in v.reason


def test_missing_or_equal_stop_passes_quality(gate):
    # A None / entry-equal stop is the risk step's job, not market quality.
    assert gate.check(entry=100.0, stop=None).ok
    assert gate.check(entry=100.0, stop=100.0).ok


def test_rejects_crossed_book(gate):
    v = gate.check(entry=100.0, stop=98.0, bid=101.0, ask=100.0)
    assert not v.ok and "Crossed" in v.reason


def test_spread_veto_only_when_configured():
    g = MarketQualityGate(MarketQualityConfig(max_spread_bps=10))
    # 50 bps spread > 10 bps limit
    assert not g.check(entry=100.0, stop=98.0, bid=100.0, ask=100.5).ok
    # tight spread passes
    assert g.check(entry=100.0, stop=98.0, bid=100.0, ask=100.02).ok


def test_stale_signal_veto_only_when_configured():
    g = MarketQualityGate(MarketQualityConfig(max_signal_age_s=60))
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    assert not g.check(entry=100.0, stop=98.0, timestamp=old).ok
    assert g.check(entry=100.0, stop=98.0, timestamp=fresh).ok
    # disabled by default -> old timestamp passes
    assert MarketQualityGate().check(entry=100.0, stop=98.0, timestamp=old).ok


def test_fails_closed_on_bad_input(gate):
    # A non-numeric entry must VETO, never raise.
    v = gate.check(entry="oops", stop=98.0)
    assert not v.ok


# --- integration: the gate blocks inside the pipeline ---
def _pipe():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, 10_000)
    return SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.05), paper, led


def test_pipeline_vetoes_bad_stop_before_execution():
    pipe, paper, led = _pipe()
    res = pipe.process({"alert_id": "x", "symbol": "BTCUSDT", "side": "BUY",
                        "entry": 100.0, "stop": 99.999})   # absurdly tight
    assert not res.accepted and res.stage == "market_quality"
    assert paper.positions() == []
    events = led._c.execute("SELECT status FROM webhook_events").fetchall()
    assert events and events[0]["status"] == "rejected"


def test_pipeline_allows_healthy_trade():
    pipe, paper, _ = _pipe()
    res = pipe.process({"alert_id": "ok", "symbol": "BTCUSDT", "side": "BUY",
                        "entry": 67500.0, "stop": 66800.0})
    assert res.accepted and res.stage == "execution"
    assert any(s.rule == "market_quality" and s.passed for s in res.steps)
