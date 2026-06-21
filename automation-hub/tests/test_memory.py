"""Market Memory (#12) + Strategy DNA (#13)."""
import pytest

from services.memory import build_memory, dna_match


def _sliced():
    # crafted sliced-performance result with clear winners/losers
    return {
        "strategy": "X", "timeframe": "15m", "total_trades": 50,
        "by_regime": [{"key": "Bull trend", "trades": 20, "net_r": 8.0, "win_rate": 60, "avg_r": 0.4},
                      {"key": "Choppy market", "trades": 15, "net_r": -6.0, "win_rate": 30, "avg_r": -0.4}],
        "by_session": [{"key": "New York", "trades": 25, "net_r": 6.0, "win_rate": 56, "avg_r": 0.24},
                       {"key": "Asia", "trades": 10, "net_r": -3.0, "win_rate": 30, "avg_r": -0.3}],
        "by_symbol": [{"key": "BTCUSDT", "trades": 18, "net_r": 7.0, "win_rate": 61, "avg_r": 0.39},
                      {"key": "XRPUSDT", "trades": 12, "net_r": -4.0, "win_rate": 33, "avg_r": -0.33}],
    }


def test_memory_derives_best_worst_and_dna():
    m = build_memory("X", "15m", sliced=_sliced())
    assert m["memory"]["best_regime"]["key"] == "Bull trend"
    assert m["memory"]["worst_regime"]["key"] == "Choppy market"
    assert m["dna"]["preferred_market"] == "Bull trend"
    assert m["dna"]["preferred_trend"] == "uptrend"
    assert m["dna"]["preferred_session"] == "New York"
    assert "BTCUSDT" in m["dna"]["preferred_symbols"]
    assert "XRPUSDT" in m["dna"]["avoid_symbols"]
    assert m["confidence"] == "high"                       # 50 trades


def test_dna_match_favorable_and_unfavorable():
    dna = build_memory("X", "15m", sliced=_sliced())["dna"]
    good = dna_match(dna, {"symbol": "BTCUSDT", "market_regime": "Bull trend", "session": "New York"})
    assert good["verdict"] == "favorable" and good["trade_here"] is True
    bad = dna_match(dna, {"symbol": "XRPUSDT", "market_regime": "Choppy market"})
    assert bad["verdict"] == "unfavorable" and bad["trade_here"] is False
    assert bad["fit_score"] < good["fit_score"]


def test_low_confidence_small_sample():
    s = _sliced(); s["total_trades"] = 6
    assert build_memory("X", "15m", sliced=s)["confidence"] == "low"


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_memory_endpoints(client):
    m = client.get("/memory/strategy", params={"strategy": "EMA 8/30", "timeframe": "15m",
                                               "symbols": "BTCUSDT,ETHUSDT", "limit": 600}).json()
    assert "dna" in m and "memory" in m and "by_regime" in m
    chk = client.get("/memory/dna-check", params={"strategy": "EMA 8/30", "symbol": "BTCUSDT",
                                                  "regime": "Bull trend"}).json()
    assert "match" in chk and "verdict" in chk["match"]
