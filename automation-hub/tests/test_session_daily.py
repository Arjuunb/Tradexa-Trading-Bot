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


def test_max_trades_per_day():
    pipe, paper = _pipe(max_trades_per_day=1)
    assert pipe.process(_alert(aid="o1", symbol="BTCUSDT")).accepted
    # second open today -> blocked
    res = pipe.process(_alert(aid="o2", symbol="ETHUSDT"))
    assert not res.accepted and res.stage == "max_trades"


def test_consecutive_loss_auto_halt():
    pipe, paper = _pipe(max_consecutive_losses=2)
    # two losing round-trips
    for sym, n in (("BTCUSDT", "1"), ("ETHUSDT", "2")):
        pipe.process(_alert(aid="o" + n, symbol=sym, entry=100, stop=90))
        pipe.process(_alert(aid="c" + n, symbol=sym, side="CLOSE", entry=40, stop=None))
    # third entry -> auto-halted after 2 consecutive losses
    res = pipe.process(_alert(aid="o3", symbol="SOLUSDT"))
    assert not res.accepted and res.stage == "risk_guard"
    assert pipe.halted and "consecutive" in pipe.halt_reason.lower()


def test_cooldown_after_loss():
    pipe, paper = _pipe(cooldown_after_loss_min=60)
    pipe.process(_alert(aid="o1", symbol="BTCUSDT", entry=100, stop=90))
    pipe.process(_alert(aid="c1", symbol="BTCUSDT", side="CLOSE", entry=40, stop=None))
    # the loss just closed (wall-clock now) -> still in cooldown
    res = pipe.process(_alert(aid="o2", symbol="ETHUSDT"))
    assert not res.accepted and res.stage == "cooldown"


def test_weekly_loss_limit():
    pipe, paper = _pipe(max_weekly_loss_pct=0.05)
    pipe.process(_alert(aid="o1", symbol="BTCUSDT", entry=100, stop=90))
    pipe.process(_alert(aid="c1", symbol="BTCUSDT", side="CLOSE", entry=40, stop=None))
    res = pipe.process(_alert(aid="o2", symbol="ETHUSDT"))
    assert not res.accepted and res.stage == "weekly_loss"


def test_trading_days_guard():
    # mask with only Monday (bit0) allowed = 1
    pipe, paper = _pipe(trading_days_mask=1)
    # 2026-01-01 is a Thursday (weekday 3) -> blocked
    res = pipe.process(_alert(aid="o1", ts="2026-01-01T10:00:00+00:00"))
    assert not res.accepted and res.stage == "trading_day"
    # 2026-01-05 is a Monday (weekday 0) -> allowed
    ok = pipe.process(_alert(aid="o2", ts="2026-01-05T10:00:00+00:00"))
    assert ok.accepted


def test_trading_days_all_is_noop():
    pipe, _ = _pipe(trading_days_mask=127)
    assert pipe.process(_alert(aid="o1", ts="2026-01-01T10:00:00+00:00")).accepted
