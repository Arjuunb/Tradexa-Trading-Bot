"""Round-5 refinements: measured time stop, side-leak lesson, per-symbol
retune."""
from datetime import datetime, timedelta, timezone

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.learning import LearningBook, classify
from services.signal_pipeline import SignalPipeline
from services.trade_manager import ManagedTrade, TradeManager

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ─────────────────────────── time stop ───────────────────────────
def test_time_stop_exits_stale_position_at_close():
    mgr = TradeManager(max_hold_bars=3)
    t = ManagedTrade(side="long", entry=100, stop=95, target=115, risk=5)
    assert mgr.on_bar(t, high=101, low=99, close=100.5).exit_price is None
    assert mgr.on_bar(t, high=101, low=99, close=100.2).exit_price is None
    act = mgr.on_bar(t, high=101, low=99, close=100.8)
    assert act.exit_price == 100.8 and act.exit_reason == "time"


def test_time_stop_never_preempts_stop_or_target():
    mgr = TradeManager(max_hold_bars=1)
    t = ManagedTrade(side="long", entry=100, stop=95, target=115, risk=5)
    act = mgr.on_bar(t, high=101, low=94, close=96)      # stop hit on the same bar
    assert act.exit_reason == "stop"


def test_default_time_stop_is_the_measured_150():
    assert TradeManager().max_hold_bars == 150


# ─────────────────────────── side-leak lesson ───────────────────────────
def _trade(i, side, rr):
    return {"symbol": "BTCUSDT", "side": side, "rr": rr, "pnl": rr * 10,
            "status": "closed", "alert_id": f"s{i}",
            "opened_at": (TS + timedelta(hours=5 * i)).isoformat(),
            "closed_at": (TS + timedelta(hours=5 * i + 2)).isoformat()}


def _asymmetric_history():
    trades = [_trade(i, "long", 2.0) for i in range(8)]          # longs earn
    trades += [_trade(20 + i, "short", -1.0) for i in range(9)]  # shorts bleed
    return trades


def test_classify_finds_the_leaking_side():
    kinds = {f["kind"]: f for f in classify(_asymmetric_history())}
    assert kinds["side-leak"]["key"] == "short"
    assert "halve short size" in kinds["side-leak"]["lesson"]
    # balanced record -> no side lesson
    balanced = [_trade(i, "long", 1.0) for i in range(8)] + \
               [_trade(20 + i, "short", 1.0) for i in range(8)]
    assert "side-leak" not in {f["kind"] for f in classify(balanced)}


def test_book_and_pipeline_halve_the_leaking_side():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5,
                          max_total_exposure_pct=1.0,
                          adaptive_risk=False, equity_throttle=False)
    pipe.learning = LearningBook()
    pipe.learning.update(list(reversed(_asymmetric_history())), now=TS)
    assert pipe.learning.side_multiplier("short") == 0.5
    assert pipe.learning.side_multiplier("long") == 1.0
    r = pipe.process({"alert_id": "sl1", "symbol": "ETHUSDT", "side": "SELL",
                      "entry": 100.0, "stop": 105.0, "confidence": 1.0})
    assert r.accepted
    detail = next(s for s in r.steps if s.rule == "risk").detail
    assert "side 0.50" in detail
    assert abs(r.fill["size"] - 10.0) < 0.3     # half of the normal 20
    r2 = pipe.process({"alert_id": "sl2", "symbol": "BTCUSDT", "side": "BUY",
                       "entry": 100.0, "stop": 95.0, "confidence": 1.0})
    assert r2.accepted and "side" not in next(
        s for s in r2.steps if s.rule == "risk").detail


# ─────────────────────────── per-symbol retune ───────────────────────────
def test_per_symbol_retune_structure():
    from services.retune import evaluate_per_symbol
    rep = evaluate_per_symbol(symbols=("ZZZUSDT",), timeframe="1h",
                              bars=2600, require_real=False)
    assert rep["available"] is True
    assert rep["verdict"] in ("candidate-found", "keep-incumbent")
    sym = rep["per_symbol"]["ZZZUSDT"]
    assert sym["verdict"] in ("candidate-found", "keep-incumbent")
    assert "best" in sym
    for s, p in rep["winners"].items():
        assert rep["per_symbol"][s]["verdict"] == "candidate-found"
        assert set(p) == {"conviction_threshold", "rr_target"}


def test_per_symbol_retune_honest_without_data(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config.settings, "market_db", str(tmp_path / "empty.db"))
    monkeypatch.setenv("HUB_REQUIRE_REAL_DATA", "1")
    from services.retune import evaluate_per_symbol
    rep = evaluate_per_symbol(symbols=("BTCUSDT",), timeframe="1h")
    assert rep["available"] is False and rep["verdict"] == "no-real-data"


def test_retune_builds_per_symbol_shadow(monkeypatch):
    from services import retune as rt

    class _Eng:
        symbols = ["BTCUSDT", "ETHUSDT"]
        shadow = None
    eng = _Eng()
    monkeypatch.setattr(rt, "evaluate_per_symbol", lambda **kw: {
        "available": True, "verdict": "candidate-found",
        "detail": "1 symbol has a validated config",
        "winners": {"ETHUSDT": {"conviction_threshold": 0.62, "rr_target": 2.5}},
        "per_symbol": {}, "incumbent": rt.INCUMBENT})
    res = rt.retune(eng, None, force=True)
    assert res["verdict"] == "candidate-found"
    assert "ETHUSDT" in eng.shadow.name
    # winner gets its own params; the other symbol keeps the incumbent
    assert eng.shadow._strats["ETHUSDT"].params["conviction_threshold"] == 0.62
    assert eng.shadow._strats["BTCUSDT"].params["conviction_threshold"] == 0.56