"""Tier 1 — trust: deep backfill, data integrity, real-data validation,
live-vs-backtest track record, persistent storage visibility."""
import time
from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Bar
from data.backfill import BackfillJob, deep_backfill
from data.historical import HistoricalStore
from data.integrity import verify, verify_store
from services.track_record import MIN_TRADES, _live_stats, compare

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _fake_fetcher(rows_total=2500):
    """Serves a deterministic 1h kline history, newest page first like Binance."""
    start_ms = int(T0.timestamp() * 1000)
    all_rows = [[start_ms + i * 3_600_000, 100 + i * 0.01, 101 + i * 0.01,
                 99 + i * 0.01, 100.5 + i * 0.01, 5.0] for i in range(rows_total)]

    def fetcher(symbol, interval, *, limit=1000, end_ms=None, start_ms=None):
        rows = all_rows
        if end_ms is not None:
            rows = [r for r in rows if r[0] <= end_ms]
        if start_ms is not None:
            rows = [r for r in rows if r[0] >= start_ms]
        return rows[-limit:]
    return fetcher


# ─────────────────────────── deep backfill ───────────────────────────
def test_deep_backfill_targets_years_of_candles(tmp_path):
    store = HistoricalStore(str(tmp_path / "m.db"))
    res = deep_backfill(store, "BTCUSDT", "1h", years=0.2, fetcher=_fake_fetcher())
    assert "error" not in res
    assert res["stored"] >= 0.2 * 8760 * 0.95          # ~a fifth of a year of 1h
    assert store.coverage("BTCUSDT", "1h")["candles"] == res["stored"]


def test_backfill_job_runs_matrix_with_progress(tmp_path):
    store = HistoricalStore(str(tmp_path / "m.db"))
    job = BackfillJob(store)
    res = job.start(symbols=("BTCUSDT", "ETHUSDT"), timeframes=("1h",),
                    years=0.05, fetcher=_fake_fetcher())
    assert res["started"] and res["total"] == 2
    for _ in range(100):
        if not job.status()["running"]:
            break
        time.sleep(0.05)
    st = job.status()
    assert st["running"] is False and st["done"] == 2 and st["succeeded"] == 2
    # second start while finished is allowed; while running it is refused
    assert job.start(symbols=("BTCUSDT",), timeframes=("1h",), years=0.01,
                     fetcher=_fake_fetcher())["started"] is True


# ─────────────────────────── integrity ───────────────────────────
def _bars(n, gap_at=None, dup_at=None, bad_at=None, tf_h=1):
    out = []
    t = T0
    for i in range(n):
        if gap_at is not None and i == gap_at:
            t += timedelta(hours=3 * tf_h)             # skip candles
        o, h, l, c = 100.0, 101.0, 99.0, 100.5
        if bad_at is not None and i == bad_at:
            h, l = 99.0, 101.0                          # broken OHLC
        out.append(Bar(t, o, h, l, c, 1.0))
        if dup_at is not None and i == dup_at:
            out.append(Bar(t, o, h, l, c, 1.0))         # duplicate timestamp
        t += timedelta(hours=tf_h)
    return out


def test_integrity_clean_series_is_ok():
    r = verify(_bars(200), "1h")
    assert r["verdict"] == "ok" and r["gaps"] == [] and r["missing_total"] == 0


def test_integrity_detects_gaps_duplicates_and_bad_candles():
    gappy = verify(_bars(400, gap_at=100), "1h")
    assert gappy["missing_total"] == 3 and gappy["gaps"]
    assert gappy["verdict"] in ("warning", "bad")
    assert verify(_bars(100, dup_at=50), "1h")["verdict"] == "bad"
    assert verify(_bars(100, bad_at=10), "1h")["verdict"] == "bad"
    assert verify([], "1h")["verdict"] == "empty"


def test_integrity_store_sweep(tmp_path):
    store = HistoricalStore(str(tmp_path / "m.db"))
    deep_backfill(store, "BTCUSDT", "1h", years=0.05, fetcher=_fake_fetcher())
    rep = verify_store(store, ("BTCUSDT",), ("1h",))
    assert rep["verdict"] == "ok" and rep["series"][0]["candles"] > 0


# ─────────────────────────── validation honesty ───────────────────────────
def test_validation_refuses_without_real_data(monkeypatch, tmp_path):
    # point the local store at an empty db -> validation must say no-real-data
    import config
    monkeypatch.setattr(config.settings, "market_db", str(tmp_path / "empty.db"))
    monkeypatch.setenv("HUB_REQUIRE_REAL_DATA", "1")
    from services.validation import validate_real
    rep = validate_real("Decision Brain", symbols=("BTCUSDT",), timeframe="1h")
    assert rep["overall"] == "no-real-data"
    assert "backfill" in rep["detail"].lower()


# ─────────────────────────── track record ───────────────────────────
def _trades(rrs):
    return [{"status": "closed", "rr": r, "pnl": r * 100} for r in rrs]


def test_live_stats_and_insufficient_sample():
    assert _live_stats([])["trades"] == 0
    v = compare(_live_stats(_trades([1.0] * 5)), {"trades": 100, "win_rate": 40})
    assert v["verdict"] == "insufficient-live-trades"


def test_track_record_verdicts():
    expected = {"trades": 200, "win_rate": 40.0, "expectancy_r": 0.5}
    good = _live_stats(_trades([3.0] * 9 + [-1.0] * 11))     # 45% win, +0.6R
    assert compare(good, expected)["verdict"] == "on-track"
    bad = _live_stats(_trades([-1.0] * 16 + [3.0] * 4))      # negative expectancy
    assert compare(bad, expected)["verdict"] == "diverging"


# ─────────────────────────── endpoints + storage ───────────────────────────
def test_tier1_endpoints(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    assert client.post("/data/backfill").status_code == 401       # secret required
    assert client.get("/data/backfill/status").json()["running"] is False
    integ = client.get("/data/integrity", params={"timeframes": "1h"}).json()
    assert "verdict" in integ and "series" in integ
    tr = client.get("/performance/track-record").json()
    assert "live" in tr and "verdict" in tr
    st = client.get("/ops/storage").json()
    assert "files" in st and "persistent" in st
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("HUB_DATA_DIR", raising=False)
    st2 = client.get("/ops/storage").json()
    assert st2["persistent"] is False and "EPHEMERAL" in st2["warning"]