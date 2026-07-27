"""The single place a strategy spec becomes a backtest.

"One engine, everywhere" is the central claim of this system: the number the
marketplace publishes, the number the review scores, the number the tuner
measures and the baseline the monitor compares against must all mean the same
thing. These tests pin that the wiring behind those numbers is literally one
function, and that its defaults match the live engine's.
"""
import pytest

from services import spec_runner as sr

SPEC = {
    "name": "EMA", "symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
    "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50}]},
    "stop": {"type": "atr", "mult": 1.5, "period": 14},
    "target": {"type": "rr", "rr": 2}, "risk_per_trade_pct": 0.01,
}


# ------------------------------------------------------------- the defaults

def test_the_quality_filter_is_on_unless_the_spec_turns_it_off(monkeypatch):
    """A backtest run without the brain is quietly easier than live trading."""
    seen = {}

    def fake_simulate(spec, rows, brain=None, min_score=0):
        seen["brain"] = brain is not None
        seen["min_score"] = min_score
        return {"total_trades": 1}

    _patch(monkeypatch, fake_simulate)
    sr.run_spec(SPEC, 100)
    assert seen == {"brain": True, "min_score": 60}

    sr.run_spec({**SPEC, "quality_filter": False}, 100)
    assert seen == {"brain": False, "min_score": 0}


def test_a_custom_min_score_is_honoured(monkeypatch):
    seen = {}

    def fake_simulate(spec, rows, brain=None, min_score=0):
        seen["min_score"] = min_score
        return {}

    _patch(monkeypatch, fake_simulate)
    sr.run_spec({**SPEC, "min_score": 80}, 100)
    assert seen["min_score"] == 80


def test_no_data_is_none_not_an_empty_backtest(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: {"total_trades": 5}, rows=[])
    assert sr.run_spec(SPEC, 100) is None


def test_a_sweep_cell_overrides_symbol_and_timeframe_without_mutating_the_spec(monkeypatch):
    seen = {}

    def fake_simulate(spec, rows, brain=None, min_score=0):
        seen["symbol"], seen["timeframe"] = spec["symbol"], spec["timeframe"]
        return {}

    _patch(monkeypatch, fake_simulate)
    sr.run_spec(SPEC, 100, symbol="ETHUSDT", timeframe="1h")
    assert seen == {"symbol": "ETHUSDT", "timeframe": "1h"}
    assert SPEC["symbol"] == "BTCUSDT", "the caller's spec must be untouched"


def test_rows_are_returned_separately_not_smuggled_into_the_result(monkeypatch):
    """Several endpoints serialise the result dict straight to JSON; bar objects
    hidden inside it would blow up on the wire."""
    _patch(monkeypatch, lambda *a, **k: {"total_trades": 3})
    res, rows = sr.run_spec_with_bars(SPEC, 100)
    assert rows, "the caller asked for the candles"
    assert not any(k.startswith("__") for k in res), res


# ------------------------------------------------------------- the runners

def test_the_range_runner_sizes_the_window_from_the_timeframe(monkeypatch):
    seen = {}
    _patch(monkeypatch, lambda *a, **k: {}, on_get=lambda sym, n, tf: seen.update(n=n, tf=tf))
    sr.make_runner(lambda tf, rng: 999, "1Y")(SPEC)
    assert seen == {"n": 999, "tf": "4h"}


def test_the_cell_runner_tags_timeframe_integrity(monkeypatch):
    """Without this a feed that ignores the timeframe argument would let a sweep
    rank a series against itself and report a fabricated 'best timeframe'."""
    _patch(monkeypatch, lambda *a, **k: {"total_trades": 2})
    run = sr.make_cell_runner(lambda tf, rng: 100, "1Y",
                              verify_timeframe=lambda rows, tf: tf == "4h")
    assert run(SPEC, "BTCUSDT", "4h")["__tf_verified"] is True
    assert run(SPEC, "BTCUSDT", "1h")["__tf_verified"] is False


def test_the_cell_runner_without_a_verifier_adds_no_tag(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: {"total_trades": 2})
    res = sr.make_cell_runner(lambda tf, rng: 100, "1Y")(SPEC, "BTCUSDT", "4h")
    assert "__tf_verified" not in res


# ---------------------------------------------------- everyone routes through

def test_tuner_publisher_and_sweep_all_delegate_to_this_module():
    """If any of them grows its own copy of the wiring, the defaults can drift
    apart and the numbers stop being comparable — which is the whole claim."""
    import inspect
    from services import strategy_publisher, strategy_sweep, strategy_tuner
    for mod in (strategy_tuner, strategy_publisher, strategy_sweep):
        src = inspect.getsource(mod.make_runner)
        assert "spec_runner" in src, f"{mod.__name__} re-implements the runner"
        assert "simulate(" not in src, f"{mod.__name__} calls simulate directly"


def test_the_review_endpoint_helper_also_delegates():
    import inspect
    import sys
    # webhook_api first: routers.analytics imports it, so importing the router
    # on its own trips the circular import.
    import webhook_api  # noqa: F401
    src = inspect.getsource(sys.modules["routers.analytics"]._run_spec)
    assert "spec_runner" in src and "simulate(" not in src


# ------------------------------------------------------------------ helpers

def _patch(monkeypatch, simulate, rows=None, on_get=None):
    """Point the runner at a fake engine so these tests measure WIRING, not
    market data."""
    import data.market_data as md
    import strategies.custom as custom
    bars = [object()] * 50 if rows is None else rows

    def fake_get_bars(symbol, n=0, timeframe=None, **kw):
        if on_get:
            on_get(symbol, n, timeframe)
        return bars, "fake"

    monkeypatch.setattr(md, "get_bars", fake_get_bars)
    monkeypatch.setattr(custom, "simulate", simulate)


def test_the_fake_engine_harness_is_actually_patching(monkeypatch):
    """Guard the guard: if the monkeypatch stopped landing, every test above
    would silently pass against real market data."""
    _patch(monkeypatch, lambda *a, **k: {"sentinel": True})
    assert sr.run_spec(SPEC, 10) == {"sentinel": True}
