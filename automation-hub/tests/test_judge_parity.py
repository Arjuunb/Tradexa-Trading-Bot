"""Regression guard: the research judges (retune, context validation) must
simulate through the SAME TradeBrain quality gate the live engine applies —
or they optimize/judge a brain the bot never actually trades."""
from data.market_data import get_bars
from strategies.brain import TradeBrain
from strategies.brain_strategy import DecisionBrain
from strategies.custom import LIVE_MIN_SCORE, gated_sim, simulate_strategy


def test_live_min_score_matches_the_engine_default():
    # the gate constant the judges use must equal the engine's HUB_MIN_SCORE default
    assert LIVE_MIN_SCORE == 60


def test_gated_sim_is_the_canonical_quality_gate():
    bars, _ = get_bars("ZZZUSDT", n=1500, timeframe="1h")
    a = gated_sim(DecisionBrain("ZZZUSDT"), bars)
    b = simulate_strategy(DecisionBrain("ZZZUSDT"), bars,
                          brain=TradeBrain(), min_score=LIVE_MIN_SCORE)
    assert a["net_r"] == b["net_r"] and a["total_trades"] == b["total_trades"]


def test_gate_actually_filters_when_it_bites():
    # proves the gate is applied (not a silent no-op): a strict threshold blocks
    bars, _ = get_bars("ZZZUSDT", n=2500, timeframe="1h")
    loose = simulate_strategy(DecisionBrain("ZZZUSDT"), bars)          # no gate
    strict = simulate_strategy(DecisionBrain("ZZZUSDT"), bars,
                               brain=TradeBrain(), min_score=90)
    assert len(strict.get("blocked", [])) > 0
    assert strict["total_trades"] <= loose["total_trades"]


def test_retune_run_config_routes_through_the_gate(monkeypatch):
    import strategies.custom as custom
    from services import retune
    calls = {"n": 0}
    real = custom.gated_sim

    def spy(strat, rows, **kw):
        calls["n"] += 1
        return real(strat, rows, **kw)

    monkeypatch.setattr(custom, "gated_sim", spy)
    bars, _ = get_bars("ZZZUSDT", n=1200, timeframe="1h")
    retune._run_config("ZZZUSDT", bars, {"conviction_threshold": 0.56, "rr_target": 3.0})
    assert calls["n"] == 1                       # went through the gated path


def test_context_validators_route_through_the_gate(monkeypatch):
    import strategies.custom as custom
    from services import context_brain
    calls = {"n": 0}
    real = custom.gated_sim

    def spy(strat, rows, **kw):
        calls["n"] += 1
        return real(strat, rows, **kw)

    monkeypatch.setattr(custom, "gated_sim", spy)
    context_brain.validate_cross_asset(symbols=("ZZZUSDT",), timeframe="1h",
                                       bars=1200, require_real=False)
    assert calls["n"] >= 2                        # baseline + gated, both gated
