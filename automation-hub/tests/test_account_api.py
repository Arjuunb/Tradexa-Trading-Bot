"""The account API: profile, sessions, deletion — over HTTP.

The store tests prove the data layer. These prove the *authorisation* layer,
which is where account APIs actually go wrong: identity comes from the session
and nowhere else, so no body field can make one user act as another.

Broken object-level authorisation is the single most common API vulnerability,
and it looks exactly like a convenience — accepting a `username` in the body so
an admin tool can reuse the endpoint. Several tests here exist only to prove
that convenience is absent.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    return TestClient(hub_app.app)


@pytest.fixture()
def auth():
    import app as hub_app
    return {"X-Webhook-Secret": hub_app.settings.webhook_secret}


def _signed_in(client, auth, username="user@example.com", password="pw-strong-123",
               remember=""):
    """A client holding a real session cookie for `username`."""
    import app as hub_app
    if hub_app.store.get_user(username) is None:
        hub_app.store.create_user(username, password)
    else:
        hub_app.store.restore_user(username)
        hub_app.store.set_password(username, password)
    data = {"username": username, "password": password}
    if remember:
        data["remember"] = remember
    assert client.post("/auth/login", data=data, headers=auth).status_code == 200
    return client


# ═══════════════════════════════════════════ authentication required

def test_every_account_route_refuses_an_anonymous_caller(client, auth):
    """A 200 on any of these without a session would expose or destroy an
    account belonging to nobody in particular."""
    client.cookies.clear()
    # GET takes no body; the others do. Sent separately because TestClient.get()
    # rejects a `json=` kwarg — an earlier version of this test passed one to
    # every route and failed on the transport rather than on the assertion.
    for path in ("/account/profile", "/account/sessions"):
        assert client.get(path, headers=auth).status_code == 401, path
    for method, path, body in (
            ("patch", "/account/profile", {}),
            ("post", "/account/sessions/revoke-others", {}),
            ("post", "/account/sessions/anything/revoke", {}),
            ("post", "/account/delete", {"password": "x", "confirm": "DELETE"})):
        response = getattr(client, method)(path, headers=auth, json=body)
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


# ═══════════════════════════════════════════ profile

def test_the_profile_reports_the_signed_in_account(client, auth):
    _signed_in(client, auth, "alice@example.com")
    body = client.get("/account/profile", headers=auth).json()
    assert body["username"] == "alice@example.com"
    assert body["display_name"]


def test_a_patch_updates_only_what_it_names(client, auth):
    _signed_in(client, auth, "alice@example.com")
    client.patch("/account/profile", headers=auth,
                 json={"full_name": "Alice Chen", "avatar_url": "https://x/a.png"})
    client.patch("/account/profile", headers=auth, json={"timezone": "Europe/London"})
    body = client.get("/account/profile", headers=auth).json()
    assert body["full_name"] == "Alice Chen"
    assert body["avatar_url"] == "https://x/a.png"
    assert body["timezone"] == "Europe/London"


def test_the_profile_never_returns_credentials(client, auth):
    """A profile endpoint that leaks the hash turns a read into an offline
    cracking job."""
    _signed_in(client, auth, "alice@example.com")
    body = client.get("/account/profile", headers=auth).json()
    for secret in ("password_hash", "salt", "totp_secret", "password"):
        assert secret not in body


def test_a_patch_cannot_change_the_role(client, auth):
    """Role changes belong to the admin surface with its escalation guard. If
    this ever succeeds, any user can make themselves an owner."""
    _signed_in(client, auth, "alice@example.com")
    client.patch("/account/profile", headers=auth, json={"role": "owner"})
    assert client.get("/account/profile", headers=auth).json()["role"] != "owner"


def test_a_patch_cannot_change_the_email(client, auth):
    """An unverified email change is an account-takeover primitive: set the
    address, then use password reset."""
    import app as hub_app
    _signed_in(client, auth, "alice@example.com")
    hub_app.store.set_email("alice@example.com", "alice@real.example", verified=True)
    client.patch("/account/profile", headers=auth,
                 json={"email": "attacker@evil.example"})
    assert client.get("/account/profile", headers=auth).json()["email"] == "alice@real.example"


def test_the_profile_is_the_callers_regardless_of_what_the_body_says(client, auth):
    """Identity comes from the session. A username in the body must not move
    the target — the classic broken-object-level-authorisation bug."""
    import app as hub_app
    hub_app.store.create_user("victim@example.com", "pw-strong-123")
    _signed_in(client, auth, "alice@example.com")
    client.patch("/account/profile", headers=auth,
                 json={"username": "victim@example.com", "full_name": "Pwned"})
    assert hub_app.store.get_user("victim@example.com").full_name != "Pwned"


# ═══════════════════════════════════════════ sessions

def test_the_session_list_marks_the_current_device(client, auth):
    """Without this a user cannot tell which row is the browser they are
    reading it in, and "sign out everywhere" becomes a coin flip."""
    _signed_in(client, auth, "alice@example.com")
    body = client.get("/account/sessions", headers=auth).json()
    assert body["count"] >= 1
    assert any(s["current"] for s in body["sessions"])


def test_remember_me_is_visible_in_the_session_list(client, auth):
    _signed_in(client, auth, "alice@example.com", remember="on")
    current = [s for s in client.get("/account/sessions", headers=auth).json()["sessions"]
               if s["current"]][0]
    assert current["remembered"] is True


def test_a_normal_login_is_not_remembered(client, auth):
    _signed_in(client, auth, "alice@example.com")
    current = [s for s in client.get("/account/sessions", headers=auth).json()["sessions"]
               if s["current"]][0]
    assert current["remembered"] is False


def test_revoking_the_current_session_signs_this_browser_out(client, auth):
    """The revocation has to bite on the very next request — a revoked session
    that keeps working until it expires is not a revocation."""
    _signed_in(client, auth, "alice@example.com")
    current = [s for s in client.get("/account/sessions", headers=auth).json()["sessions"]
               if s["current"]][0]
    assert client.post(f"/account/sessions/{current['id']}/revoke",
                       headers=auth).status_code == 200
    assert client.get("/account/profile", headers=auth).status_code == 401


def test_a_user_cannot_revoke_another_users_session(client, auth):
    import app as hub_app
    hub_app.store.create_user("victim@example.com", "pw-strong-123")
    hub_app.store.create_session("victim@example.com", "victim-session", ttl_days=7)
    _signed_in(client, auth, "alice@example.com")
    assert client.post("/account/sessions/victim-session/revoke",
                       headers=auth).status_code == 404
    assert hub_app.store.session_is_valid("victim-session")


def test_revoking_an_unknown_session_is_a_404_not_a_500(client, auth):
    _signed_in(client, auth, "alice@example.com")
    assert client.post("/account/sessions/no-such-id/revoke",
                       headers=auth).status_code == 404


def test_sign_out_everywhere_keeps_the_current_browser(client, auth):
    """The button someone reaches for after losing a laptop. Logging *them*
    out at the same moment is the one outcome that makes it unusable."""
    import app as hub_app
    _signed_in(client, auth, "alice@example.com")
    hub_app.store.create_session("alice@example.com", "old-laptop", ttl_days=7)
    body = client.post("/account/sessions/revoke-others", headers=auth).json()
    assert body["revoked"] >= 1 and body["kept_current"] is True
    assert not hub_app.store.session_is_valid("old-laptop")
    assert client.get("/account/profile", headers=auth).status_code == 200


# ═══════════════════════════════════════════ deletion

def _delete(client, auth, **body):
    return client.post("/account/delete", headers=auth, json=body)


def test_deletion_requires_the_typed_confirmation(client, auth):
    """Stops the owner clicking through a dialog."""
    _signed_in(client, auth, "alice@example.com")
    assert _delete(client, auth, password="pw-strong-123").status_code == 400
    assert _delete(client, auth, password="pw-strong-123",
                   confirm="yes").status_code == 400


def test_deletion_requires_the_password(client, auth):
    """A session cookie proves who you are; it does not prove you are still at
    the keyboard. Without this, an unlocked laptop is a total loss."""
    _signed_in(client, auth, "alice@example.com")
    assert _delete(client, auth, password="wrong", confirm="DELETE").status_code == 403


def test_a_confirmed_deletion_disables_the_account_and_the_session(client, auth):
    import app as hub_app
    _signed_in(client, auth, "alice@example.com")
    assert _delete(client, auth, password="pw-strong-123",
                   confirm="DELETE").status_code == 200
    assert hub_app.store.authenticate("alice@example.com", "pw-strong-123") is None
    assert client.get("/account/profile", headers=auth).status_code == 401


def test_the_last_owner_cannot_delete_themselves(client, auth):
    """It would leave the deployment with no administrator and no way back in —
    signup only mints an owner when there are no users at all."""
    import app as hub_app
    hub_app.store.create_user("solo-owner@example.com", "pw-strong-123", role="owner")
    for user in hub_app.store.list_users():
        if user.role == "owner" and user.username != "solo-owner@example.com":
            hub_app.store.soft_delete_user(user.username)
    _signed_in(client, auth, "solo-owner@example.com")
    response = _delete(client, auth, password="pw-strong-123", confirm="DELETE")
    assert response.status_code == 409
    assert "owner" in response.json()["detail"]
    assert hub_app.store.authenticate("solo-owner@example.com", "pw-strong-123")


def test_deletion_is_reported_as_recoverable(client, auth):
    """A user who deletes by mistake needs to know there is a way back before
    they write a support ticket."""
    _signed_in(client, auth, "alice@example.com")
    body = _delete(client, auth, password="pw-strong-123", confirm="DELETE").json()
    assert body["recoverable_until_days"] == 30
