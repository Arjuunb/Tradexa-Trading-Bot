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


# ------------------------------------------------- diagnosable LLM failures

def _api_error(cls, status, msg):
    import httpx
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req, json={"error": {"message": msg}})
    return cls(msg, response=resp, body={"error": {"message": msg}})


def test_each_failure_names_its_own_cause():
    """Regression: every failure used to render as its exception class name —
    "HTTPError" — which reads identically for a rejected key, an exhausted
    balance, and a rate limit. Those need three different actions."""
    import anthropic
    from services.strategy_agent import describe_llm_error

    cases = [
        (anthropic.AuthenticationError, 401, "invalid x-api-key", "401"),
        (anthropic.BadRequestError, 400, "credit balance is too low", "400"),
        (anthropic.NotFoundError, 404, "model: bogus", "404"),
        (anthropic.RateLimitError, 429, "rate limit exceeded", "429"),
    ]
    seen = set()
    for cls, status, msg, marker in cases:
        out = describe_llm_error(_api_error(cls, status, msg))
        assert marker in out, out
        assert msg in out, "the API's own message must survive"
        seen.add(out)
    assert len(seen) == len(cases), "each status must read differently"


def test_the_low_balance_case_is_legible():
    """A valid key on an account with no credit returns 400 — the single most
    confusing failure, because the key itself is fine."""
    import anthropic
    from services.strategy_agent import describe_llm_error
    out = describe_llm_error(_api_error(
        anthropic.BadRequestError, 400,
        "Your credit balance is too low to access the Anthropic API"))
    assert "credit balance is too low" in out


def test_a_network_failure_is_not_reported_as_a_key_problem():
    import anthropic
    import httpx
    from services.strategy_agent import describe_llm_error
    exc = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    out = describe_llm_error(exc)
    assert "outbound network" in out and "key" not in out.lower()


def test_compile_surfaces_the_reason_rather_than_the_class(monkeypatch):
    import anthropic
    from services import strategy_agent as sa
    monkeypatch.setattr(sa, "llm_available", lambda: True)

    def boom(*a, **k):
        raise _api_error(anthropic.AuthenticationError, 401, "invalid x-api-key")
    monkeypatch.setattr(sa, "_call_llm", boom)

    note = sa.compile_strategy("Buy when RSI is above 55.")["note"]
    assert "401" in note and "invalid x-api-key" in note
    assert "AuthenticationError" not in note, "the class name is not a diagnosis"


def test_the_default_model_is_a_current_one():
    from services import strategy_agent as sa
    assert sa._MODEL.startswith("claude-"), sa._MODEL
    assert "-4-5" not in sa._MODEL, "claude-sonnet-4-5 is a legacy model"


# ══════════════════════════════════════════ risk units (real report)
# From a live session: "Risk 1% of my account on each trade" compiled to
# risk_per_trade_pct = 1, and the engine read it as 100% of equity per trade.

def test_risk_of_one_is_blocked_not_merely_warned():
    """1 is 100% of the account. Passing that as a warning lets a strategy
    reach a backtest sized 100x what the user asked for."""
    v = sa.validate_spec({**_good_spec(), "risk_per_trade_pct": 1})
    assert v["ok"] is False
    assert any("100%" in e for e in v["errors"])


def test_the_blocking_error_names_the_value_the_user_probably_meant():
    v = sa.validate_spec({**_good_spec(), "risk_per_trade_pct": 1})
    assert any("0.01" in e for e in v["errors"])


def test_risk_above_one_is_impossible_as_a_fraction():
    v = sa.validate_spec({**_good_spec(), "risk_per_trade_pct": 2})
    assert v["ok"] is False
    assert any("cannot exceed" in e for e in v["errors"])


def test_a_normal_risk_fraction_still_passes_clean():
    v = sa.validate_spec({**_good_spec(), "risk_per_trade_pct": 0.01})
    assert not [e for e in v["errors"] if "risk" in e.lower()]
    assert not v["warnings"]


def test_an_aggressive_but_plausible_risk_warns_without_blocking():
    """0.08 is 8% — high, but a real choice someone might make. It must not be
    confused with a unit error."""
    v = sa.validate_spec({**_good_spec(), "risk_per_trade_pct": 0.08})
    assert not [e for e in v["errors"] if "risk" in e.lower()]
    assert any("aggressive" in w for w in v["warnings"])


def test_the_risk_value_is_never_silently_rescaled():
    """The interpreter must not rewrite the user's risk. It reports and pauses;
    correcting the number is the user's decision."""
    spec = {**_good_spec(), "risk_per_trade_pct": 1}
    sa.validate_spec(spec)
    assert spec["risk_per_trade_pct"] == 1


def test_an_ambiguous_risk_comes_with_an_answerable_question():
    """A blocking error with no matching question leaves the user stuck: told
    compilation is paused, with no control that resumes it."""
    spec = {**_good_spec(), "risk_per_trade_pct": 1}
    qs = sa.risk_unit_questions(spec, sa.validate_spec(spec))
    assert len(qs) == 1 and qs[0]["id"] == "risk_units"
    assert any("0.01" in o for o in qs[0]["options"])


def test_a_sane_risk_raises_no_unit_question():
    spec = {**_good_spec(), "risk_per_trade_pct": 0.01}
    assert sa.risk_unit_questions(spec, sa.validate_spec(spec)) == []


def test_the_prompt_tells_the_model_the_field_is_a_fraction():
    """The field name ends in _pct while the value is a fraction — the model
    needs that said out loud, or it emits 1 for 1% again."""
    p = sa._system_prompt()
    assert "FRACTION" in p and "0.01" in p


# ══════════════════════════════════════ contradictory stop options

def test_the_stop_question_never_offers_an_unsupported_option():
    """It used to offer "Below the previous swing low" while validate_spec
    accepts only atr and pct — choosing it produced a spec the engine rejects."""
    qs = sa.clarifying_questions({**_good_spec(), "stop": None}, {"errors": []})
    stop_q = next(q for q in qs if q["id"] == "stop")
    assert not any("swing" in o.lower() for o in stop_q["options"])
    for opt in stop_q["options"]:
        assert "atr" in opt.lower() or "percentage" in opt.lower()


def test_the_model_question_suppresses_the_duplicate_deterministic_one():
    """Both fired at once in a live session: the model explained swing-low
    stops are unsupported, while ours offered swing low as a choice."""
    existing = [{"id": "stop_type", "question":
                 "Stops must be an ATR multiple or a fixed percentage — "
                 "'below the previous swing low' is not supported. Which?",
                 "options": []}]
    qs = sa.clarifying_questions({**_good_spec(), "stop": None}, {"errors": []},
                                 existing=existing)
    assert not [q for q in qs if q["id"] == "stop"]


def test_unrelated_model_questions_do_not_suppress_the_stop_question():
    existing = [{"id": "symbol", "question": "Which asset?", "options": []}]
    qs = sa.clarifying_questions({**_good_spec(), "stop": None}, {"errors": []},
                                 existing=existing)
    assert [q for q in qs if q["id"] == "stop"]


def test_a_model_target_question_suppresses_ours():
    existing = [{"id": "tp", "question": "How should take profit be set?", "options": []}]
    qs = sa.clarifying_questions({**_good_spec(), "target": None}, {"errors": []},
                                 existing=existing)
    assert not [q for q in qs if q["id"] == "target"]
