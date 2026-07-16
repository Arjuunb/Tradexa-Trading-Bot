"""No-Code Strategy Builder — new blocks, catalog, templates, AI review, library.

Everything compiles to the EXISTING spec engine (strategies/custom.py), so the
builder adds no second execution path. Uses the deterministic bar feed so tests
never touch the network.
"""
from data.market_data import get_bars
from strategies.custom import _rule, simulate, describe, evaluate
from services import strategy_builder as sb
from services.custom_store import CustomStore


def _bars(n=400, tf="1h"):
    b, _ = get_bars("BTCUSDT", n=n, timeframe=tf)
    return b


# ─────────────────────────── new blocks evaluate ───────────────────────────
def test_new_blocks_evaluate_without_error():
    bars = _bars()
    i = len(bars) - 1
    for t, params in [("adx", {"period": 14, "value": 20}), ("supertrend", {"period": 10, "mult": 3}),
                      ("obv", {"lookback": 20}), ("stoch_rsi", {"period": 14, "value": 20}),
                      ("trend", {"dir": "up"})]:
        ok, why = _rule({"type": t, **params}, bars, i)
        assert isinstance(ok, bool) and isinstance(why, str)


def test_smc_blocks_evaluate_and_describe():
    bars = _bars()
    i = len(bars) - 1
    for t, params in [("ichimoku", {"dir": "above"}), ("order_block", {"dir": "up", "lookback": 20}),
                      ("supply_demand", {"dir": "demand"})]:
        ok, why = _rule({"type": t, **params}, bars, i)
        assert isinstance(ok, bool) and isinstance(why, str)
    spec = {"side": "long", "entry": {"op": "AND", "rules": [{"type": "ichimoku", "dir": "above"},
                                                             {"type": "order_block", "dir": "up"}]}}
    d = describe(spec)
    assert "Ichimoku" in d and "order block" in d


def test_ichimoku_above_below_exclusive():
    bars = _bars()
    i = len(bars) - 1
    a, _ = _rule({"type": "ichimoku", "dir": "above"}, bars, i)
    b, _ = _rule({"type": "ichimoku", "dir": "below"}, bars, i)
    assert not (a and b)          # price can't be both above and below the cloud


def test_adx_reports_a_value():
    bars = _bars()
    ok, why = _rule({"type": "adx", "period": 14, "value": 0, "op": "above"}, bars, len(bars) - 1)
    assert ok is True and "ADX" in why       # ADX >= 0 always


def test_trend_up_and_down_are_exclusive():
    bars = _bars()
    i = len(bars) - 1
    up, _ = _rule({"type": "trend", "dir": "up"}, bars, i)
    down, _ = _rule({"type": "trend", "dir": "down"}, bars, i)
    assert not (up and down)                  # can't be HH/HL and LH/LL at once


def test_nested_condition_groups_evaluate_and_simulate():
    # the node canvas can express (A AND B) OR C — evaluate() must recurse into
    # a group rule while flat specs stay unchanged.
    bars = _bars()
    tree = {"op": "OR", "rules": [
        {"op": "AND", "rules": [{"type": "adx", "value": 0}, {"type": "supertrend", "dir": "up"}]},
        {"type": "rsi", "op": "below", "value": 30}]}
    ok, reasons = evaluate(tree, bars, len(bars) - 1)
    assert isinstance(ok, bool) and isinstance(reasons, list)
    spec = {"side": "long", "symbol": "BTCUSDT", "timeframe": "1h", "entry": tree,
            "stop": {"type": "atr", "mult": 1.5}, "target": {"type": "rr", "rr": 2}}
    assert "total_trades" in simulate(spec, bars)          # nested tree runs in the simulator


def test_indicator_exit_closes_trades():
    bars, _ = get_bars("BTCUSDT", n=1500, timeframe="1h")
    base = {"side": "long", "symbol": "BTCUSDT", "timeframe": "1h",
            "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"}]},
            "stop": {"type": "atr", "mult": 2}, "target": {"type": "rr", "rr": 4}}
    with_exit = {**base, "exit": {"op": "OR", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50, "dir": "below"}]}}
    r = simulate(with_exit, bars)
    reasons = {t.get("exit_reason") for t in r["trades"]}
    assert "indicator" in reasons              # some trades exit on the indicator rule


def test_ai_exit_closes_on_reversal():
    bars, _ = get_bars("BTCUSDT", n=1500, timeframe="1h")
    spec = {"side": "long", "symbol": "BTCUSDT", "timeframe": "1h",
            "entry": {"op": "AND", "rules": [{"type": "ema_cross", "dir": "above"}]},
            "stop": {"type": "atr", "mult": 2}, "target": {"type": "rr", "rr": 4}, "exit": {"ai_exit": True}}
    r = simulate(spec, bars)
    assert any(t.get("exit_reason") == "ai-exit" for t in r["trades"])


def test_live_adapter_should_exit_fires():
    # the live paper adapter honours the SAME exit rules as the backtest, so a
    # deployed strategy exits consistently (no divergence).
    from strategies.custom_adapter import CustomStrategyAdapter
    bars, _ = get_bars("BTCUSDT", n=600, timeframe="1h")
    spec = {"name": "X", "side": "long", "timeframe": "1h", "quality_filter": False,
            "entry": {"op": "AND", "rules": [{"type": "ema_cross", "dir": "above"}]},
            "exit": {"op": "OR", "rules": [{"type": "rsi", "op": "below", "value": 45}]}}
    a = CustomStrategyAdapter("BTCUSDT", spec)
    fired = 0
    for i in range(60, len(bars)):
        a.bars = list(bars[:i])                 # history WITHOUT the current bar (engine order)
        if a.should_exit(bars[i], "long") == "indicator":
            fired += 1
    assert fired > 0                            # exit conditions trigger live too


