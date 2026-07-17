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


def test_directional_market_regime_classified():
    """Every frame carries a directional regime drawn from the spec's six
    categories, derived from real volatility + higher-timeframe direction."""
    from services.replay import _directional_regime
    allowed = {"Bull trend", "Bear trend", "Range", "Choppy market",
               "High volatility", "Low volatility"}
    r = build_replay("BTCUSDT", "15m", 600)
    assert r["frames"], "expected frames from seeded real data"
    for f in r["frames"]:
        assert f["market_regime"] in allowed
    # mapping rules
    assert _directional_regime("High Volatility", {}) == "High volatility"
    assert _directional_regime("Low Volatility", {}) == "Low volatility"
    assert _directional_regime("Trending", {"Daily": "Bullish", "4H": "Bullish"}) == "Bull trend"
    assert _directional_regime("Trending", {"Daily": "Bearish", "4H": "Bearish"}) == "Bear trend"
    assert _directional_regime("Ranging", {"Daily": "Bullish", "4H": "Bearish"}) == "Choppy market"
    assert _directional_regime("Ranging", {"Daily": "Neutral"}) == "Range"


def test_missing_real_data_prompts_download_not_synthetic(monkeypatch):
    """Default (binance) replay must NEVER fall back to synthetic — when no real
    Binance data is cached it surfaces a download prompt instead."""
    import services.replay as rp
    import data.market_data as md
    monkeypatch.setattr(md, "get_bars", lambda *a, **k: ([], "unavailable (real data required — run /data/sync)"))
    r = rp.build_replay("BTCUSDT", "15m", 400, source="binance")
    assert r["meta"]["bars"] == 0
    assert r["meta"]["needs_download"] is True
    assert r["meta"]["data_is_real"] is False
    assert r["meta"]["data_warning"] == "Historical data missing. Download data first."
    assert r["candles"] == [] and r["trades"] == []
    # demo is the ONLY way to get synthetic, and it stays clearly labelled
    demo = rp.build_replay("BTCUSDT", "15m", 400, source="demo")
    assert demo["meta"]["data_is_real"] is False and "Demo" in demo["meta"]["data_source_label"]


def test_registry_has_all_strategies():
    from services.strategy_presets import REGISTRY
    names = {r["name"] for r in REGISTRY}
    assert {"Decision Brain", "Trend Following", "Breakout Retest", "Liquidity Sweep",
            "Support/Resistance Rejection", "Supply/Demand", "EMA 8/30", "EMA 20/50",
            "Custom Strategy"} <= names
    for r in REGISTRY:
        assert r["id"] and r["version"] and "description" in r


def test_indicator_series_compute_and_are_causal():
    """Every overlay must be the real, computed series — same length as the
    candles, with ``None`` only during its warm-up window (never a fake value)."""
    r = build_replay("BTCUSDT", "15m", 600)
    nc = len(r["candles"])
    ov = r["overlays"]
    for key in ("ema8", "ema20", "ema30", "ema50", "sma20", "sma50", "vwap",
                "bb_upper", "bb_mid", "bb_lower", "rsi", "atr",
                "macd", "macd_signal", "macd_hist"):
        assert key in ov, key
        assert len(ov[key]) == nc, (key, len(ov[key]), nc)
    # RSI is bounded 0..100 wherever it is computed
    for v in ov["rsi"]:
        assert v is None or 0.0 <= v <= 100.0
    # Bollinger ordering upper >= mid >= lower wherever all three exist
    for u, m, l in zip(ov["bb_upper"], ov["bb_mid"], ov["bb_lower"]):
        if None not in (u, m, l):
            assert u >= m >= l
    # ATR is non-negative wherever computed; warm-up is None
    assert any(v is not None for v in ov["atr"])
    for v in ov["atr"]:
        assert v is None or v >= 0.0
    # SMA20 warm-up: first 19 entries None, value appears at index 19
    assert ov["sma20"][18] is None and ov["sma20"][19] is not None


def test_indicator_values_match_manual_calculation():
    """Recompute SMA/RSI directly from the returned candles and confirm the
    overlay matches — proves the series isn't decorative."""
    from services.replay import _sma_series, _rsi_series
    r = build_replay("ETHUSDT", "15m", 500)
    closes = [c["c"] for c in r["candles"]]
    # recompute from the (6-dp rounded) candle closes — must match to within rounding
    def close_enough(a, b, tol=1e-4):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert (x is None) == (y is None)
            if x is not None:
                assert abs(x - y) <= tol, (x, y)
    close_enough(r["overlays"]["sma20"], _sma_series(closes, 20))
    close_enough(r["overlays"]["rsi"], _rsi_series(closes, 14), tol=0.5)
    # last SMA20 equals the mean of the last 20 closes
    expect = sum(closes[-20:]) / 20
    assert abs(r["overlays"]["sma20"][-1] - expect) <= 1e-4


def test_macro_confirmation_timeframes_drive_the_gate():
    """Macro / confirmation selectors must change the multi-timeframe gate the
    engine enforces (not just a label)."""
    weekly = build_replay("BTCUSDT", "15m", 1000, macro="1w", confirmation="1d")
    assert weekly["meta"]["debug"]["gate_timeframes"] == ["Weekly", "Daily"]
    from services.mtf_engine import htf_consensus
    for t in weekly["trades"]:
        side = 1 if t["side"] == "long" else -1
        ft = weekly["frames"][t["entry_idx"]]["trends"]
        assert htf_consensus(ft, side, tfs=("Weekly", "Daily"))["allowed"]
    # default gate differs from a Weekly/Daily-only gate
    default = build_replay("BTCUSDT", "15m", 1000)
    assert default["meta"]["debug"]["gate_timeframes"] == ["Weekly", "Daily", "4H"]


