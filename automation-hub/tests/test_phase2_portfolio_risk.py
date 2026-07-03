"""Phase 2 — portfolio-level risk: correlation guard, total exposure cap,
equity-curve throttle."""
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline, _cluster


def _pipe(paper, led, **kw):
    kw.setdefault("equity", 10_000)
    kw.setdefault("risk_per_trade_pct", 0.01)
    return SignalPipeline(led, paper, TradingControl(), **kw)


def _open(pipe, sym, side="BUY", entry=100.0, stop=95.0, alert="a"):
    return pipe.process({"alert_id": f"{alert}-{sym}-{side}", "symbol": sym,
                         "side": side, "entry": entry, "stop": stop,
                         "confidence": 1.0})


def test_cluster_map():
    assert _cluster("BTCUSDT") == "crypto"
    assert _cluster("SOL/USDC") == "crypto"
    assert _cluster("EURJPY") == "other"


def test_correlation_guard_blocks_third_same_direction_crypto_long():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    # generous exposure caps so ONLY the correlation guard is under test
    pipe = _pipe(paper, led, max_open_positions=5, max_total_exposure_pct=0.5)
    assert _open(pipe, "BTCUSDT").accepted
    assert _open(pipe, "ETHUSDT").accepted
    r3 = _open(pipe, "SOLUSDT")            # 3rd correlated long -> blocked
    assert not r3.accepted and r3.stage == "correlation"
    # the opposite direction is NOT correlated exposure — still allowed
    assert _open(pipe, "XRPUSDT", side="SELL", entry=100, stop=105).accepted


def test_correlation_guard_disabled_with_zero():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = _pipe(paper, led, max_open_positions=5, max_correlated_positions=0,
                 max_total_exposure_pct=0.5, exposure_limit_pct=0.10)
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"):
        assert _open(pipe, sym).accepted


def test_total_exposure_cap_limits_the_book():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    # per-trade cap 5% x2 positions = 10% -> the 10% portfolio cap is binding
    pipe = _pipe(paper, led, max_open_positions=5, max_correlated_positions=0,
                 exposure_limit_pct=0.05, max_total_exposure_pct=0.10)
    a = _open(pipe, "BTCUSDT")
    b = _open(pipe, "ETHUSDT")
    assert a.accepted and b.accepted
    c = _open(pipe, "SOLUSDT")             # book is full -> rejected outright
    assert not c.accepted and c.stage == "portfolio_exposure"
    total = sum(p["size"] * p["entry"] for p in paper.positions())
    assert total <= 0.10 * 10_000 + 1e-6


def test_total_exposure_cap_trims_partial_budget():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    # one 5% position leaves a 3% budget under an 8% cap -> next size is trimmed
    pipe = _pipe(paper, led, max_open_positions=5, max_correlated_positions=0,
                 exposure_limit_pct=0.05, max_total_exposure_pct=0.08)
    assert _open(pipe, "BTCUSDT").accepted
    r = _open(pipe, "ETHUSDT")
    assert r.accepted
    total = sum(p["size"] * p["entry"] for p in paper.positions())
    assert total <= 0.08 * 10_000 + 1e-6


def _seed(paper, pnls):
    for i, pnl in enumerate(pnls):
        sym = f"Q{i}USDT"
        paper.open(symbol=sym, side="BUY", size=1.0, entry=100, stop=99)
        paper.close(symbol=sym, exit_price=100 + pnl)


def test_equity_curve_throttle_halves_risk_in_drawdown():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = _pipe(paper, led)
    _seed(paper, [5.0] * 10 + [-8.0] * 5)   # rally, then a slide below the average
    assert pipe._equity_curve_factor() == 0.5
    led2 = SqliteLedger(":memory:")
    paper2 = PaperExecutionEngine(led2)
    pipe2 = _pipe(paper2, led2)
    _seed(paper2, [2.0] * 12)                # steadily rising curve -> full size
    assert pipe2._equity_curve_factor() == 1.0
    led3 = SqliteLedger(":memory:")
    paper3 = PaperExecutionEngine(led3)
    pipe3 = _pipe(paper3, led3)
    _seed(paper3, [2.0] * 5)                 # not enough history -> untouched
    assert pipe3._equity_curve_factor() == 1.0
