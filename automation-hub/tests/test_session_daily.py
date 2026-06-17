"""Trading-session window + daily-loss kill switch (real pipeline guards)."""
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline


def _pipe(**kw):
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, 10_000)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5, **kw)
    return pipe, paper


def _alert(aid="a", entry=100, stop=90, ts=None, side="BUY", symbol="BTCUSDT"):
    p = {"alert_id": aid, "symbol": symbol, "side": side, "entry": entry, "stop": stop}
    if ts:
        p["timestamp"] = ts
    return p


def test_session_blocks_outside_hours():
    pipe, paper = _pipe(session_start=8, session_end=20)
    # 03:00 UTC -> outside 08-20 window -> blocked
    res = pipe.process(_alert(ts="2026-01-01T03:00:00+00:00"))
    assert not res.accepted and res.stage == "session"
    assert paper.positions() == []
    # 10:00 UTC -> inside -> allowed
    ok = pipe.process(_alert(aid="b", ts="2026-01-01T10:00:00+00:00"))
    assert ok.accepted


def test_session_full_day_is_noop():
    pipe, _ = _pipe(session_start=0, session_end=24)
    assert pipe.process(_alert(ts="2026-01-01T03:00:00+00:00")).accepted


def test_daily_loss_kill_switch_blocks_after_limit():
    pipe, paper = _pipe(max_daily_loss_pct=0.05)   # halt at -$500 today
    pipe.process(_alert(aid="o1", entry=100, stop=90))
    pipe.process(_alert(aid="c1", symbol="BTCUSDT", side="CLOSE", entry=40, stop=None))
    assert paper.realized_pnl() < -500
    # today's loss exceeds the limit -> new entry blocked
    blocked = pipe.process(_alert(aid="o2", symbol="ETHUSDT"))
    assert not blocked.accepted and blocked.stage == "daily_loss"


def test_daily_loss_is_per_utc_day():
    # the helper only counts trades closed on the given day -> resets next day
    trades = [{"pnl": -600, "closed_at": "2026-01-01T10:00:00+00:00"},
              {"pnl": -50, "closed_at": "2026-01-02T10:00:00+00:00"}]
    assert SignalPipeline._pnl_on_day(trades, "2026-01-01") == -600
    assert SignalPipeline._pnl_on_day(trades, "2026-01-02") == -50
    assert SignalPipeline._pnl_on_day(trades, "2026-01-03") == 0


def test_daily_loss_disabled_by_default():
    pipe, paper = _pipe()  # max_daily_loss_pct defaults to 0 -> disabled
    pipe.process(_alert(aid="o1", entry=100, stop=90))
    pipe.process(_alert(aid="c1", symbol="BTCUSDT", side="CLOSE", entry=40, stop=None))
    assert pipe.process(_alert(aid="o2", symbol="ETHUSDT")).accepted