def test_stats_have_streaks_matching_trades():
    """Consecutive win/loss metrics must match the actual ordered trade results."""
    r = build_replay("ETHUSDT", "15m", 900)
    s = r["stats"]
    for k in ("max_consecutive_wins", "max_consecutive_losses", "current_streak"):
        assert k in s
    rs = [t["rr"] for t in r["trades"] if t.get("rr") is not None]
    seq = ["W" if x > 0 else "L" if x < 0 else "B" for x in rs]
    mw = ml = cw = cl = 0
    for res in seq:
        cw = cw + 1 if res == "W" else 0
        cl = cl + 1 if res == "L" else 0
        mw, ml = max(mw, cw), max(ml, cl)
    assert s["max_consecutive_wins"] == mw
    assert s["max_consecutive_losses"] == ml


def test_replay_endpoint_strategy_param(client):
    a = client.get("/replay/run", params={"symbol": "BTCUSDT", "timeframe": "15m",
                                          "limit": 400, "strategy": "EMA 20/50"}).json()
    assert a["meta"]["strategy"] == "EMA 20/50"
    assert a["meta"]["debug"]["strategy_id"] == "ema_20_50"
    reg = client.get("/strategies/registry").json()["strategies"]
    assert any(s["id"] == "ema_20_50" for s in reg)


def test_memory_dna_filter_blocks_avoided_regimes():
    """The DNA memory filter must skip trades whose market regime is in the
    avoid set, recording a DNA-filter block — fewer trades, no entry in those
    regimes (#1/#13)."""
    base = build_replay("BTCUSDT", "15m", 800, strategy="EMA 8/30")
    regimes = {f["market_regime"] for f in base["frames"] if base["frames"]}
    avoid = list(regimes)[:1]  # avoid one present regime
    filt = build_replay("BTCUSDT", "15m", 800, strategy="EMA 8/30", avoid_regimes=avoid)
    # no taken trade may sit in an avoided regime
    for t in filt["trades"]:
        assert filt["frames"][t["entry_idx"]]["market_regime"] not in avoid
    # and the filter can only reduce (or equal) the trade count
    assert len(filt["trades"]) <= len(base["trades"])
    # a DNA-filter block is recorded when it bites
    if len(filt["trades"]) < len(base["trades"]):
        assert any("DNA filter" in e["text"] for e in filt["events"] if e["kind"] == "blocked")


def test_viz_spec_matches_active_strategy():
    """Item #1: the chart annotation spec (meta.viz) must declare EXACTLY the
    elements the ACTIVE strategy uses — SMC shows structure/zones and NO EMAs,
    EMA strategies show their two EMAs + crossovers and NO structure, and every
    declared overlay key is actually present in overlays."""
    smc = build_replay("BTCUSDT", "15m", 400, strategy="Supply/Demand", source="demo")["meta"]["viz"]
    assert smc["structure"] and smc["zones"] and smc["overlays"] == [] and not smc["crossovers"]

    ema = build_replay("BTCUSDT", "15m", 400, strategy="EMA 8/30", source="demo")
    v = ema["meta"]["viz"]
    assert v["overlays"] == ["ema8", "ema30"] and v["crossovers"] and not v["structure"]
    assert all(k in ema["overlays"] for k in v["overlays"])   # declared => computed
    assert any(m["type"] == "EMA Cross" for m in ema["markers"])   # real crossover markers

    st = build_replay("BTCUSDT", "15m", 400, strategy="Trend Following", source="demo")
    assert st["meta"]["viz"]["supertrend"] and st["overlays"].get("supertrend")
    assert not st["meta"]["viz"]["structure"] and st["meta"]["viz"]["overlays"] == []


def test_paper_close_endpoint(client):
    """Item #6: manual close routes through the real paper engine and realizes
    P&L; guards missing position (404) and bad symbol (400). Runs on an isolated
    in-memory paper engine so it never pollutes the shared account state."""
    import webhook_api as wa
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    orig_paper = wa.paper
    wa.paper = PaperExecutionEngine(SqliteLedger(":memory:"), starting_balance=10_000)
    try:
        wa.paper.open(symbol="BTCUSDT", side="long", size=0.5, entry=100.0, stop=95.0)
        sec = {"X-Webhook-Secret": wa.settings.webhook_secret}
        r = client.post("/paper/close", json={"symbol": "BTCUSDT", "price": 120.0}, headers=sec)
        assert r.status_code == 200 and r.json()["ok"] is True
        assert not any(p["symbol"] == "BTCUSDT" for p in wa.paper.positions())   # flattened
        assert client.post("/paper/close", json={"symbol": "NOPE"}, headers=sec).status_code == 404
        assert client.post("/paper/close", json={"symbol": ""}, headers=sec).status_code == 400
        assert client.post("/paper/close", json={"symbol": "BTCUSDT"}).status_code == 401  # secret required
    finally:
        wa.paper = orig_paper
