"""AI Strategy Agent — interpreter contract tests.

The agent must never invent a rule, never assume intent, and never claim a
capability the engine lacks. These tests pin exactly that, and none of them
require an LLM: the deterministic grammar / validator / clarification layers are
what enforce the contract, with the model only proposing candidates."""
import pytest

from services import strategy_agent as sa
from strategies.custom import _rule


def _bar_stub():
    from bot.types import Bar
    from datetime import datetime, timezone
    return [Bar(datetime(2025, 1, 1, tzinfo=timezone.utc), 1, 1, 1, 1, 1)]


# ------------------------------------------- grammar cannot drift from engine

def test_every_grammar_rule_is_implemented_by_the_engine():
    """The anti-hallucination guarantee: every type the agent may emit must be a
    real branch of strategies.custom._rule. Mirrors the builder's own catalog
    test, so the agent's vocabulary can never outgrow the engine."""
    bars = _bar_stub()
    for rtype in sa.rule_types():
        passed, why = _rule({"type": rtype}, bars, 0)
        assert isinstance(passed, bool), f"{rtype} is not a real engine rule"


def test_grammar_exposes_params_and_options():
    g = sa.rule_grammar()
    assert "ema_cross" in g and "rsi" in g
    assert g["ema_cross"]["params"]["fast"]["default"] == 20
    assert g["rsi"]["params"]["op"]["options"] == ["above", "below"]


# --------------------------------------------------- unsupported capabilities

def test_news_filter_is_reported_unsupported_not_dropped():
    found = sa.detect_unsupported("Buy the breakout but avoid high-impact news events.")
    caps = [f["capability"] for f in found]
    assert "News / economic-calendar filtering" in caps
    assert any("no news" in f["why"].lower() for f in found)


def test_two_named_sessions_are_flagged_not_merged():
    """The spec holds ONE session window, so 'London and New York' cannot be
    represented — it must be raised rather than silently merged."""
    found = sa.detect_unsupported("Only trade London and New York sessions.")
    caps = [f["capability"] for f in found]
    assert "Multiple trading sessions" in caps


def test_single_session_is_not_flagged():
    assert not any(f["capability"] == "Multiple trading sessions"
                   for f in sa.detect_unsupported("Only trade the London session."))


def test_unsupported_scan_runs_without_an_llm():
    """Capability gaps are deterministic, so the user still learns about them
    even with no API key configured."""
    out = sa.compile_strategy("Trade breakouts, avoid NFP news")
    assert out["available"] is False or out["spec"] is not None
    assert any(f["capability"].startswith("News") for f in out["unsupported"])


# ------------------------------------------------------------------ validation

def _good_spec():
    return {
        "name": "EMA pullback", "symbol": "BTCUSDT", "timeframe": "15m", "side": "long",
        "entry": {"op": "AND", "rules": [
            {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above",
             "source": "20 EMA crosses above the 50 EMA"},
            {"type": "rsi", "period": 14, "value": 55, "op": "above",
             "source": "RSI is above 55"},
        ]},
        "stop": {"type": "atr", "mult": 1.5, "period": 14},
        "target": {"type": "rr", "rr": 3},
        "risk_per_trade_pct": 0.01,
    }


def test_valid_spec_passes():
    v = sa.validate_spec(_good_spec())
    assert v["ok"], v["errors"]


def test_unknown_rule_type_is_a_hard_error():
    """The engine silently never fires an unknown type — that must not pass."""
    spec = _good_spec()
    spec["entry"]["rules"].append({"type": "moon_phase", "source": "full moon"})
    v = sa.validate_spec(spec)
    assert not v["ok"]
    assert any("moon_phase" in e for e in v["errors"])


def test_ungrounded_rule_is_rejected():
    """A rule with no source phrase is an invention — rejected, not kept."""
    spec = _good_spec()
    spec["entry"]["rules"].append({"type": "adx", "period": 14, "value": 25, "op": "above"})
    v = sa.validate_spec(spec)
    assert not v["ok"]
    assert any("not grounded" in e for e in v["errors"])


def test_bad_enum_value_is_an_error():
    spec = _good_spec()
    spec["entry"]["rules"][1]["op"] = "sideways"
    v = sa.validate_spec(spec)
    assert not v["ok"]
    assert any("must be one of" in e for e in v["errors"])


def test_no_entry_rules_is_an_error():
    spec = _good_spec()
    spec["entry"] = {"op": "AND", "rules": []}
    v = sa.validate_spec(spec)
    assert not v["ok"]
    assert any("never take a trade" in e for e in v["errors"])


def test_wraparound_session_is_rejected():
    spec = _good_spec()
    spec["session"] = {"start": 21, "end": 6}
    v = sa.validate_spec(spec)
    assert not v["ok"]
    assert any("wrap-around" in e for e in v["errors"])


def test_nested_groups_are_validated_recursively():
    spec = _good_spec()
    spec["entry"]["rules"].append(
        {"op": "OR", "rules": [{"type": "nonsense", "source": "x"}]})
    v = sa.validate_spec(spec)
    assert not v["ok"] and any("nonsense" in e for e in v["errors"])


def test_high_risk_warns_but_does_not_block():
    spec = _good_spec()
    spec["risk_per_trade_pct"] = 0.10
    v = sa.validate_spec(spec)
    assert v["ok"] and any("aggressive" in w for w in v["warnings"])


# ---------------------------------------------------- completeness + questions

def test_completeness_scores_and_lists_missing():
    c = sa.completeness(_good_spec())
    assert 0 < c["score"] <= 100
    assert c["rule_count"] == 2
    assert "Trading session" in c["missing"]      # not specified in the fixture


def test_missing_pieces_become_questions_not_defaults():
    spec = _good_spec()
    del spec["stop"]
    del spec["target"]
    qs = sa.clarifying_questions(spec, sa.validate_spec(spec))
    ids = {q["id"] for q in qs}
    assert "stop" in ids and "target" in ids
    assert all(q["question"] for q in qs)


# ------------------------------------------------------------ honest degradation

def test_no_api_key_degrades_honestly(monkeypatch):
    for env in ("HUB_LLM_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    out = sa.compile_strategy("When EMA 20 crosses above EMA 50, go long.")
    assert out["available"] is False
    assert out["spec"] is None                  # never a fabricated spec
    assert "no LLM API key" in out["note"]


def test_llm_failure_never_fabricates(monkeypatch):
    monkeypatch.setenv("HUB_LLM_API_KEY", "test-key")
    monkeypatch.setattr(sa, "_call_llm",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = sa.compile_strategy("go long on a breakout")
    assert out["spec"] is None
    assert "Nothing was compiled" in out["note"]


def test_compiled_flag_requires_clean_validation_and_no_questions(monkeypatch):
    monkeypatch.setenv("HUB_LLM_API_KEY", "test-key")
    monkeypatch.setattr(sa, "_call_llm", lambda *a, **k: {"spec": _good_spec()})
    out = sa.compile_strategy("20 EMA crosses above the 50 EMA and RSI is above 55")
    assert out["available"] and out["spec"] is not None
    # session was never specified, so the agent asks rather than assuming one
    assert out["compiled"] is False or not out["questions"]


def test_system_prompt_is_built_from_the_real_grammar():
    p = sa._system_prompt()
    for rtype in ("ema_cross", "liquidity_sweep", "ichimoku"):
        assert rtype in p
    assert "moon_phase" not in p
    assert "Never invent" in p or "never invent" in p.lower()
