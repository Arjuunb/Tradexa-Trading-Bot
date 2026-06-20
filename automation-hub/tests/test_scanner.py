"""Market scanner: detectors fire on crafted bars; scan ranks real opportunities."""
from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Bar
from services.scanner import scan_bars, scan, SETUP_TYPES


def _bars(closes, vols=None, spread=0.002):
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        v = (vols[i] if vols else 1000.0)
        out.append(Bar(t0 + timedelta(hours=i), prev, c * (1 + spread), c * (1 - spread), c, v))
        prev = c
    return out


def _types(sigs):
    return {s["type"] for s in sigs}


def test_breakout_long_detected():
    # 60 flat bars then a decisive break above the range
    closes = [100 + (i % 3) * 0.2 for i in range(60)] + [108.0]
    sigs = scan_bars(_bars(closes))
    bo = [s for s in sigs if s["type"] == "Breakout"]
    assert bo and bo[0]["side"] == "long" and bo[0]["strength"] > 0


def test_breakout_short_detected():
    closes = [100 - (i % 3) * 0.2 for i in range(60)] + [90.0]
    sigs = scan_bars(_bars(closes))
    bo = [s for s in sigs if s["type"] == "Breakout"]
    assert bo and bo[0]["side"] == "short"


def test_high_volume_detected():
    closes = [100 + (i % 2) * 0.1 for i in range(60)] + [100.2]
    vols = [1000.0] * 60 + [4000.0]                     # last bar 4x volume
    sigs = scan_bars(_bars(closes, vols=vols))
    assert "High volume" in _types(sigs)


def test_strong_uptrend_gives_momentum_or_trend():
    closes = [100 + i * 0.7 for i in range(61)]         # clean uptrend
    sigs = scan_bars(_bars(closes))
    assert _types(sigs) & {"Strong momentum", "Trend continuation"}
    assert all(0 <= s["strength"] <= 100 for s in sigs)
    # an uptrend should read long
    assert any(s["side"] == "long" for s in sigs)


def test_no_signals_when_too_short():
    assert scan_bars(_bars([100 + i for i in range(10)])) == []


def test_setup_types_catalog():
    assert set(SETUP_TYPES) == {"Breakout", "Liquidity sweep", "High volume",
                                "Strong momentum", "Trend continuation", "Pullback"}


def test_scan_ranks_opportunities_real_data():
    r = scan(["BTCUSDT", "ETHUSDT", "SOLUSDT"], timeframe="4h", bars=300)
    assert "opportunities" in r and "symbols" in r
    # symbols available from the seeded store, ranked by score
    avail = [s for s in r["symbols"] if s["available"]]
    assert avail
    scores = [s["score"] for s in r["symbols"]]
    assert scores == sorted(scores, reverse=True)
    # opportunities ranked by strength, strongest first
    if len(r["opportunities"]) > 1:
        assert r["opportunities"][0]["strength"] >= r["opportunities"][-1]["strength"]


def test_scan_type_filter():
    r = scan(["BTCUSDT", "ETHUSDT"], timeframe="4h", bars=300, types=["Breakout"])
    for s in r["symbols"]:
        for sig in s["signals"]:
            assert sig["type"] == "Breakout"


# ───────────────────────── endpoint ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_scanner_endpoint(client):
    body = client.get("/scanner/scan", params={"symbols": "BTCUSDT,ETHUSDT", "timeframe": "4h"}).json()
    assert "opportunities" in body and "symbols" in body and "count" in body
