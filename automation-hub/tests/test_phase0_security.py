"""Audit Phase 0 — security hot-fixes.

CR-1: session tokens are signed with the server-only secret_key (HUB_SECRET),
      NOT the webhook_secret that ships in every authed page — so a leaked
      webhook secret can no longer forge a session.
H-2:  the bare /settings API is session-gated even in the landing-bundled config
      (only the SPA sub-routes /settings/... are auth-exempt).
"""
import hashlib
import hmac

import app as app_module
from config import settings


def test_sessions_signed_with_secret_key_not_webhook_secret():
    app_module.store.create_user("alice", "password-a1")   # verify() checks the user exists
    token = app_module._sign_session("alice")
    msg, sig = token.rsplit("|", 1)
    good_secret = hmac.new(settings.secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    forged_secret = hmac.new(settings.webhook_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    assert sig == good_secret                 # signed with the server-only key
    assert sig != forged_secret               # NOT the embedded webhook secret
    assert app_module._verify_session(token) == "alice"


def test_forged_token_with_webhook_secret_is_rejected():
    # an attacker who read the embedded webhook secret tries to mint an owner token
    import time
    exp = str(int(time.time()) + 86400)
    msg = f"owner|{exp}"
    forged = f"{msg}|" + hmac.new(settings.webhook_secret.encode(), msg.encode(),
                                  hashlib.sha256).hexdigest()
    assert app_module._verify_session(forged) is None    # rejected


def test_settings_api_not_auth_exempt_even_with_landing():
    # reproduce the production exempt set (landing bundled) and assert the bare
    # /settings API is NOT exempt while the SPA sub-routes are.
    exempt = app_module._AUTH_EXEMPT + ("/settings/", "/app")

    def is_exempt(path):
        return path == "/" or any(path.startswith(p) for p in exempt)

    assert is_exempt("/settings") is False            # engine-config API — gated
    assert is_exempt("/settings/profile") is True     # SPA route — served
    assert is_exempt("/settings/risk") is True
    assert is_exempt("/paper/account") is False


def test_settings_get_requires_auth(client=None):
    from fastapi.testclient import TestClient
    c = TestClient(app_module.app)
    # no session, no secret -> the auth wall blocks it
    assert c.get("/settings").status_code == 401
    # with the control secret it's reachable (operator path)
    assert c.get("/settings", headers={"X-Webhook-Secret": settings.webhook_secret}).status_code == 200
