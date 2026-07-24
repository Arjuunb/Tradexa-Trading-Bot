"""Versioned /api/v1 namespace (Sprint 1c).

The JSON API is aliased under /api/v1 while every legacy root path keeps
working. These tests drive the REAL app (both mounts present)."""
import pytest


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    return TestClient(hub_app.app)


def test_api_version_handshake(client):
    for path in ("/api/v1", "/api/version"):
        r = client.get(path)
        assert r.status_code == 200, path
        j = r.json()
        assert j["ok"] is True and j["api_version"] == "v1"
        assert j["endpoints_base"] == "/api/v1"


def test_router_endpoint_aliased_under_v1(client):
    # a representative router-based GET must respond identically at both paths.
    # Authenticate with the webhook secret so the auth wall lets the read
    # through at BOTH paths (the alias must NOT bypass the wall on its own).
    import app as hub_app
    sec = {"X-Webhook-Secret": hub_app.settings.webhook_secret}
    legacy = client.get("/bot-os", headers=sec)
    v1 = client.get("/api/v1/bot-os", headers=sec)
    assert legacy.status_code != 404, "legacy path missing"
    assert v1.status_code != 404, "/api/v1 alias missing"
    assert legacy.status_code == v1.status_code == 200
    assert v1.json() == legacy.json()


def test_v1_alias_still_enforces_the_auth_wall(client):
    # the alias must be gated exactly like legacy — no anonymous bypass
    assert client.get("/api/v1/bot-os").status_code == 401
    assert client.get("/bot-os").status_code == 401


def test_openapi_still_builds_with_dual_mount(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    # both the legacy and the versioned surface are present in the schema
    assert any(p.startswith("/api/v1/") for p in paths)
    assert "/bot-os" in paths
