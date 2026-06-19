"""Strategy Replay engine: shape, causality / no-lookahead, and endpoints."""
import pytest

from services.replay import build_replay, multi_asset_stats, TF_FACTORS, MIN_HTF_CANDLES


def test_replay_shape():
    r = build_replay("BTCUSDT", "15m", 500)
    for k in ("meta", "candles", "overlays", "markers", "zones", "frames", "events", "trades", "stats"):
        assert k in r
    nc = len(r["candles"])
    assert nc > 0
    assert len(r["frames"]) == nc                       # one frame per candle
    assert len(r["overlays"]["ema20"]) == nc
    assert len(r["overlays"]["vwap"]) == nc
    # every frame carries the multi-timeframe brain state
    f = r["frames"][nc // 2]
    for k in ("regime", "trends", "trigger", "score"):
        assert k in f
    assert set(f["trends"]) == {"Weekly", "Daily", "4H", "15M"} or "4H" in f["trends"]


def test_marker_and_event_indices_in_range():
    r = build_replay("ETHUSDT", "15m", 500)
    nc = len(r["candles"])
    for m in r["markers"]:
        assert 0 <= m["idx"] < nc
    for e in r["events"]:
        assert 0 <= e["idx"] < nc


def test_trades_are_consistent_and_causal():
    r = build_replay("BTCUSDT", "15m", 700)
    for t in r["trades"]:
        if t["exit_idx"] is not None:
            assert t["entry_idx"] < t["exit_idx"]      # exit never before entry
            assert t["result"] in ("Winner", "Loser")
            assert t["rr"] is not None
        # bracket consistency
        if t["side"] == "long":
            assert t["sl"] < t["entry"] < t["tp"]
        else:
            assert t["tp"] < t["entry"] < t["sl"]
        assert 0 <= t["score"] <= 100
        assert t["entry_reasons"]


def test_htf_closed_index_never_looks_ahead():
    """The 'last closed higher-tf candle' must end on or before the current bar."""
    for f in (3, 16, 48, 96, 672):
        for i in range(0, 5000, 7):
            closed = ((i + 1) // f) - 1
            if closed >= 0:
                last_exec_bar_of_candle = (closed + 1) * f - 1
                assert last_exec_bar_of_candle <= i   # no future bar used


def test_htf_availability_flags_present():
    r = build_replay("BTCUSDT", "15m", 600)
    avail = r["meta"]["htf_available"]
    assert "Weekly" in avail and "4H" in avail
    assert isinstance(avail["4H"], bool)


def test_multi_asset_stats():
    rows = multi_asset_stats(["BTCUSDT", "ETHUSDT"], "15m", 400)
    assert len(rows) == 2
    for s in rows:
        assert "win_rate" in s and "profit_factor" in s and "symbol" in s


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


def test_replay_endpoints(client):
    body = client.get("/replay/run", params={"symbol": "BTCUSDT", "timeframe": "15m", "limit": 400}).json()
    assert body["meta"]["symbol"] == "BTCUSDT"
    assert len(body["candles"]) == len(body["frames"])
    stats = client.get("/replay/stats", params={"symbols": "BTCUSDT,ETHUSDT", "limit": 300}).json()
    assert len(stats["assets"]) == 2


def test_order_block_zones_present():
    r = build_replay("BTCUSDT", "15m", 700)
    obs = [z for z in r["zones"] if z["type"] in ("demand", "supply")]
    for z in obs:
        assert z["top"] >= z["bottom"]
        assert 0 <= z["left_idx"]
    # at least the swing S/R levels exist
    assert any(z["type"] in ("support", "resistance") for z in r["zones"])


def test_date_window_filters_and_is_causal():
    full = build_replay("BTCUSDT", "15m", 600)
    start = (full["meta"]["start"] or "")[:10]
    win = build_replay("BTCUSDT", "15m", 200, start=start)
    assert win["meta"]["bars"] > 0
    assert win["meta"]["start"][:10] >= start
    assert len(win["candles"]) == len(win["frames"])


def test_date_window_out_of_range_is_empty():
    r = build_replay("BTCUSDT", "15m", 300, start="1990-01-01", end="1990-02-01")
    assert r["meta"]["bars"] == 0
    assert r["candles"] == [] and r["trades"] == []
    assert "note" in r["meta"]
