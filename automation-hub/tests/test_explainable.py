"""Explainable Trading layer: every analysis cycle produces a complete
Decision Report (never a silent trade OR a silent skip), the market analysis
is honest, MFE/MAE lifecycle telemetry is recorded, and the AI Coach debriefs
every completed trade from its real entry reads."""
from datetime import datetime, timedelta, timezone

from bot.data.synthetic import generate_bars
from bot.types import Bar
from data.cycle_store import CycleStore
from data.journal_store import JournalStore
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.auto_engine import AutoStrategyEngine
from services.controls import TradingControl
from services.decision_journal import DecisionJournal, build_coach
from services.market_analysis import analyze
from services.signal_pipeline import SignalPipeline
from services.trade_manager import ManagedTrade, TradeManager
from strategies.brain_strategy import DecisionBrain

TS = datetime(2026, 1, 5, tzinfo=timezone.utc)


def _bar(i, o, h, l, c, v=1000.0):
    return Bar(TS + timedelta(minutes=5 * i), o, h, l, c, v)


# ───────────────────────────── market analysis ─────────────────────────────
def test_analysis_honest_below_minimum_history():
    bars = [_bar(i, 100, 101, 99, 100) for i in range(10)]
    ma = analyze(bars)
    assert ma["available"] is False and "insufficient" in ma["note"]


def test_analysis_reads_a_clean_uptrend():
    # constructed stair-step uptrend (GBM seeds can end mid-pullback): rising
    # closes with small oscillation so pivots (HH/HL) actually form
    import math
    bars = []
    for i in range(160):
        base = 100 * (1.002 ** i)                    # steady climb…
        wig = math.sin(i * 0.5) * base * 0.015       # …with real pullbacks so
        c = base + wig                               # pivot highs AND lows form
        bars.append(_bar(i, c * 0.999, c * 1.004, c * 0.996, c))
    ma = analyze(bars)
    assert ma["available"]
    assert ma["bias"] == "Bullish"
    assert ma["trend"]["ema8_vs_ema33"] == "above"
    assert ma["structure"]["state"] in ("trending up", "transitional")
    # zones + levels are real dicts with distances
    assert isinstance(ma["zones"]["demand"], dict)
    assert "distance_pct" in ma["zones"]["demand"]
    assert ma["volatility"]["label"] in ("low", "medium", "high")


def test_analysis_detects_equal_highs_and_sweep():
    # two equal pivot highs at 110, then a wick through that closes back below
    bars = []
    i = 0
    def flat(n, px=100):
        nonlocal i
        for _ in range(n):
            bars.append(_bar(i, px, px + 0.2, px - 0.2, px)); i += 1
    def spike_high(top):
        nonlocal i
        bars.append(_bar(i, 100, top, 99.8, 100.2)); i += 1
    flat(20); spike_high(110); flat(8); spike_high(110.05); flat(8)
    bars.append(_bar(i, 100, 111.5, 99.9, 100.1))  # sweep: wick above, close below
    i += 1
    flat(4)
    ma = analyze(bars)
    assert ma["available"]
    assert ma["liquidity"]["equal_highs"], "expected equal highs detected"
    assert "swept equal highs" in ma["liquidity"]["sweep"]


# ─────────────────────────── per-cycle reports ───────────────────────────
def _engine_with_reports(seed=11, drift=0.0006):
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000)
    eng = AutoStrategyEngine(pipe, paper, led, symbols=["BTCUSDT"], timeframe="5m",
                             strategy_factory=lambda s: DecisionBrain(s),
                             entry_mode="market")
    eng.reports = CycleStore(":memory:")
    strat = DecisionBrain("BTCUSDT")
    for bar in generate_bars(n=700, timeframe="5m", drift_per_bar=drift,
                             vol_per_bar=0.006, seed=seed):
        eng._process_bar("BTCUSDT", bar, strat)
    return eng


def test_every_cycle_is_reported_even_wait():
    eng = _engine_with_reports()
    assert eng.reports.count() == 700          # one report per bar, no gaps
    waits = eng.reports.list(limit=500, decision="WAIT")
    assert waits, "WAIT cycles must be reported, not silent"
    full = eng.reports.get(waits[0]["id"])["report"]
    assert full["reasons"], "a WAIT must explain itself"
    assert full["recommendation"]
    assert len(full["checklist"]) == 8
    assert 0 <= full["scores"]["total"] <= 100


