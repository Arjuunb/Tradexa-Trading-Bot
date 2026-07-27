"""Empirically-verified parameter tuning.

Contract: a suggestion exists only because a real backtest measured it winning
by a material margin, it only nudges parameters the user already chose, and the
guards against curve-fitting a lucky variant actually hold."""
import pytest

from services import strategy_tuner as tn

SPEC = {
    "name": "EMA", "symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
    "entry": {"op": "AND", "rules": [
        {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"},
        {"type": "rsi", "period": 14, "value": 55, "op": "above"},
    ]},
    "stop": {"type": "atr", "mult": 1.5, "period": 14},
    "target": {"type": "rr", "rr": 2}, "risk_per_trade_pct": 0.01,
}


def _res(net_r, pf, trades=40):
    return {"trades": [{"r": 1.0}] * trades, "total_trades": trades,
            "net_r": net_r, "profit_factor": pf, "win_rate": 50.0,
            "max_drawdown_r": -5.0, "expectancy_r": net_r / max(trades, 1)}


# ------------------------------------------------------------------ candidates

def test_candidates_only_nudge_parameters_the_user_chose():
    cands = tn.candidates(SPEC)
    assert cands, "expected variants"
    for c in cands:
        assert c["rule_type"] in ("ema_cross", "rsi")
        assert c["param"] in ("fast", "slow", "period", "value")
        assert c["from"] != c["to"]


def test_candidates_never_touch_direction_or_operator():
    """Changing 'above' to 'below' would invent a different strategy."""
    for c in tn.candidates(SPEC):
        assert c["param"] not in ("dir", "op", "type", "negate")


def test_candidates_preserve_the_rest_of_the_spec():
    c = tn.candidates(SPEC)[0]
    assert c["spec"]["stop"] == SPEC["stop"]
    assert c["spec"]["target"] == SPEC["target"]
    assert len(c["spec"]["entry"]["rules"]) == 2


def test_candidates_do_not_mutate_the_original():
    before = str(SPEC)
    tn.candidates(SPEC)
    assert str(SPEC) == before


def test_candidate_count_is_bounded():
    assert len(tn.candidates(SPEC, limit=3)) == 3


# ------------------------------------------------------ only measured winners

def test_only_variants_that_actually_win_are_suggested():
    def runner(spec):
        rules = spec["entry"]["rules"]
        fast = rules[0].get("fast")
        if fast == 25:                       # one genuinely better variant
            return _res(30.0, 2.2)
        if spec == SPEC:
            return _res(10.0, 1.4)           # the baseline
        return _res(9.0, 1.3)                # every other variant is worse
    out = tn.tune(SPEC, runner)
    assert out["available"] is True and out["tested"] > 0
    assert len(out["suggestions"]) == 1
    s = out["suggestions"][0]
    assert "fast" in s["title"] and "25" in s["title"]
    assert s["measured"]["before"]["net_r"] == 10.0
    assert s["measured"]["after"]["net_r"] == 30.0
    assert "Measured, not predicted" in s["expected_benefit"]


def test_no_winner_says_so_rather_than_suggesting_the_least_bad():
    out = tn.tune(SPEC, lambda spec: _res(10.0, 1.4))     # every variant ties
    assert out["suggestions"] == []
    assert "none beat the current settings" in out["note"]
    assert out["tested"] > 0, "it should still report how much it searched"


def test_marginal_gains_are_rejected_as_noise():
    def runner(spec):
        if spec == SPEC:
            return _res(10.0, 1.40)
        return _res(10.2, 1.45)              # a hair better — not material
    assert tn.tune(SPEC, runner)["suggestions"] == []


def test_a_variant_that_stops_trading_is_rejected():
    """A 'winner' that only takes 5 of 40 trades is cherry-picking, not an edge."""
    def runner(spec):
        if spec == SPEC:
            return _res(10.0, 1.4, trades=40)
        return _res(50.0, 9.0, trades=5)     # spectacular, and meaningless
    assert tn.tune(SPEC, runner)["suggestions"] == []


def test_confidence_is_never_high_for_single_window_tuning():
    def runner(spec):
        return _res(40.0, 3.0) if spec != SPEC else _res(10.0, 1.4)
    for s in tn.tune(SPEC, runner)["suggestions"]:
        assert s["confidence"] == "medium"
        assert "curve-fitted" in s["tradeoffs"]


def test_a_failing_variant_does_not_kill_tuning():
    calls = {"n": 0}
    def runner(spec):
        if spec == SPEC:
            return _res(10.0, 1.4)
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return _res(30.0, 2.2)
    out = tn.tune(SPEC, runner)
    assert out["available"] is True and out["suggestions"]


def test_no_baseline_means_no_tuning():
    out = tn.tune(SPEC, lambda spec: None)
    assert out["available"] is False and out["suggestions"] == []


def test_patch_replaces_only_the_entry_tree():
    def runner(spec):
        return _res(30.0, 2.2) if spec != SPEC else _res(10.0, 1.4)
    s = tn.tune(SPEC, runner)["suggestions"][0]
    assert set(s["patch"]) == {"entry"}
    assert len(s["patch"]["entry"]["rules"]) == 2


# ------------------------------------------------------------------ endpoint

@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


def test_tune_endpoint_runs_real_backtests(client):
    r = client.post("/strategy/tune", json={"spec": SPEC, "range": "1Y", "limit": 3})
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is True
    assert j["tested"] <= 3
    for s in j["suggestions"]:
        assert s["measured"]["before"] and s["measured"]["after"]


def test_tune_endpoint_requires_entry_rules(client):
    assert client.post("/strategy/tune", json={"spec": {}}).status_code == 400
