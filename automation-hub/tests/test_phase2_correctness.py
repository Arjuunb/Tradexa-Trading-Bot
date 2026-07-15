"""Audit Phase 2 — correctness & performance.

H-4: process() is serialized so the position-cap check-then-open is atomic.
H-5: history() is cached (one ledger scan per process() call) + invalidated on writes.
M-9: a partial close records the actually-closed size on the closed row.
"""
import threading

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline


def _pipe(cap=3):
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=100_000)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=100_000,
                          max_open_positions=cap, exposure_limit_pct=1.0,
                          max_total_exposure_pct=1.0, adaptive_risk=False,
                          equity_throttle=False)
    return pipe, paper


# ─────────────────────────── H-4: position-cap race ───────────────────────────
def test_process_is_locked():
    pipe, _ = _pipe()
    assert isinstance(pipe._proc_lock, type(threading.RLock()))


def test_position_cap_holds_under_concurrent_signals():
    # fire more concurrent entries than the cap; the lock must keep opens <= cap
    pipe, paper = _pipe(cap=3)
    syms = [f"SYM{i}USDT" for i in range(12)]
    errors = []

    def fire(sym):
        try:
            pipe.process({"alert_id": f"a-{sym}", "symbol": sym, "side": "BUY",
                          "entry": 100.0, "stop": 95.0, "confidence": 1.0})
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=fire, args=(s,)) for s in syms]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"pipeline raised under concurrency: {errors}"
    assert len(paper.positions()) <= 3           # cap never breached


# ─────────────────────────── H-5: history cache ───────────────────────────
def test_history_cache_hits_and_invalidates(monkeypatch):
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000)
    calls = {"n": 0}
    real = led.get_paper_trades

    def counting():
        calls["n"] += 1
        return real()
    monkeypatch.setattr(led, "get_paper_trades", counting)

    paper.history(); paper.history(); paper.history()
    assert calls["n"] == 1                        # 3 reads -> 1 ledger scan (cached)

    # a write invalidates the cache
    paper.open(symbol="BTCUSDT", side="BUY", size=1.0, entry=100.0, stop=95.0)
    paper.history()
    assert calls["n"] == 2                        # re-scanned once after the write


def test_paper_trades_indexes_exist():
    led = SqliteLedger(":memory:")
    idx = [r["name"] for r in led._c.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='paper_trades'")]
    assert "idx_paper_status" in idx and "idx_paper_opened" in idx


# ─────────────────────────── M-9: partial-close size ───────────────────────────
def test_partial_close_records_closed_size():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000)
    paper.open(symbol="BTCUSDT", side="BUY", size=10.0, entry=100.0, stop=95.0)
    paper.reduce(symbol="BTCUSDT", exit_price=110.0, fraction=0.4)   # close 4, keep 6

    rows = led.get_paper_trades()
    closed = [r for r in rows if r["status"] == "closed"]
    open_rows = [r for r in rows if r["status"] == "open"]
    assert len(closed) == 1 and len(open_rows) == 1
    # the closed row shows the ACTUALLY-closed size (4), not the original 10
    assert abs(closed[0]["size"] - 4.0) < 1e-9
    assert abs(open_rows[0]["size"] - 6.0) < 1e-9
    # pnl on the closed row matches 4 units * (110-100) = 40
    assert abs((closed[0]["pnl"] or 0.0) - 40.0) < 1e-6


def test_full_close_size_unchanged():
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000)
    paper.open(symbol="ETHUSDT", side="BUY", size=5.0, entry=100.0, stop=95.0)
    paper.close(symbol="ETHUSDT", exit_price=120.0)
    closed = [r for r in led.get_paper_trades() if r["status"] == "closed"]
    assert len(closed) == 1 and abs(closed[0]["size"] - 5.0) < 1e-9   # full size intact
