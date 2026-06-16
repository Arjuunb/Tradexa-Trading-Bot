"""Automatic capital protection: drawdown circuit breaker + position cap."""
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline


def _pipe(*, max_drawdown_pct=0.20, max_open_positions=3):
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, 10_000)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5,
                          max_drawdown_pct=max_drawdown_pct,
                          max_open_positions=max_open_positions)
    return pipe, paper, led


def _open(pipe, symbol="BTCUSDT", entry=100, stop=90, aid="o"):
    return pipe.process({"alert_id": aid, "symbol": symbol, "side": "BUY",
                         "entry": entry, "stop": stop})


def test_drawdown_breaker_halts_new_entries_after_big_loss():
    pipe, paper, led = _pipe(max_drawdown_pct=0.05)
    assert _open(pipe, aid="o1").accepted              # opens ~10 units @100
    # close at a heavy loss (-600 = 6% > 5% drawdown limit)
    closed = pipe.process({"alert_id": "c1", "symbol": "BTCUSDT", "side": "CLOSE", "entry": 40})
    assert closed.accepted and closed.reason == "position closed"
    assert pipe.halted and "drawdown" in pipe.halt_reason.lower()

    # a NEW entry is now auto-rejected
    res = _open(pipe, symbol="ETHUSDT", aid="o2")
    assert not res.accepted and res.stage == "risk_guard" and "Auto-halt" in res.reason
    # a critical risk alert was raised
    alerts = [a for a in led.get_alerts() if a["severity"] == "critical"]
    assert alerts and "Auto-halt" in alerts[0]["title"]


def test_resume_clears_auto_halt():
    pipe, paper, _ = _pipe(max_drawdown_pct=0.05)
    _open(pipe, aid="o1")
    pipe.process({"alert_id": "c1", "symbol": "BTCUSDT", "side": "CLOSE", "entry": 40})
    assert pipe.halted
    pipe.resume()
    assert not pipe.halted
    assert _open(pipe, symbol="ETHUSDT", aid="o2").accepted   # entries allowed again


def test_exits_are_never_blocked_when_halted():
    pipe, paper, _ = _pipe(max_drawdown_pct=0.05)
    _open(pipe, symbol="BTCUSDT", aid="o1")
    _open(pipe, symbol="ETHUSDT", aid="o2")
    # force a halt
    pipe._engage_halt("test halt")
    assert pipe.halted
    # closing an open position still works (safety: exits never blocked)
    res = pipe.process({"alert_id": "c", "symbol": "BTCUSDT", "side": "CLOSE", "entry": 105})
    assert res.accepted and res.reason == "position closed"


def test_max_open_positions_cap():
    pipe, paper, _ = _pipe(max_open_positions=2)
    assert _open(pipe, symbol="BTCUSDT", aid="a").accepted
    assert _open(pipe, symbol="ETHUSDT", aid="b").accepted
    res = _open(pipe, symbol="SOLUSDT", aid="c")        # 3rd -> capped
    assert not res.accepted and res.stage == "risk_guard" and "Max open positions" in res.reason
    assert len(paper.positions()) == 2
