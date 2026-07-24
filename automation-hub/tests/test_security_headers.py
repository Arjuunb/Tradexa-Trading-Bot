"""Baseline security response headers (Sprint 11).

Drives the real app; read-only public paths, no shared state mutated."""
import pytest


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    return TestClient(hub_app.app)


def test_baseline_headers_present(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_hsts_only_on_https(client):
    # plain HTTP (the test transport) → no HSTS
    assert "Strict-Transport-Security" not in client.get("/api/version").headers
    # behind an HTTPS-terminating proxy (Render) → HSTS present
    r = client.get("/api/version", headers={"X-Forwarded-Proto": "https"})
    hsts = r.headers.get("Strict-Transport-Security", "")
    assert "max-age=" in hsts and "includeSubDomains" in hsts


def test_no_frame_options_so_embedding_is_not_broken(client):
    # framing is governed by the configurable CSP, not a hard X-Frame-Options
    assert "X-Frame-Options" not in client.get("/api/version").headers
