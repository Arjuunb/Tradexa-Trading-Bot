"""The engine publishes to the event bus — proven against the real engine.

Phase 2 of the architecture consolidation wires ONE seam end to end rather
than shipping machinery that only tests exercise. `_process_bar` is that seam:
every closed bar in both replay and live mode passes through it.

The properties worth holding are that events genuinely flow, and — far more
important — that a subscriber cannot affect trading. Telemetry that can stop a
bar being processed is worse than no telemetry.
"""
from datetime import datetime, timezone

import pytest

from bot.types import Bar
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.auto_engine import AutoStrategyEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline

from tradexa.core.events import MarketDataReceived
from tradexa.infrastructure.events import default_bus


@pytest.fixture()
def engine():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000)
    return AutoStrategyEngine(pipe, paper, led, symbols=["BTCUSDT"], timeframe="4h")


@pytest.fixture(autouse=True)
def clean_bus():
    """A subscriber leaked from one test makes an unrelated one fail later."""
    default_bus().clear()
    yield
    default_bus().clear()


def _bar(close=100.5):
    return Bar(datetime.now(timezone.utc), 100.0, 101.0, 99.0, close, 1000.0)


def test_processing_a_bar_publishes_market_data_received(engine):
    seen = []
    default_bus().subscribe(MarketDataReceived, seen.append)
    engine._process_bar("BTCUSDT", _bar(), engine.strategy_factory("BTCUSDT"))
    assert len(seen) == 1


def test_the_event_carries_the_symbol_timeframe_and_bar(engine):
    """A bar without its symbol and timeframe is what lets a 4h candle be
    treated as 1h downstream."""
    seen = []
    default_bus().subscribe(MarketDataReceived, seen.append)
    engine._process_bar("BTCUSDT", _bar(close=42.0), engine.strategy_factory("BTCUSDT"))
    e = seen[0]
    assert e.symbol == "BTCUSDT" and e.timeframe == "4h"
    assert e.bar.close == 42.0 and e.occurred_at is not None


def test_a_failing_subscriber_does_not_stop_the_bar_being_processed(engine):
    """The property that makes this safe to ship. If a subscriber raises, the
    engine must still record the bar and update its activity clock."""
    default_bus().subscribe(
        MarketDataReceived, lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    engine._process_bar("BTCUSDT", _bar(), engine.strategy_factory("BTCUSDT"))
    assert engine.last_activity is not None
    assert engine.last_bar_ts is not None


def test_no_subscribers_is_the_normal_case_and_costs_nothing(engine):
    """Production has no subscribers today. Publishing into an empty bus must
    be a no-op, not an error."""
    engine._process_bar("BTCUSDT", _bar(), engine.strategy_factory("BTCUSDT"))
    assert engine.last_bar_ts is not None


def test_every_processed_bar_is_announced(engine):
    seen = []
    default_bus().subscribe(MarketDataReceived, seen.append)
    strat = engine.strategy_factory("BTCUSDT")
    for i in range(5):
        engine._process_bar("BTCUSDT", _bar(close=100 + i), strat)
    assert len(seen) == 5
    assert [e.bar.close for e in seen] == [100, 101, 102, 103, 104]
