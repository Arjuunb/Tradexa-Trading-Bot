"""The webhook_api monolith is split into domain routers (task 1). These guard
the split's invariants so it can't silently regress."""
import pytest


def test_all_domain_routers_included_and_endpoints_reachable():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    # one GET endpoint from every domain router must be reachable (not 404)
    for p in ["/engine/status", "/paper/account", "/risk/summary",
              "/journal/trades", "/health/bot", "/settings", "/bots/live",
              "/strategy/performance", "/skipped/trades", "/safety/live-readiness"]:
        assert client.get(p).status_code != 404, f"unreachable: {p}"


def test_singletons_stay_on_webhook_api_not_shadowed_by_router_modules():
    """Domain names like `settings`, `paper`, `engine` collide with router file
    names — guard that the includes never shadow the real singletons (which the
    test suite and app.py read as webhook_api.<name>)."""
    import webhook_api
    from config import Settings
    assert isinstance(webhook_api.settings, Settings)
    assert type(webhook_api.paper).__name__ == "PaperExecutionEngine"
    assert type(webhook_api.engine).__name__ == "AutoStrategyEngine"
    assert type(webhook_api.pipeline).__name__ == "SignalPipeline"


def test_routers_resolve_singletons_dynamically():
    """Moved endpoint bodies read shared state via _wa.<name>, so rebinding a
    webhook_api singleton (as fixtures do) is reflected in the handlers."""
    import webhook_api
    import routers.paper as rp
    # the router imports webhook_api as _wa and reads through it (dynamic)
    assert rp._wa is webhook_api
