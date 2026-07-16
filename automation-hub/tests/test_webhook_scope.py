"""M-5 — decouple the admin/control credential from the webhook secret.

By default nothing changes (the admin key falls back to the webhook secret). When
an operator sets a distinct admin key and turns on scoping, the webhook secret —
which is shared with TradingView and so the most likely to leak — can ONLY post
alerts, not control the account.
"""
import pytest
from fastapi.testclient import TestClient

import app as app_module
import webhook_api as wa
from config import settings

WH = settings.webhook_secret


@pytest.fixture
def restore():
    admin, scope = settings.admin_key, settings.scope_webhook_secret
    yield
    settings.admin_key, settings.scope_webhook_secret = admin, scope


# ─────────────────────────── default: unchanged behaviour ───────────────────────────
def test_default_webhook_secret_still_controls(restore):
    settings.admin_key, settings.scope_webhook_secret = WH, False   # default state
    wa._check_secret(WH)                # webhook secret works for control (no raise)
    wa._check_webhook_secret(WH)        # and for the webhook


# ─────────────────────────── distinct admin key ───────────────────────────
def test_admin_key_controls(restore):
    settings.admin_key, settings.scope_webhook_secret = "ADMIN-KEY-123", False
    wa._check_secret("ADMIN-KEY-123")           # admin key controls
    wa._check_secret(WH)                          # webhook secret still allowed (not scoped)


# ─────────────────────────── scoped: webhook secret loses control ───────────────────────────
def test_scoped_webhook_secret_cannot_control(restore):
    settings.admin_key, settings.scope_webhook_secret = "ADMIN-KEY-123", True
    wa._check_secret("ADMIN-KEY-123")                     # admin key still controls
    with pytest.raises(Exception):
        wa._check_secret(WH)                              # webhook secret rejected on control
    wa._check_webhook_secret(WH)                          # but STILL valid for the webhook


def test_bad_credential_always_rejected(restore):
    settings.admin_key, settings.scope_webhook_secret = "ADMIN-KEY-123", True
    for bad in (None, "", "nope"):
        with pytest.raises(Exception):
            wa._check_secret(bad)


# ─────────────────────────── auth wall (reads) honours scoping ───────────────────────────
def test_auth_wall_scopes_reads(restore):
    settings.admin_key, settings.scope_webhook_secret = "ADMIN-KEY-123", True
    c = TestClient(app_module.app)
    # webhook secret no longer opens the read wall...
    assert c.get("/risk/summary", headers={"X-Webhook-Secret": WH}).status_code == 401
    # ...but the admin key does
    assert c.get("/risk/summary", headers={"X-Webhook-Secret": "ADMIN-KEY-123"}).status_code == 200


def test_webhook_endpoint_accepts_webhook_secret_when_scoped(restore):
    settings.admin_key, settings.scope_webhook_secret = "ADMIN-KEY-123", True
    c = TestClient(app_module.app)
    payload = {"alert_id": "scope-test-1", "symbol": "BTCUSDT", "side": "BUY",
               "entry": 60000, "stop": 59000}
    # TradingView's webhook secret still works on /webhook — that's the whole point
    r = c.post("/webhook/tradingview", json=payload, headers={"X-Webhook-Secret": WH})
    assert r.status_code == 200
    # a wrong secret is still rejected
    assert c.post("/webhook/tradingview", json=payload,
                  headers={"X-Webhook-Secret": "nope"}).status_code == 401
