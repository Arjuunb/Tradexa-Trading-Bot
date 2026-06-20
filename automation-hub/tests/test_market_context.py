"""Evolution live-market context + provider settings: real fetches fail closed
(never fabricated), key-gated sources show 'Not connected', keys are UI-settable."""
import pytest

from services.market_context import ProviderSettings, market_context, PROVIDERS


def test_context_never_fakes_when_offline(tmp_path):
    ctx = market_context(ProviderSettings(str(tmp_path / "p.json")))
    for k in ("fear_greed", "btc_dominance", "total_mcap_usd", "eth_btc",
              "funding_rate", "open_interest", "news"):
        assert k in ctx
        # offline in tests -> available False, and no fabricated numeric value
        if not ctx[k].get("available"):
            assert ctx[k].get("value") in (None, [], {}) or "headlines" in ctx[k]
    assert "not faking" in ctx["sentiment_summary"].lower() or ctx["fear_greed"]["available"]


def test_key_gated_sources_not_connected_without_key(tmp_path):
    ctx = market_context(ProviderSettings(str(tmp_path / "p.json")))
    for k in ("news", "liquidations", "economic_calendar"):
        assert ctx[k]["connected"] is False
        assert "not connected" in ctx[k]["note"].lower()


def test_provider_settings_save_status_and_no_key_leak(tmp_path):
    st = ProviderSettings(str(tmp_path / "p.json"))
    # all no-key providers connected, all key providers not — by default
    status = {p["id"]: p["connected"] for p in st.status()}
    assert status["fear_greed"] is True and status["news"] is False
    # saving a key connects it
    st.save({"news": "TOKEN123", "liquidations": "  ", "econ_calendar": "EC"})
    status2 = {p["id"]: p["connected"] for p in st.status()}
    assert status2["news"] is True and status2["econ_calendar"] is True
    assert status2["liquidations"] is False              # blank ignored
    # status never exposes the actual key value
    assert all("TOKEN123" not in str(p) for p in st.status())
    assert st.key("news") == "TOKEN123"
    # blanks don't wipe an existing key
    st.save({"news": ""})
    assert st.key("news") == "TOKEN123"


def test_env_var_fallback_for_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTOPANIC_TOKEN", "ENVTOKEN")
    st = ProviderSettings(str(tmp_path / "p.json"))
    assert st.key("news") == "ENVTOKEN"
    assert {p["id"]: p["connected"] for p in st.status()}["news"] is True


def test_providers_catalog_complete():
    ids = {p["id"] for p in PROVIDERS}
    assert {"fear_greed", "coingecko", "binance_funding", "binance_oi", "news",
            "liquidations", "econ_calendar", "twitter", "reddit"} <= ids


# ---- endpoints ----
@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    webhook_api.provider_settings = ProviderSettings(str(tmp_path / "p.json"))
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"


def test_market_context_endpoint(client):
    body = client.get("/evolution/market-context").json()
    assert "fear_greed" in body and "providers" in body and "sentiment_summary" in body


def test_providers_endpoint_and_gated_save(client):
    st = client.get("/evolution/providers").json()
    assert any(p["id"] == "news" for p in st["providers"])
    assert client.post("/evolution/providers", json={"news": "X"}).status_code == 401
    saved = client.post("/evolution/providers", json={"news": "ABC"},
                        headers={"X-Webhook-Secret": SECRET}).json()
    assert {p["id"]: p["connected"] for p in saved["providers"]}["news"] is True
