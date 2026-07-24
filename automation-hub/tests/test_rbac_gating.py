"""RBAC wired onto the user-management cluster (Sprint 11, first slice).

Covers the owner-can't-manage-users bug fix (User.is_admin now includes owner)
and the /users create gate routed through the rbac helpers."""
import pytest


# ------------------------------------------------------------- model bug fix

def test_owner_is_admin_capable():
    from database.models import User
    assert User(username="o", role="owner").is_admin is True
    assert User(username="a", role="admin").is_admin is True
    assert User(username="op", role="operator").is_admin is False
    assert User(username="v", role="viewer").is_admin is False


# ------------------------------------------------------- request-role helper

class _Req:
    """Minimal stand-in for a Starlette Request (cookies + headers)."""
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


def test_request_role_from_control_secret():
    import app as hub_app
    r = _Req(headers={"x-webhook-secret": hub_app.settings.admin_key})
    assert hub_app._request_role(r) == "owner"
    assert hub_app._has_role(r, "owner") and hub_app._has_role(r, "admin")
    # anonymous → no role, default-deny
    anon = _Req()
    assert hub_app._request_role(anon) is None
    assert not hub_app._has_role(anon, "viewer")


# -------------------------------------------------- /users create gate (e2e)

@pytest.fixture()
def env(tmp_path):
    pytest.importorskip("fastapi")
    import app as hub_app
    from database.store import SqliteStore
    orig = hub_app.store
    hub_app.store = SqliteStore(str(tmp_path / "hub.db"))
    try:
        yield hub_app
    finally:
        hub_app.store = orig


def _login(client, user, pw):
    # form login sets the session cookie in the client's jar
    return client.post("/login", data={"username": user, "password": pw})


def test_owner_can_create_users(env):
    from fastapi.testclient import TestClient
    env.store.create_user("boss", "pw12345678", role="owner")
    c = TestClient(env.app)
    _login(c, "boss", "pw12345678")
    r = c.post("/users", data={"username": "newop", "password": "pw12345678", "role": "operator"},
               follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers.get("location", "")
    assert env.store.get_user("newop") is not None   # the owner-lockout bug is fixed


def test_operator_cannot_create_users(env):
    from fastapi.testclient import TestClient
    env.store.create_user("worker", "pw12345678", role="operator")
    c = TestClient(env.app)
    _login(c, "worker", "pw12345678")
    r = c.post("/users", data={"username": "sneaky", "password": "pw12345678", "role": "admin"},
               follow_redirects=False)
    assert r.status_code == 303 and "error=Admin" in r.headers.get("location", "")
    assert env.store.get_user("sneaky") is None


def test_anonymous_blocked(env):
    from fastapi.testclient import TestClient
    c = TestClient(env.app)
    r = c.post("/users", data={"username": "x", "password": "pw12345678"},
               follow_redirects=False)
    # the global auth wall blocks anonymous writes (401) before the handler's
    # own /login redirect can run — either way, no user is created.
    assert r.status_code in (401, 303)
    assert env.store.get_user("x") is None


# ------------------------------------- privilege-escalation guard on role mint

def test_only_owner_can_mint_admins(env):
    from fastapi.testclient import TestClient
    env.store.create_user("boss", "pw12345678", role="owner")
    env.store.create_user("adm", "pw12345678", role="admin")

    # an ADMIN cannot create another admin (no lateral privilege escalation) …
    ca = TestClient(env.app); _login(ca, "adm", "pw12345678")
    r = ca.post("/users", data={"username": "wannabe", "password": "pw12345678", "role": "admin"},
                follow_redirects=False)
    assert r.status_code == 303 and "Only+the+owner" in r.headers.get("location", "")
    assert env.store.get_user("wannabe") is None

    # … but an admin CAN create operators and viewers
    ca.post("/users", data={"username": "vv", "password": "pw12345678", "role": "viewer"},
            follow_redirects=False)
    assert env.store.get_user("vv") is not None and env.store.get_user("vv").role == "viewer"

    # the OWNER can mint an admin
    co = TestClient(env.app); _login(co, "boss", "pw12345678")
    co.post("/users", data={"username": "newadm", "password": "pw12345678", "role": "admin"},
            follow_redirects=False)
    assert env.store.get_user("newadm") is not None and env.store.get_user("newadm").role == "admin"


def test_unknown_role_is_normalised_to_operator(env):
    from fastapi.testclient import TestClient
    env.store.create_user("boss", "pw12345678", role="owner")
    c = TestClient(env.app); _login(c, "boss", "pw12345678")
    c.post("/users", data={"username": "weird", "password": "pw12345678", "role": "superuser"},
           follow_redirects=False)
    assert env.store.get_user("weird").role == "operator"   # never the injected value
