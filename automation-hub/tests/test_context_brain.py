"""Context-aware brain: cross-asset gate, funding/sentiment sizing — all OFF
by default, validated on demand, graded when enabled."""
from datetime import datetime, timezone

import pytest

from bot.types import Signal, SignalType
from services.context_brain import (ContextConfig, ContextModifiers,
                                    classify_trend, cross_asset_block,
                                    fetch_funding_history_factors,
                                    fetch_sentiment_history_factors,
                                    funding_factor, leader_trend_series,
                                    sentiment_factor, validate_cross_asset,
                                    validate_sizing_modifier)

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ─────────────────────────── pure rules ───────────────────────────
def test_classify_trend():
    up = [100 + i for i in range(80)]
    down = [200 - i for i in range(80)]
    assert classify_trend(up) == "bullish"
    assert classify_trend(down) == "bearish"
    assert classify_trend([100.0] * 80) == "neutral"
    assert classify_trend([100.0] * 10) == "neutral"      # not enough history


def test_cross_asset_block_rules():
    assert cross_asset_block("ETHUSDT", "long", "bearish") is not None
    assert cross_asset_block("ETHUSDT", "short", "bullish") is not None
    assert cross_asset_block("ETHUSDT", "long", "bullish") is None
    assert cross_asset_block("ETHUSDT", "long", "neutral") is None
    assert cross_asset_block("BTCUSDT", "long", "bearish") is None  # BTC exempt


def test_funding_and_sentiment_factors():
    assert funding_factor("long", 0.08) == 0.5            # crowded longs
    assert funding_factor("short", 0.08) == 1.0           # against the crowd: full
    assert funding_factor("short", -0.08) == 0.5
    assert funding_factor("long", None) == 1.0
    assert sentiment_factor("short", 5) == 0.5            # shorting capitulation
    assert sentiment_factor("long", 95) == 0.5            # buying euphoria
    assert sentiment_factor("long", 50) == 1.0
    assert sentiment_factor("long", None) == 1.0


# ─────────────────────────── off by default ───────────────────────────
def test_modifiers_are_noops_until_enabled(monkeypatch):
    monkeypatch.delenv("HUB_CONTEXT", raising=False)
    ctx = ContextModifiers()
    assert ctx.config.any_enabled is False
    assert ctx.gate("ETHUSDT", "long") is None
    assert ctx.size_factor("ETHUSDT", "long") == 1.0
    monkeypatch.setenv("HUB_CONTEXT", "cross")
    cfg = ContextConfig.from_env()
    assert cfg.cross_asset and not cfg.funding and not cfg.sentiment
    monkeypatch.setenv("HUB_CONTEXT", "1")
    assert ContextConfig.from_env().any_enabled


# ─────────────────────────── engine integration ───────────────────────────
def test_engine_gate_blocks_alt_long_against_btc_and_grades_it():
    from bot.data.synthetic import generate_bars
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.auto_engine import AutoStrategyEngine
    from services.controls import TradingControl
    from services.counterfactual import CounterfactualTracker
    from services.signal_pipeline import SignalPipeline

    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000)
    eng = AutoStrategyEngine(pipe, paper, led, symbols=["ETHUSDT"],
                             entry_mode="market")
    eng.min_quality_score = 0                       # isolate the context gate
    eng.context = ContextModifiers(
        ContextConfig(cross_asset=True),
        leader_bars_fn=lambda: generate_bars(
            n=80, timeframe="1h", drift_per_bar=-0.004, vol_per_bar=0.002, seed=3))
    eng.counterfactual = CounterfactualTracker()

    class _Stub:
        bars = []
        def __init__(self): self._fired = False
        def on_bar(self, bar):
            if self._fired: return None
            self._fired = True
            return Signal(timestamp=TS, symbol="ETHUSDT", type=SignalType.LONG,
                          entry=100.0, stop_loss=95.0, take_profit=110.0, reason="x")

    from bot.types import Bar
    eng._process_bar("ETHUSDT", Bar(TS, 100, 100, 100, 100, 1.0), _Stub())
    assert paper.positions() == []                  # blocked: BTC is bearish
    assert eng.stats["rejections"] == 1
    assert eng.counterfactual.open[0]["rule"] == "context:btc-trend"
    assert any(l["stage"] == "context" for l in led.get_logs())


def test_pipeline_applies_context_size_factor():
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.controls import TradingControl
    from services.signal_pipeline import SignalPipeline
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5,
                          max_total_exposure_pct=1.0,
                          adaptive_risk=False, equity_throttle=False)
    r = pipe.process({"alert_id": "cx1", "symbol": "BTCUSDT", "side": "BUY",
                      "entry": 100.0, "stop": 95.0, "confidence": 1.0,
                      "context_size_factor": 0.5})
    assert r.accepted
    detail = next(s for s in r.steps if s.rule == "risk").detail
    assert "context 0.50" in detail
    assert abs(r.fill["size"] - 10.0) < 0.3         # half of the normal 20


# ─────────────────────────── validation harness ───────────────────────────
def test_validate_cross_asset_honest_without_data(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config.settings, "market_db", str(tmp_path / "empty.db"))
    monkeypatch.setenv("HUB_REQUIRE_REAL_DATA", "1")
    rep = validate_cross_asset(timeframe="1h")
    assert rep["available"] is False and rep["verdict"] == "no-real-data"


def test_validate_cross_asset_runs_and_verdicts(monkeypatch):
    rep = validate_cross_asset(symbols=("ZZZUSDT",), timeframe="1h", bars=1600,
                               require_real=False)
    # leader ZZZ... wait: leader is BTCUSDT — synthetic fallback provides it
    assert rep["available"] is True
    assert rep["verdict"] in ("helps", "hurts", "neutral")
    judged = rep["per_symbol"][0]
    assert "baseline" in judged and "gated" in judged
    assert judged["gated"]["blocked_by_btc"] >= 0


def test_validate_sizing_modifier_math():
    rep = validate_sizing_modifier("funding", {}, require_real=False)
    assert rep["available"] is False and rep["verdict"] == "no-history"
    factors = {"2020-01-01": 1.0}                   # no overlap with sim days ->
    rep2 = validate_sizing_modifier("funding", factors,
                                    symbols=("ZZZUSDT",), require_real=False)
    if rep2["available"]:                            # identical weighting = neutral
        assert rep2["verdict"] == "neutral"
        assert rep2["net_r"]["baseline"] == rep2["net_r"]["with_modifier"]


def test_history_fetchers_parse_and_fail_honestly():
    funding_rows = [{"fundingTime": 1750000000000, "fundingRate": "0.0008"},
                    {"fundingTime": 1750086400000, "fundingRate": "0.0001"}]
    f = fetch_funding_history_factors(get_json=lambda url: funding_rows)
    assert 0.5 in f.values() and len(f) == 2         # 0.08% day is crowded
    assert fetch_funding_history_factors(get_json=lambda url: None) == {}
    fng = {"data": [{"value": "8", "timestamp": "1750000000"},
                    {"value": "55", "timestamp": "1750086400"}]}
    sf = fetch_sentiment_history_factors("short", get_json=lambda url: fng)
    assert 0.5 in sf.values()
    assert fetch_sentiment_history_factors(get_json=lambda url: None) == {}


def test_validate_context_endpoint_requires_secret():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    assert client.post("/research/validate-context").status_code == 401