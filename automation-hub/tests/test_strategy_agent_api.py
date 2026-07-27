"""AI Strategy Agent HTTP surface (slice 2).

Proves the endpoints keep the interpreter contract end-to-end: no key -> honest
unavailable (never a spec), capability gaps always reported, and a compiled spec
is handed to the EXISTING simulate endpoint rather than any new engine."""
import pytest


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


def test_agent_status_reports_availability_and_vocabulary(client):
    r = client.get("/strategy/agent/status")
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j["available"], bool)
    assert j["rule_count"] >= 20
    assert "ema_cross" in j["rule_types"] and "liquidity_sweep" in j["rule_types"]
    if not j["available"]:
        assert "HUB_LLM_API_KEY" in j["note"]


def test_status_available_flips_with_the_key(client, monkeypatch):
    for env in ("HUB_LLM_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    assert client.get("/strategy/agent/status").json()["available"] is False
    monkeypatch.setenv("HUB_LLM_API_KEY", "test-key")
    assert client.get("/strategy/agent/status").json()["available"] is True


def test_compile_without_key_is_honest_and_never_returns_a_spec(client, monkeypatch):
    for env in ("HUB_LLM_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    r = client.post("/strategy/ai-compile",
                    json={"text": "Go long when the 20 EMA crosses above the 50 EMA."})
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is False
    assert j["spec"] is None
    assert "no LLM API key" in j["note"]


def test_compile_reports_capability_gaps_even_without_an_llm(client, monkeypatch):
    """The engine genuinely cannot do these, so the user must be told regardless
    of whether the model is configured."""
    for env in ("HUB_LLM_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    r = client.post("/strategy/ai-compile", json={
        "text": "Buy breakouts on the London and New York sessions, avoid high-impact news."})
    caps = [u["capability"] for u in r.json()["unsupported"]]
    assert "News / economic-calendar filtering" in caps
    assert "Multiple trading sessions" in caps


def test_empty_text_is_a_prompt_not_an_error(client):
    j = client.post("/strategy/ai-compile", json={"text": "   "}).json()
    assert j["spec"] is None and "Describe your strategy" in j["note"]


def test_overlong_text_is_rejected(client):
    r = client.post("/strategy/ai-compile", json={"text": "x" * 8001})
    assert r.status_code == 400


def test_compiled_spec_includes_engine_read_back(client, monkeypatch):
    """The confirmation screen must show the ENGINE's reading of the spec, so it
    comes from strategies.custom.describe(), not from the model's prose."""
    from services import strategy_agent as sa
    spec = {
        "name": "EMA pullback", "symbol": "BTCUSDT", "timeframe": "15m", "side": "long",
        "entry": {"op": "AND", "rules": [
            {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above",
             "source": "20 EMA crosses above the 50 EMA"}]},
        "stop": {"type": "atr", "mult": 1.5, "period": 14},
        "target": {"type": "rr", "rr": 3}, "risk_per_trade_pct": 0.01,
    }
    monkeypatch.setenv("HUB_LLM_API_KEY", "test-key")
    monkeypatch.setattr(sa, "_call_llm", lambda *a, **k: {"spec": spec})
    j = client.post("/strategy/ai-compile", json={"text": "20 EMA above 50 EMA"}).json()
    assert j["spec"]["name"] == "EMA pullback"
    assert j["description"] and isinstance(j["description"], str)
    assert j["completeness"]["rule_count"] == 1


def test_compiled_spec_runs_on_the_existing_simulate_endpoint(client, monkeypatch):
    """The whole point of compiling to the existing format: the agent's output
    feeds the SAME backtest endpoint the visual builder uses. No new engine."""
    from services import strategy_agent as sa
    spec = {
        "name": "Agent EMA", "symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
        "entry": {"op": "AND", "rules": [
            {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above",
             "source": "20 EMA crosses above the 50 EMA"}]},
        "stop": {"type": "atr", "mult": 1.5, "period": 14},
        "target": {"type": "rr", "rr": 2}, "risk_per_trade_pct": 0.01,
    }
    monkeypatch.setenv("HUB_LLM_API_KEY", "test-key")
    monkeypatch.setattr(sa, "_call_llm", lambda *a, **k: {"spec": spec})
    compiled = client.post("/strategy/ai-compile", json={"text": "20 EMA above 50"}).json()
    assert compiled["spec"] is not None

    sim = client.post("/strategy/custom/simulate",
                      json={"spec": compiled["spec"], "bars": 1200})
    assert sim.status_code == 200
    body = sim.json()
    assert "results" in body and "total_trades" in body["results"]


def test_ungrounded_model_output_is_blocked_from_compiling(client, monkeypatch):
    """A rule the model could not trace to the user's words must not compile."""
    from services import strategy_agent as sa
    spec = {
        "name": "Invented", "symbol": "BTCUSDT", "timeframe": "15m", "side": "long",
        "entry": {"op": "AND", "rules": [{"type": "adx", "period": 14, "value": 25,
                                          "op": "above"}]},   # no "source"
        "stop": {"type": "atr", "mult": 1.5}, "target": {"type": "rr", "rr": 2},
        "risk_per_trade_pct": 0.01,
    }
    monkeypatch.setenv("HUB_LLM_API_KEY", "test-key")
    monkeypatch.setattr(sa, "_call_llm", lambda *a, **k: {"spec": spec})
    j = client.post("/strategy/ai-compile", json={"text": "just buy dips"}).json()
    assert j["compiled"] is False
    assert any("not grounded" in e for e in j["errors"])