def test_live_adapter_no_exit_rules_returns_none():
    from strategies.custom_adapter import CustomStrategyAdapter
    bars, _ = get_bars("BTCUSDT", n=200, timeframe="1h")
    a = CustomStrategyAdapter("BTCUSDT", {"name": "X", "side": "long", "quality_filter": False,
                                          "entry": {"op": "AND", "rules": [{"type": "ema_cross"}]}})
    a.bars = list(bars[:-1])
    assert a.should_exit(bars[-1], "long") is None    # no exit config -> never exits early


def test_no_exit_rules_unchanged():
    bars, _ = get_bars("BTCUSDT", n=800, timeframe="1h")
    spec = {"side": "long", "entry": {"op": "AND", "rules": [{"type": "ema_cross", "dir": "above"}]},
            "stop": {"type": "atr", "mult": 2}, "target": {"type": "rr", "rr": 3}}
    reasons = {t.get("exit_reason") for t in simulate(spec, bars)["trades"]}
    assert reasons <= {"stop", "target", "breakeven", "time"}      # no indicator/ai exits appear


def test_flat_spec_unchanged_by_nesting_support():
    bars = _bars()
    flat = {"op": "AND", "rules": [{"type": "ema_cross"}, {"type": "rsi", "op": "above", "value": 50}]}
    ok, _ = evaluate(flat, bars, len(bars) - 1)
    assert isinstance(ok, bool)                            # backward compatible


def test_simulate_runs_with_new_blocks():
    spec = {"side": "long", "symbol": "BTCUSDT", "timeframe": "1h",
            "entry": {"op": "AND", "rules": [{"type": "adx", "value": 20}, {"type": "supertrend", "dir": "up"},
                                             {"type": "obv", "dir": "up"}]},
            "stop": {"type": "atr", "mult": 1.5, "period": 14}, "target": {"type": "rr", "rr": 2}}
    res = simulate(spec, _bars())
    assert "total_trades" in res and res["total_trades"] >= 0
    assert "ADX" in describe(spec) or "Supertrend" in describe(spec)   # new blocks describe


# ─────────────────────────── catalog ───────────────────────────
def test_block_catalog_covers_categories_and_maps_to_engine():
    cat = sb.block_catalog()
    keys = {c["key"] for c in cat["categories"]}
    assert {"market_structure", "smc", "indicators", "price_action"} <= keys
    # every catalog block type must be a real engine rule (no invented behaviour)
    bars = _bars()
    for c in cat["categories"]:
        for blk in c["blocks"]:
            ok, _ = _rule({"type": blk["type"],
                           **{p["name"]: p["default"] for p in blk["params"]}}, bars, len(bars) - 1)
            assert isinstance(ok, bool), f"{blk['type']} not a real engine rule"
    assert "AND" in cat["config"]["logic"] and any(s["key"] == "london" for s in cat["config"]["sessions"])


# ─────────────────────────── templates ───────────────────────────
def test_ten_templates_all_simulate():
    tpls = sb.templates()
    assert len(tpls) == 10
    names = {t["id"] for t in tpls}
    assert {"smc", "ict", "ema_trend", "breakout", "scalping", "swing", "mean_reversion",
            "momentum", "trend_following", "price_action"} == names
    bars = _bars()
    for t in tpls:
        res = simulate(t, bars)               # each template is a valid, runnable spec
        assert "total_trades" in res


# ─────────────────────────── AI review ───────────────────────────
def test_ai_review_without_results():
    spec = {"side": "long", "entry": {"op": "AND", "rules": [{"type": "ema_cross"}]},
            "target": {"type": "rr", "rr": 1.0}, "risk_per_trade_pct": 0.05}
    r = sb.ai_review(spec, None)
    assert r["complexity"] == "simple"
    assert r["risk_level"] == "high"          # 5% risk
    assert any("reward:risk" in w.lower() for w in r["weaknesses"])   # 1.0 RR flagged
    assert r["confidence_level"] in ("Very High", "High", "Medium", "Low", "Very Low")


def test_ai_review_with_backtest_results():
    spec = {"side": "long", "entry": {"op": "AND", "rules": [{"type": "ema_cross"}, {"type": "adx"}]},
            "target": {"type": "rr", "rr": 3}}
    results = {"total_trades": 60, "win_rate": 55, "profit_factor": 1.6, "max_drawdown_pct": 12}
    r = sb.ai_review(spec, results)
    assert "60 trades" in r["expected_behaviour"]
    assert r["estimated_confidence"] > 50     # profitable + enough trades
    assert any("Profitable" in s for s in r["strengths"])


# ─────────────────────────── library meta ───────────────────────────
def test_library_rename_and_folder(tmp_path):
    st = CustomStore(str(tmp_path / "custom.json"))
    saved = st.save({"name": "Draft", "side": "long", "entry": {"op": "AND", "rules": []}})
    sid = saved["id"]
    st.set_meta(sid, name="My SMC Strategy", folder="Crypto")
    got = st.get(sid)
    assert got["name"] == "My SMC Strategy" and got["folder"] == "Crypto"
    st.set_favorite(sid, True)
    assert st.get(sid)["favorite"] is True
