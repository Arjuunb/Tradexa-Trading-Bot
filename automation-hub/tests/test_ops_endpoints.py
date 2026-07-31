"""The operational HTTP surface: probes and the scrape endpoint.

These are the endpoints Kubernetes and Prometheus depend on. If any of them
changes shape the cluster does not fail loudly — it quietly restarts healthy
pods, or stops collecting metrics and leaves every alert permanently green.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as hub_app


@pytest.fixture()
def client():
    # The context manager is required: it fires the startup event, which is what
    # registers the readiness checks and marks boot complete.
    with TestClient(hub_app.app) as c:
        yield c


def test_liveness_is_cheap_and_always_answers(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


def test_readiness_reports_its_individual_checks(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    # The checks registered at startup — the ones that decide whether this
    # instance should receive traffic.
    assert "data_dir" in body["checks"]
    assert "database" in body["checks"]


def test_startup_probe_passes_once_boot_completes(client):
    r = client.get("/health/startup")
    assert r.status_code == 200
    assert r.json()["status"] == "started"


def test_readiness_returns_503_when_a_dependency_fails(client, monkeypatch):
    """503, not 500. It tells the load balancer to stop routing here without
    telling the kubelet to restart the process."""
    from ops import health

    health.register_check("synthetic_failure", lambda: (False, "down for the test"))
    try:
        r = client.get("/health/ready")
        assert r.status_code == 503
        assert r.json()["status"] == "not_ready"
    finally:
        health._checks.pop("synthetic_failure", None)


def test_legacy_health_still_returns_the_rich_payload(client):
    """The dashboard and the Render health check read this. Adding the probes
    must not have changed it."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "persistence" in body and "tenancy" in body


def test_metrics_serves_prometheus_exposition_without_a_session(client):
    """Prometheus scrapes with no cookie. If this ever requires auth, every
    metric silently stops and every alert goes green."""
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "hub_build_info" in r.text


def test_metrics_exposes_the_series_the_alerts_query(client):
    """Each name here is referenced by an alert in
    deploy/observability/prometheus/rules/hub-alerts.yml. Renaming one without
    updating the rules produces an alert that can never fire."""
    body = client.get("/metrics").text
    for series in ("hub_http_requests_total",
                   "hub_http_request_duration_seconds_bucket",
                   "hub_engine_running",
                   "hub_engine_leader",
                   "hub_engine_cycles_total",
                   "hub_trade_decisions_total",
                   "hub_risk_vetoes_total",
                   "hub_rate_limit_rejections_total",
                   "hub_auth_failures_total"):
        assert series in body, f"{series} is missing — an alert depends on it"


def test_metrics_token_gates_the_endpoint_when_configured(client, monkeypatch):
    # Read at import time, so patch the module attribute rather than the env.
    monkeypatch.setattr(hub_app, "_METRICS_TOKEN", "s3cret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_requests_carry_a_correlation_id(client):
    r = client.get("/health/live")
    assert r.headers.get("X-Request-ID")


def test_an_inbound_correlation_id_is_preserved(client):
    """One identity for a request across the proxy, this service and anything
    it calls."""
    r = client.get("/health/live", headers={"X-Request-ID": "trace-me-123"})
    assert r.headers["X-Request-ID"] == "trace-me-123"


def test_http_metrics_use_route_templates_not_raw_paths(client):
    """Cardinality control. A label taken from user input is unbounded, and an
    unbounded label is how a Prometheus server runs out of memory. Unmatched
    paths must collapse into one series."""
    for i in range(3):
        client.get(f"/definitely-not-a-route-{i}")
    body = client.get("/metrics").text
    assert "__unmatched__" in body
    assert "definitely-not-a-route-0" not in body
