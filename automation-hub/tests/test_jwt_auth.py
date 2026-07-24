"""JWT access tokens issued alongside the HMAC session cookie (Sprint 1b).

Verifies the dependency-free codec and that a Bearer token authenticates the
JSON API without a cookie — while the existing cookie path is untouched."""
import time

import pytest


# ------------------------------------------------------------- codec (pure)

def test_jwt_roundtrip_and_claims():
    from services import jwt_tokens
    tok = jwt_tokens.encode({"sub": "alice", "typ": "access"}, "s3cret", ttl_seconds=60)
    body = jwt_tokens.decode(tok, "s3cret")
    assert body and body["sub"] == "alice" and body["typ"] == "access"
    assert body["exp"] > body["iat"]


def test_jwt_rejects_wrong_secret_tamper_and_garbage():
    from services import jwt_tokens
    tok = jwt_tokens.encode({"sub": "bob"}, "right", ttl_seconds=60)
    assert jwt_tokens.decode(tok, "wrong") is None            # wrong key
    assert jwt_tokens.decode(tok + "x", "right") is None       # tampered sig
    header, body, sig = tok.split(".")
    assert jwt_tokens.decode(f"{header}.{body}AA.{sig}", "right") is None  # tampered body
    for junk in ("", "abc", "a.b", "a.b.c.d", None):
        assert jwt_tokens.decode(junk, "right") is None


def test_jwt_expiry():
    from services import jwt_tokens
    tok = jwt_tokens.encode({"sub": "carol"}, "k", ttl_seconds=-1)  # already expired
    assert jwt_tokens.decode(tok, "k") is None
    fresh = jwt_tokens.encode({"sub": "carol"}, "k", ttl_seconds=5)
    assert jwt_tokens.decode(fresh, "k")["sub"] == "carol"


# ------------------------------------------------------- app-level (issue/verify)

@pytest.fixture()
def app_env(tmp_path):
    # Swap the module-level store to an isolated DB (the same pattern the other
    # auth suites use) and restore it after — NEVER reload app/config, which
    # would rebind shared singletons and poison the rest of the suite.
    pytest.importorskip("fastapi")
    import app as hub_app
    from database.store import SqliteStore
    orig_store = hub_app.store
    hub_app.store = SqliteStore(str(tmp_path / "hub.db"))
    hub_app.store.seed_admin("admin", "admin")
    try:
        yield hub_app
    finally:
        hub_app.store = orig_store


def test_issue_and_verify_access(app_env):
    tok = app_env.issue_access("admin")
    assert app_env.verify_access(tok) == "admin"
    # a valid signature for a user that doesn't exist is rejected
    ghost = app_env.issue_access("nobody")
    assert app_env.verify_access(ghost) is None
    # a non-access token type is rejected even if well-signed
    from services import jwt_tokens
    refresh = jwt_tokens.encode({"sub": "admin", "typ": "refresh"},
                                app_env.settings.secret_key, ttl_seconds=60)
    assert app_env.verify_access(refresh) is None


def test_bearer_authenticates_json_api_without_cookie(app_env):
    from fastapi.testclient import TestClient
    c = TestClient(app_env.app)

    # JSON login returns a bearer token (and sets the cookie)
    r = c.post("/auth/login", data={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    tok = r.json()["token"]
    assert r.json()["token_type"] == "bearer"

    # a FRESH client (no cookie jar) authenticates purely via the Bearer header
    c2 = TestClient(app_env.app)
    st = c2.get("/auth/status", headers={"Authorization": f"Bearer {tok}"}).json()
    assert st["authenticated"] is True and st["user"] == "admin"

    # no header, no cookie → anonymous
    assert c2.get("/auth/status").json()["authenticated"] is False
    # bad token → anonymous (not a 500)
    bad = c2.get("/auth/status", headers={"Authorization": "Bearer not.a.jwt"}).json()
    assert bad["authenticated"] is False


def test_form_login_still_sets_working_cookie(app_env):
    from fastapi.testclient import TestClient
    c = TestClient(app_env.app)
    c.post("/auth/login", data={"username": "admin", "password": "admin"})
    # the cookie set by /auth/login authenticates subsequent requests (no header)
    assert c.get("/auth/status").json()["authenticated"] is True


def test_json_login_bad_credentials(app_env):
    from fastapi.testclient import TestClient
    c = TestClient(app_env.app)
    assert c.post("/auth/login", data={"username": "admin", "password": "nope"}).status_code == 401
