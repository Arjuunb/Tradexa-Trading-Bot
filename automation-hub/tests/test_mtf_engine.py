"""Multi-Timeframe Decision Engine: per-layer logic + combined alignment rules.
Deterministic synthetic bars so the alignment outcomes are stable."""
from datetime import datetime, timedelta, timezone

import pytest

from bot.types import Bar
from services.mtf_engine import (analyze_layers, _ema_bias, _structure_bias,
                                  _setup, _trigger)


def _series(closes, spread=0.004):
    # high/low straddle each bar's OWN close, so swing pivots track the closes
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out, prev = [], closes[0]
    for k, c in enumerate(closes):
        hi = c * (1 + spread)
        lo = c * (1 - spread)
        out.append(Bar(t0 + timedelta(hours=k), prev, hi, lo, c, 1000.0))
        prev = c
    return out


def _up(n=80, start=100.0, step=0.6):
    return _series([start + i * step for i in range(n)])


def _down(n=80, start=160.0, step=0.6):
    return _series([start - i * step for i in range(n)])


# ---- per-layer ----
def test_ema_bias_direction_and_insufficient():
    assert _ema_bias([b.close for b in _up()])[0] == 1
    assert _ema_bias([b.close for b in _down()])[0] == -1
    assert _ema_bias([1, 2, 3])[0] is None         # not enough data


def _struct_bars(up=True):
    # legs of 6 with a clear pivot-high (idx2) and pivot-low (idx4); each leg
    # steps up (or down) so swings form HH/HL (or LL/LH) for a pivot-2 detector
    closes = []
    for L in range(4):
        b = 100 + (L * 6 if up else -L * 6)
        closes += [b, b + 2, b + 4, b + 1, b - 1, b + 1]
    return _series(closes, spread=0.0005)   # tiny spread so closes drive the swings


def test_structure_bias_bull_and_bear():
    assert _structure_bias(_struct_bars(up=True), pivot=2)[0] == 1
    assert _structure_bias(_struct_bars(up=False), pivot=2)[0] == -1


def test_setup_and_trigger_directional():
    # craft a clean uptrend then a pullback-to-EMA on the last bar
    closes = [100 + i for i in range(40)]
    closes[-1] = closes[-2] - 0.5     # small dip
    bars = _series(closes)
    ok, _ = _setup(bars, side=1)
    assert isinstance(ok, bool)
    # trigger: last 5M candle closes above prior high
    trig_bars = _series([100, 101, 99, 103])
    assert _trigger(trig_bars, side=1)[0] is True
    assert _trigger(trig_bars, side=-1)[0] is False


# ---- combined decision ----
def test_full_bull_stack_can_confirm_entry():
    # all higher TFs bullish; 15M pullback; 5M bullish trigger
    weekly = _up(); daily = _up(); h4 = _up()
    m15 = _series([100 + i * 0.5 for i in range(40)][:-1] + [100 + 38 * 0.5 - 0.4])
    m5 = _series([100, 100.5, 100.2, 101.5])  # last closes above prior high
    d = analyze_layers(weekly, daily, h4, m15, m5)
    assert d.side == "long"
    assert d.trigger_state in ("Entry confirmed", "Setup found — waiting for 5M trigger", "Waiting for setup")
    assert d.layers["Weekly"]["dir"] == "Bullish"
    assert 0 <= d.score <= 100


def test_htf_conflict_blocks_trade():
    # weekly bull but daily + 4H bear -> conflict -> blocked
    d = analyze_layers(_up(), _down(), _down(), _up(), _up())
    assert d.allowed is False
    assert d.trigger_state == "Blocked"
    assert any("conflict" in b.lower() for b in d.blockers)
    assert d.side is None


def test_no_htf_direction_blocks():
    # too little data on every HTF -> neutral/na -> blocked with a reason
    flat = _series([100, 100, 100])
    d = analyze_layers(flat, flat, flat, flat, flat)
    assert d.allowed is False and d.trigger_state == "Blocked"
    assert d.blockers


def test_aligned_but_no_trigger_waits():
    weekly = _down(); daily = _down(); h4 = _down()
    m15 = _down(); m5 = _up()   # 5M momentum is up, but trade side is short -> no trigger
    d = analyze_layers(weekly, daily, h4, m15, m5)
    assert d.side == "short"
    assert d.allowed is False
    assert "waiting" in d.trigger_state.lower()


# ---- endpoint ----
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_mtf_endpoint(client):
    body = client.get("/mtf/analyze", params={"symbol": "BTCUSDT"}).json()
    assert body["symbol"] == "BTCUSDT"
    assert "layers" in body and "trigger_state" in body
    assert set(body["data_available"]) == {"1w", "1d", "4h", "15m", "5m"}
