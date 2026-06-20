"""Risk & Sizing engine: position sizing math, real correlation, portfolio VaR."""
import math

import pytest

from services.risk_engine import (position_size, correlation_matrix, pearson,
                                   correlation_conflicts, portfolio_risk, log_returns)


# ───────────────────────── position sizing (#4) ─────────────────────────
def test_percent_sizing_risks_exactly_the_target():
    r = position_size(equity=10_000, entry=100, stop=95, method="percent", risk_pct=0.01)
    # 1% of 10k = $100 risk over a $5 stop -> 20 units, $2000 notional
    assert r["dollar_risk"] == 100.0
    assert r["position_size"] == 20.0
    assert r["notional"] == 2000.0
    assert r["risk_pct_of_equity"] == 1.0


def test_fixed_and_atr_methods():
    fixed = position_size(equity=10_000, entry=100, stop=98, method="fixed", fixed_risk=50)
    assert fixed["dollar_risk"] == 50.0 and fixed["position_size"] == 25.0
    atr = position_size(equity=10_000, entry=100, side="long", method="atr",
                        atr=2.0, atr_mult=1.5, risk_pct=0.01)
    # stop distance = 2*1.5 = 3 -> stop 97; size = 100/3
    assert atr["stop"] == 97.0 and atr["stop_distance"] == 3.0
    assert round(atr["position_size"], 4) == round(100 / 3, 4)


def test_vol_adjusted_cuts_size_in_high_vol():
    calm = position_size(equity=10_000, entry=100, stop=98, method="vol_adjusted",
                         atr=2.0, vol_target_pct=0.02)      # cur vol 2% == target -> scale 1
    wild = position_size(equity=10_000, entry=100, stop=98, method="vol_adjusted",
                         atr=4.0, vol_target_pct=0.02)      # cur vol 4% -> scale 0.5
    assert wild["dollar_risk"] < calm["dollar_risk"]
    assert round(wild["dollar_risk"], 2) == round(calm["dollar_risk"] * 0.5, 2)


def test_margin_and_liquidation_directional():
    lng = position_size(equity=10_000, entry=100, stop=95, leverage=10)
    assert lng["margin_required"] == round(lng["notional"] / 10, 2)
    assert lng["liquidation_estimate"] < 100          # long liquidates below entry
    sht = position_size(equity=10_000, entry=100, stop=105, side="short", leverage=10)
    assert sht["liquidation_estimate"] > 100          # short liquidates above entry


def test_sizing_validates_inputs():
    assert "error" in position_size(equity=0, entry=100, stop=95)
    assert "error" in position_size(equity=10_000, entry=100, stop=100)   # zero stop dist
    assert "error" in position_size(equity=10_000, entry=100, method="atr")  # atr missing


# ───────────────────────── correlation (#3) ─────────────────────────
def test_pearson_perfect_and_inverse():
    a = [0.01, -0.02, 0.03, 0.0, 0.015]
    assert round(pearson(a, a), 6) == 1.0
    assert round(pearson(a, [-x for x in a]), 6) == -1.0


def test_log_returns_length():
    assert len(log_returns([100, 101, 102, 101])) == 3


def test_correlation_matrix_real_data_is_symmetric_and_bounded():
    m = correlation_matrix(["BTCUSDT", "ETHUSDT", "SOLUSDT"], timeframe="1d", lookback=150)
    assert set(m["available"]) >= {"BTCUSDT", "ETHUSDT", "SOLUSDT"}   # seeded store
    mat = m["matrix"]
    for a in m["symbols"]:
        assert mat[a][a] == 1.0                                      # self-correlation
        for b in m["symbols"]:
            c = mat[a][b]
            assert c is None or (-1.0 <= c <= 1.0)
            if mat[b][a] is not None and c is not None:
                assert abs(c - mat[b][a]) < 1e-9                     # symmetric
    # pairs sorted by |correlation|, strongest first
    if len(m["pairs"]) > 1:
        assert abs(m["pairs"][0]["correlation"]) >= abs(m["pairs"][-1]["correlation"])


def test_correlation_conflict_blocks_highly_correlated():
    # crafted matrix: candidate strongly correlated with an open symbol
    matrix = {"AAA": {"AAA": 1.0, "BBB": 0.92, "CCC": 0.1},
              "BBB": {"AAA": 0.92, "BBB": 1.0, "CCC": 0.2},
              "CCC": {"AAA": 0.1, "BBB": 0.2, "CCC": 1.0}}
    blocked = correlation_conflicts("AAA", ["BBB"], threshold=0.8, matrix=matrix)
    assert blocked["allowed"] is False and blocked["conflicts"][0]["symbol"] == "BBB"
    ok = correlation_conflicts("AAA", ["CCC"], threshold=0.8, matrix=matrix)
    assert ok["allowed"] is True


# ───────────────────────── portfolio risk (#2) ─────────────────────────
def test_portfolio_exposure_long_short_and_heat():
    pos = [{"symbol": "BTCUSDT", "direction": "long", "notional": 2000, "risk": 100},
           {"symbol": "ETHUSDT", "direction": "short", "notional": 1000, "risk": 50}]
    r = portfolio_risk(10_000, pos, timeframe="1d", lookback=150)
    assert r["total_exposure"] == 3000.0
    assert r["long_exposure"] == 2000.0 and r["short_exposure"] == 1000.0
    assert r["net_exposure"] == 1000.0
    assert r["portfolio_heat_pct"] == 1.5            # 150 / 10000
    # VaR computed from the real covariance matrix (seeded store) and positive
    assert r["value_at_risk"] is not None and r["value_at_risk"] > 0
    assert r["value_at_risk_pct"] is not None


def test_portfolio_warns_when_exposure_too_high():
    pos = [{"symbol": "BTCUSDT", "direction": "long", "notional": 15_000, "risk": 800}]
    r = portfolio_risk(10_000, pos, timeframe="1d", lookback=150,
                       exposure_warn=1.0, heat_warn=0.06)
    assert r["risk_level"] == "high"
    assert any("exposure" in w.lower() for w in r["warnings"])
    assert any("heat" in w.lower() for w in r["warnings"])


def test_empty_portfolio_is_flat():
    r = portfolio_risk(10_000, [], timeframe="1d")
    assert r["total_exposure"] == 0.0 and r["warnings"] == [] and r["risk_level"] == "normal"


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_risk_endpoints(client):
    ps = client.post("/risk/position-size", json={"equity": 10000, "entry": 100, "stop": 95}).json()
    assert ps["position_size"] == 20.0
    corr = client.get("/risk/correlation", params={"symbols": "BTCUSDT,ETHUSDT", "timeframe": "1d"}).json()
    assert "matrix" in corr and corr["matrix"]["BTCUSDT"]["BTCUSDT"] == 1.0
    pf = client.get("/risk/portfolio").json()
    assert "value_at_risk_pct" in pf and "portfolio_heat_pct" in pf and "warnings" in pf
