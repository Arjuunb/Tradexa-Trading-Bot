"""The admin portal over HTTP.

`test_admin_portal_policy.py` proves the rules. This proves the app actually
consults them — which is the failure mode that matters, because a route that
renders a permitted-looking page and then acts without re-checking is exactly as
exploitable as having no rules at all.

So the shape of most tests here is: hide the button, *and* refuse the POST. A
hand-crafted request must get the same answer as the page.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    # `settings` is a module-level instance built at first import, so setting
    # HUB_DB_PATH here would be read too late and every test in this file would
    # share the developer's real hub.db — which is how the first version of
    # this fixture had one test create an account that made the next one pass
    # for the wrong reason. Patch the resolved attribute, then reload the app
    # so its module-level store is built against it.
    from config import settings as cfg
    monkeypatch.setattr(cfg, "db_path", str(tmp_path / "admin.db"))
    monkeypatch.setenv("HUB_ADMIN_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("HUB_ADMIN_SECRET", "portal-secret-for-tests")
    monkeypatch.setenv("HUB_COOKIE_SECURE", "0")   # TestClient speaks http://
    import importlib
    import admin_app
    importlib.reload(admin_app)
    from fastapi.testclient import TestClient
    return TestClient(admin_app.app, follow_redirects=False), admin_app


def test_the_fixture_really_is_isolated(client, tmp_path):
    """Guards the fixture itself. If this drifts back to the shared database,
    every other test in the file starts passing or failing for reasons that
    have nothing to do with the portal."""
    _c, mod = client
    assert str(tmp_path) in mod.store.path
    assert mod.store.list_users() == []


def _seed(mod):
    """One of every role, plus the owner the deployment always has."""
    mod.store.create_user("owner@example.com", "pw-strong-123", role="owner")
    mod.store.create_user("admin@example.com", "pw-strong-123", role="admin")
    mod.store.create_user("admin2@example.com", "pw-strong-123", role="admin")
    mod.store.create_user("op@example.com", "pw-strong-123", role="operator")
    mod.store.create_user("viewer@example.com", "pw-strong-123", role="viewer")


def _sign_in(client, username="owner@example.com", password="pw-strong-123"):
    return client.post("/login", data={"username": username, "password": password})


# ═══════════════════════════════════════════ the front door

def test_the_index_is_closed_to_anonymous_callers(client):
    c, _mod = client
    r = c.get("/")
    assert r.status_code == 303 and "/login" in r.headers["location"]


def test_an_operator_is_refused_at_the_door(client):
    """Not shown an empty page — refused. A signed-in non-admin on this app is
    one missing check away from acting."""
    c, mod = client
    _seed(mod)
    r = _sign_in(c, "op@example.com")
    assert "error=" in r.headers["location"]
    assert c.get("/").status_code == 303


def test_an_admin_can_sign_in_and_see_the_accounts(client):
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    body = c.get("/").text
    assert "admin@example.com" in body and "op@example.com" in body


def test_a_wrong_password_does_not_say_which_part_was_wrong(client):
    c, mod = client
    _seed(mod)
    r = _sign_in(c, "owner@example.com", "nope")
    assert "Incorrect+username+or+password" in r.headers["location"]


def test_a_disabled_admin_cannot_sign_in(client):
    c, mod = client
    _seed(mod)
    mod.store.soft_delete_user("admin@example.com")
    assert "error=" in _sign_in(c, "admin@example.com").headers["location"]


def test_two_factor_is_demanded_when_the_admin_has_it_on(client):
    """A second door that skipped it would be the way to avoid it."""
    c, mod = client
    _seed(mod)
    mod.store.set_totp_secret("owner@example.com", "JBSWY3DPEHPK3PXP")
    mod.store.enable_totp("owner@example.com", [])
    r = _sign_in(c)
    assert "/two-factor" in r.headers["location"]
    # And the password alone did NOT open a session.
    assert c.get("/").status_code == 303


def test_a_pending_two_factor_ticket_is_not_a_session(client):
    """The ticket is minted before the second factor. If it were accepted as a
    portal cookie, 2FA would be advisory."""
    c, mod = client
    _seed(mod)
    mod.store.set_totp_secret("owner@example.com", "JBSWY3DPEHPK3PXP")
    mod.store.enable_totp("owner@example.com", [])
    _sign_in(c)
    pending = c.cookies.get(mod.PENDING_COOKIE)
    assert pending
    c.cookies.clear()
    c.cookies.set(mod.COOKIE, pending)
    assert c.get("/").status_code == 303


# ═══════════════════════════════════════════ cookie separation

def test_a_trading_app_cookie_does_not_open_the_portal(client):
    """The reason this is a separate process at all. If a stolen user session
    works here, the separation is decoration."""
    c, mod = client
    _seed(mod)
    from services.session_auth import sign
    from services import admin_portal as policy
    c.cookies.set(mod.COOKIE, sign("owner@example.com", policy.admin_secret(),
                                   ttl_days=7))
    assert c.get("/").status_code == 303


def test_a_revoked_portal_session_stops_working_immediately(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    assert c.get("/").status_code == 200
    mod.store.revoke_all_sessions("owner@example.com", by="test")
    assert c.get("/").status_code == 303


def test_signing_out_revokes_the_row_not_just_the_cookie(client):
    """Deleting the cookie alone leaves a valid session id in the wild."""
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.get("/logout")
    assert mod.store.list_sessions("owner@example.com") == []


def test_a_demotion_takes_effect_on_the_next_request(client):
    """The actor's row is re-read every request. Trusting the cookie's claim
    would leave a demoted admin operating until it expired."""
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    assert c.get("/").status_code == 200
    mod.store.set_role("admin@example.com", "operator")
    assert c.get("/").status_code == 303


# ═══════════════════════════════════════════ creating accounts

def test_an_admin_cannot_create_an_admin_by_posting_directly(client):
    """The page hides the option. This proves the handler refuses it too — the
    hidden-field bypass is the whole reason to check twice."""
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    c.post("/users", data={"username": "new@example.com",
                           "password": "pw-strong-123", "role": "admin"})
    assert mod.store.get_user("new@example.com") is None


def test_the_owner_can_create_an_admin(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users", data={"username": "new@example.com",
                           "password": "pw-strong-123", "role": "admin"})
    assert mod.store.get_user("new@example.com").role == "admin"


def test_nobody_can_create_an_owner(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users", data={"username": "second-owner@example.com",
                           "password": "pw-strong-123", "role": "owner"})
    assert mod.store.get_user("second-owner@example.com") is None


def test_creating_a_duplicate_is_refused_without_touching_the_existing_row(client):
    """Silently resetting the existing account's password would be an account
    takeover dressed as a typo."""
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users", data={"username": "op@example.com",
                           "password": "attacker-chosen", "role": "viewer"})
    assert mod.store.authenticate("op@example.com", "pw-strong-123")
    assert mod.store.get_user("op@example.com").role == "operator"


# ═══════════════════════════════════════════ roles

def test_an_admin_cannot_promote_anyone_to_admin_by_posting_directly(client):
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    c.post("/users/op@example.com/role", data={"role": "admin"})
    assert mod.store.get_user("op@example.com").role == "operator"


def test_an_admin_cannot_demote_the_owner(client):
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    c.post("/users/owner@example.com/role", data={"role": "viewer"})
    assert mod.store.get_user("owner@example.com").role == "owner"


def test_an_admin_cannot_demote_another_admin(client):
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    c.post("/users/admin2@example.com/role", data={"role": "viewer"})
    assert mod.store.get_user("admin2@example.com").role == "admin"


def test_nobody_can_change_their_own_role(client):
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    c.post("/users/admin@example.com/role", data={"role": "owner"})
    assert mod.store.get_user("admin@example.com").role == "admin"


def test_the_owner_can_demote_an_admin(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users/admin@example.com/role", data={"role": "operator"})
    assert mod.store.get_user("admin@example.com").role == "operator"


def test_a_role_change_ends_that_users_existing_sessions(client):
    """Otherwise a demoted account keeps acting with its old privileges until
    the cookie expires — the change looks applied and is not."""
    c, mod = client
    _seed(mod)
    mod.store.create_session("admin2@example.com", "their-laptop", ttl_days=7)
    _sign_in(c)
    c.post("/users/admin2@example.com/role", data={"role": "viewer"})
    assert not mod.store.session_is_valid("their-laptop")


def test_a_role_change_does_not_end_the_actors_own_sessions(client):
    """Acting on someone else must not sign the administrator out mid-task."""
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users/op@example.com/role", data={"role": "viewer"})
    assert c.get("/").status_code == 200


def test_an_unknown_role_string_is_refused(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users/op@example.com/role", data={"role": "superuser"})
    assert mod.store.get_user("op@example.com").role == "operator"


# ═══════════════════════════════════════════ disable / restore

def test_an_admin_can_disable_an_operator(client):
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    c.post("/users/op@example.com/disable")
    assert mod.store.authenticate("op@example.com", "pw-strong-123") is None


def test_an_admin_cannot_disable_the_owner(client):
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    c.post("/users/owner@example.com/disable")
    assert mod.store.authenticate("owner@example.com", "pw-strong-123")


def test_the_last_owner_cannot_be_disabled(client):
    """The deployment would be left with no administrator and no way back —
    signup only re-opens when there are no users at all."""
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users/owner@example.com/disable")
    assert mod.store.authenticate("owner@example.com", "pw-strong-123")


def test_disabling_ends_every_session_that_account_holds(client):
    c, mod = client
    _seed(mod)
    mod.store.create_session("op@example.com", "their-phone", ttl_days=7)
    _sign_in(c)
    c.post("/users/op@example.com/disable")
    assert not mod.store.session_is_valid("their-phone")


def test_a_disabled_account_can_be_restored(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users/op@example.com/disable")
    c.post("/users/op@example.com/restore")
    assert mod.store.authenticate("op@example.com", "pw-strong-123")


def test_an_admin_cannot_restore_a_disabled_admin(client):
    """Restoring an admin is granting the role back with extra steps."""
    c, mod = client
    _seed(mod)
    mod.store.soft_delete_user("admin2@example.com")
    _sign_in(c, "admin@example.com")
    c.post("/users/admin2@example.com/restore")
    assert mod.store.authenticate("admin2@example.com", "pw-strong-123") is None


# ═══════════════════════════════════════════ session revocation

def test_an_admin_can_sign_another_account_out_everywhere(client):
    c, mod = client
    _seed(mod)
    mod.store.create_session("op@example.com", "their-laptop", ttl_days=7)
    _sign_in(c, "admin@example.com")
    c.post("/users/op@example.com/revoke")
    assert not mod.store.session_is_valid("their-laptop")


def test_an_admin_cannot_sign_the_owner_out(client):
    """Otherwise an admin can disrupt the owner mid-incident."""
    c, mod = client
    _seed(mod)
    mod.store.create_session("owner@example.com", "owner-laptop", ttl_days=7)
    _sign_in(c, "admin@example.com")
    c.post("/users/owner@example.com/revoke")
    assert mod.store.session_is_valid("owner-laptop")


def test_acting_on_an_unknown_account_is_refused_not_a_500(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    for path in ("role", "disable", "restore", "revoke"):
        r = c.post(f"/users/ghost@example.com/{path}", data={"role": "viewer"})
        assert r.status_code == 303, path
        assert "error=" in r.headers["location"], path


# ═══════════════════════════════════════════ every action needs a session

def test_every_mutating_route_refuses_an_anonymous_caller(client):
    c, mod = client
    _seed(mod)
    c.cookies.clear()
    for path, body in (("/users", {"username": "x@example.com",
                                   "password": "pw-strong-123", "role": "viewer"}),
                       ("/users/op@example.com/role", {"role": "viewer"}),
                       ("/users/op@example.com/disable", {}),
                       ("/users/op@example.com/restore", {}),
                       ("/users/op@example.com/revoke", {})):
        r = c.post(path, data=body)
        assert "/login" in r.headers["location"], path
    assert mod.store.get_user("x@example.com") is None
    assert mod.store.get_user("op@example.com").role == "operator"


# ═══════════════════════════════════════════ audit

def test_a_successful_action_is_recorded(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    c.post("/users/op@example.com/role", data={"role": "viewer"})
    lines = mod.AUDIT_PATH.read_text().strip().splitlines()
    assert any('"action": "set_role"' in ln and '"allowed": true' in ln
               for ln in lines)


def test_a_REFUSED_action_is_recorded_too(client):
    """The more interesting half. A run of refusals is what an escalation
    attempt looks like, and a log of successes alone cannot show it."""
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    c.post("/users/owner@example.com/role", data={"role": "viewer"})
    lines = mod.AUDIT_PATH.read_text().strip().splitlines()
    assert any('"allowed": false' in ln and "owner@example.com" in ln
               for ln in lines)


def test_a_failed_sign_in_is_recorded(client):
    c, mod = client
    _seed(mod)
    _sign_in(c, "owner@example.com", "wrong")
    assert '"action": "login"' in mod.AUDIT_PATH.read_text()


def test_the_audit_log_never_contains_a_password(client):
    """It records what was attempted, not what was typed."""
    c, mod = client
    _seed(mod)
    _sign_in(c, "owner@example.com", "hunter2-the-secret")
    _sign_in(c)
    c.post("/users", data={"username": "new@example.com",
                           "password": "another-secret-pw", "role": "viewer"})
    text = mod.AUDIT_PATH.read_text()
    assert "hunter2-the-secret" not in text
    assert "another-secret-pw" not in text


# ═══════════════════════════════════════════ the page tells the truth

def test_the_page_hides_actions_the_caller_may_not_take(client):
    """Rendering a button that always fails trains people to ignore errors."""
    c, mod = client
    _seed(mod)
    _sign_in(c, "admin@example.com")
    body = c.get("/").text
    # An admin may not act on the owner, so no owner-targeted form is drawn.
    assert "/users/owner@example.com/disable" not in body
    assert "/users/owner@example.com/role" not in body
    # ...but may act on an operator.
    assert "/users/op@example.com/disable" in body


def test_the_portal_is_marked_noindex(client):
    c, mod = client
    _seed(mod)
    _sign_in(c)
    assert "noindex" in c.get("/").text


def test_the_portal_exposes_no_api_documentation(client):
    """The schema of an admin surface is a map for whoever finds the port."""
    c, _mod = client
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert c.get(path).status_code == 404, path


def test_health_answers_without_a_session(client):
    """So a container health check does not need a credential."""
    c, _mod = client
    assert c.get("/health").json()["ok"] is True
