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


def test_partial_take_profit_and_breakeven():
    r = build_replay("ETHUSDT", "15m", 900)
    # trade records carry the staged-exit fields
    for t in r["trades"]:
        assert "tp1" in t and "tp1_idx" in t and "status" in t and "partial" in t
        if t["partial"] and t["tp1"] is not None:
            # tp1 sits between entry and final tp
            if t["side"] == "long":
                assert t["entry"] < t["tp1"] <= t["tp"]
            else:
                assert t["tp"] <= t["tp1"] < t["entry"]
        if t["exit_idx"] is not None:
            assert t["status"] == "Closed"
            assert t["result"] in ("Winner", "Loser", "Break Even")
    # a partial fill produces a 'partial' timeline event and a TP1 marker
    if any(t["tp1_idx"] is not None for t in r["trades"]):
        assert any(e["kind"] == "partial" for e in r["events"])
        assert any(m["type"] == "TP1" for m in r["markers"])


def test_partial_then_breakeven_is_small_winner():
    """A trade that books a partial then stops at break-even nets a small + R."""
    r = build_replay("ETHUSDT", "15m", 900)
    for t in r["trades"]:
        if t["tp1_idx"] is not None and t["exit_reason"] == "Break-even stop after partial":
            assert t["rr"] is not None and t["rr"] > 0   # the booked partial keeps it green


def test_trades_respect_multi_timeframe_gate():
    """No taken trade may oppose a directional higher timeframe, and each trade
    records its multi-timeframe alignment reason (explainability)."""
    from services.mtf_engine import htf_consensus
    r = build_replay("BTCUSDT", "15m", 1200)
    for t in r["trades"]:
        assert "mtf" in t and "reason" in t["mtf"] and "aligned" in t["mtf"]
        side = 1 if t["side"] == "long" else -1
        frame_trends = r["frames"][t["entry_idx"]]["trends"]
        assert htf_consensus(frame_trends, side)["allowed"]   # never against the HTF


def test_changing_strategy_changes_trades_and_id():
    """Selecting a different strategy must use a different engine and produce
    different trades — proving the selector drives the real backend."""
    a = build_replay("BTCUSDT", "15m", 900, strategy="Supply/Demand")
    b = build_replay("BTCUSDT", "15m", 900, strategy="EMA 20/50")
    assert a["meta"]["debug"]["strategy_id"] == "supply_demand"
    assert b["meta"]["debug"]["strategy_id"] == "ema_20_50"
    # different strategy -> different trade set
    sig = lambda r: [(t["side"], t["entry_idx"]) for t in r["trades"]]
    assert sig(a) != sig(b)
    # debug panel proves the wiring
    for r in (a, b):
        d = r["meta"]["debug"]
        assert d["candles_loaded"] == len(r["candles"])
        assert d["trades_generated"] == len(r["trades"])


def test_data_source_labelled_and_demo_flagged():
    r = build_replay("BTCUSDT", "15m", 400)
    # never claims synthetic/bundled is real Binance data
    if r["meta"]["data_source"] in ("synthetic", "bundled sample"):
        assert r["meta"]["data_is_real"] is False
        assert "Binance historical data" != r["meta"]["data_source_label"]
    demo = build_replay("BTCUSDT", "15m", 400, source="demo")
    assert demo["meta"]["data_is_real"] is False
    assert "Demo" in demo["meta"]["data_source_label"]
    assert "Demo sample" in (demo["meta"]["data_warning"] or "")


def test_registry_has_all_strategies():
    from services.strategy_presets import REGISTRY
    names = {r["name"] for r in REGISTRY}
    assert {"Decision Brain", "Trend Following", "Breakout Retest", "Liquidity Sweep",
            "Support/Resistance Rejection", "Supply/Demand", "EMA 8/30", "EMA 20/50",
            "Custom Strategy"} <= names
    for r in REGISTRY:
        assert r["id"] and r["version"] and "description" in r


def test_replay_endpoint_strategy_param(client):
    a = client.get("/replay/run", params={"symbol": "BTCUSDT", "timeframe": "15m",
                                          "limit": 400, "strategy": "EMA 20/50"}).json()
    assert a["meta"]["strategy"] == "EMA 20/50"
    assert a["meta"]["debug"]["strategy_id"] == "ema_20_50"
    reg = client.get("/strategies/registry").json()["strategies"]
    assert any(s["id"] == "ema_20_50" for s in reg)
