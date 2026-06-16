"""Live forward mode: trade only NEW closed candles, never the in-progress one."""
from datetime import datetime, timedelta, timezone

from bot.types import Bar, Signal, SignalType
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.auto_engine import AutoStrategyEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline


class _AlwaysLong:
    """Emits a LONG every bar (so we can see when the engine acts)."""
    def __init__(self):
        self.bars = []

    def on_bar(self, bar):
        self.bars.append(bar)
        return Signal(timestamp=bar.timestamp, symbol="BTCUSDT", type=SignalType.LONG,
                      entry=bar.close, stop_loss=bar.close * 0.97,
                      take_profit=bar.close * 1.06, reason="test")


def _bars(n, start=100.0):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Bar(t0 + timedelta(hours=4 * i), start + i, start + i + 1,
                start + i - 1, start + i, 1.0) for i in range(n)]


def _engine():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, 10_000)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5)
    eng = AutoStrategyEngine(pipe, paper, led, symbols=["BTCUSDT"], live=True)
    return eng, paper


def test_ingest_acts_only_on_new_closed_bars():
    eng, paper = _engine()
    strat = _AlwaysLong()
    bars = _bars(5)                       # bars[-1] is "in-progress"
    # warm strategy on the closed history (bars[:-1]) without trading
    for b in bars[:-2]:
        strat.bars.append(b)
    last = bars[-3].timestamp             # already-seen up to here

    # first poll: bars[-2] is the only NEW closed bar (bars[-1] is in-progress)
    last = eng._ingest("BTCUSDT", strat, bars, last)
    assert eng.stats["bars"] == 1
    assert len(paper.positions()) == 1     # it opened on the new closed bar
    assert last == bars[-2].timestamp

    # re-poll with the SAME data -> nothing new, no action
    before = eng.stats["bars"]
    last = eng._ingest("BTCUSDT", strat, bars, last)
    assert eng.stats["bars"] == before


def test_ingest_ignores_in_progress_candle():
    eng, paper = _engine()
    strat = _AlwaysLong()
    bars = _bars(3)
    for b in bars[:-1]:
        strat.bars.append(b)
    last = bars[-2].timestamp              # seen all closed bars
    # only the in-progress bar (bars[-1]) is "new" -> must be ignored
    eng._ingest("BTCUSDT", strat, bars, last)
    assert eng.stats["bars"] == 0
    assert paper.positions() == []


def test_status_reports_mode():
    eng, _ = _engine()
    assert eng.status()["mode"] == "live"