def test_trade_cycles_carry_gate_reasons_and_score_categories():
    eng = _engine_with_reports()
    trades = eng.reports.list(limit=500, decision="BUY")
    assert trades, "expected at least one BUY in a drifting-up scenario"
    full = eng.reports.get(trades[0]["id"])["report"]
    assert any("Quality gate" in r or "conviction" in r for r in full["reasons"])
    s = full["scores"]
    for cat in ("trend", "structure", "supply_demand", "volume", "risk"):
        assert 0 <= s[cat] <= 20
    assert s["label"] in ("strong", "watchlist", "skip-quality")


def test_cycle_store_prunes_to_cap():
    store = CycleStore(":memory:", keep=50)
    for i in range(120):
        store.record({"ts": f"2026-01-01T00:{i:02d}:00", "symbol": "X",
                      "timeframe": "5m", "price": 1.0, "decision": "WAIT",
                      "score": 50})
    assert store.count() <= 51                # cap enforced (±1 on the boundary)


# ─────────────────────── lifecycle telemetry (MFE/MAE) ───────────────────────
def test_managed_trade_tracks_mfe_and_mae():
    mt = ManagedTrade(side="long", entry=100.0, stop=95.0, target=115.0, risk=5.0)
    tm = TradeManager()
    tm.on_bar(mt, high=104.0, low=98.0, close=103.0)   # +0.8R fav, -0.4R adverse
    tm.on_bar(mt, high=108.0, low=101.0, close=107.0)  # +1.6R fav
    assert mt.mfe == 108.0 and mt.mae == 98.0
    mfe_r, mae_r = AutoStrategyEngine._mfe_mae_r(mt)
    assert abs(mfe_r - 1.6) < 1e-9
    assert abs(mae_r - 0.4) < 1e-9


def test_journal_records_lifecycle_and_coach():
    store = JournalStore(":memory:")
    journal = DecisionJournal(store)
    journal.record_entry(
        trade_id="T1", mode="paper", symbol="BTCUSDT", side="long",
        strategy="Decision Brain", timeframe="5m", entry=100.0, stop=95.0,
        target=115.0, size=1.0, equity=10_000, confidence=0.8, brain_score=75,
        regime="Trending", steps=[],
        payload={"brain_checklist": [
            {"name": "EMA trend", "status": "Passed", "detail": "EMA12>EMA26"},
            {"name": "RSI confirmation", "status": "Failed", "detail": "RSI 48"}]})
    out = journal.record_exit(trade_id="T1", exit_price=115.0, pnl=15.0,
                              exit_reason="take-profit", mfe_r=3.1, mae_r=0.6)
    j = store.get("T1")
    ex = j["sections"]["exit_decision"]
    assert ex["max_profit_r"] == 3.1 and ex["max_drawdown_r"] == 0.6
    coach = j["sections"]["review"]["coach"]
    assert coach["strengths"] and coach["weaknesses"] and coach["lesson"]
    assert coach["rating"][0] in "ABCDF"
    assert out is not None


def test_untracked_position_reports_not_tracked_honestly():
    store = JournalStore(":memory:")
    journal = DecisionJournal(store)
    journal.record_entry(trade_id="T2", mode="paper", symbol="ETHUSDT", side="long",
                         strategy="EMA", timeframe="5m", entry=100.0, stop=95.0,
                         target=110.0, size=1.0, equity=10_000, confidence=0.7,
                         brain_score=None, regime="Trending", steps=[], payload={})
    journal.record_exit(trade_id="T2", exit_price=95.0, pnl=-5.0, exit_reason="stop-loss")
    ex = store.get("T2")["sections"]["exit_decision"]
    assert ex["max_profit_r"] == "not tracked"
    assert ex["max_drawdown_r"] == "not tracked"


def test_coach_debriefs_from_real_reads():
    review = {"improvement": "Wait for deeper pullbacks before entering.",
              "grade": "A"}
    sections = {"checklist": {"entry_reads": [
        {"rule": "EMA trend", "ok": True, "detail": "aligned"},
        {"rule": "Volume", "ok": False, "detail": "below average"}]}}
    coach = build_coach(sections, review, "win", actual_rr=2.4, planned_rr=3.0,
                        risk_ok=True)
    assert any("EMA trend" in s for s in coach["strengths"])
    assert any("Volume" in w for w in coach["weaknesses"])
    assert coach["lesson"].startswith("Wait for deeper")
    assert coach["rating"] == "A+"
