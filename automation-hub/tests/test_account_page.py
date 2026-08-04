"""The /account page and its form handlers.

The JSON API is tested next door. This file exists because the page is not a
thin view over it: a browser `<form>` cannot send PATCH or a JSON body, so the
account page has its own set of POST handlers — and a second door into the same
operations is exactly where an authorisation check gets forgotten.

So the tests that matter here are the ones proving the form path is *not* the
weaker door: same session requirement, same password + typed confirmation on
delete, same last-owner guard, same cross-account refusal. A form handler that
skipped any of those would pass a "does the page render" test and still hand
away an account.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    # follow_redirects=False: every form handler answers with a 303, and the
    # redirect target is the assertion. Following it would hide which branch ran.
    return TestClient(hub_app.app, follow_redirects=False)


@pytest.fixture()
def auth():
    import app as hub_app
    return {"X-Webhook-Secret": hub_app.settings.webhook_secret}


def _signed_in(client, auth, username="page@example.com", password="pw-strong-123",
               remember=""):
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


def _page(client, auth, query=""):
    return client.get("/account" + query, headers=auth)


# ═══════════════════════════════════════════ the page itself

def test_the_page_sends_an_anonymous_visitor_to_the_login(client, auth):
    """A rendered account page for nobody in particular would leak whichever
    account the store happened to return first."""
    client.cookies.clear()
    response = _page(client, auth)
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_the_page_renders_all_three_sections(client, auth):
    _signed_in(client, auth)
    response = _page(client, auth)
    assert response.status_code == 200
    for heading in ("Profile", "Devices", "Delete account"):
        assert heading in response.text, heading


def test_the_page_shows_the_signed_in_identity(client, auth):
    _signed_in(client, auth, "whoami@example.com")
    assert "whoami@example.com" in _page(client, auth).text


def test_the_page_never_renders_a_credential(client, auth):
    """The page reads the User row, which carries the password hash. Rendering
    it into HTML would put it in every browser cache and proxy log."""
    import app as hub_app
    _signed_in(client, auth, "whoami@example.com")
    user = hub_app.store.get_user("whoami@example.com")
    body = _page(client, auth).text
    for secret in (user.password_hash, getattr(user, "totp_secret", None)):
        if secret:
            assert secret not in body


def test_a_field_value_is_escaped_rather_than_rendered(client, auth):
    """Profile fields are user-controlled and echoed straight back into the
    page — stored XSS against yourself is still stored XSS once an admin views
    the account."""
    import app as hub_app
    _signed_in(client, auth, "whoami@example.com")
    hub_app.store.update_profile("whoami@example.com",
                                 full_name='"><script>alert(1)</script>')
    body = _page(client, auth).text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_the_current_device_is_marked_and_has_no_sign_out_button(client, auth):
    """Offering "sign out" on the row you are reading it from is a trap: it
    looks like the way to end other sessions and ends yours instead."""
    _signed_in(client, auth)
    body = _page(client, auth).text
    assert "this device" in body
    # Asserted on the current row alone rather than on the whole page: the store
    # is process-wide, so earlier sign-ins leave other rows behind — and those
    # rows are *supposed* to carry a sign-out button.
    current_row = [row for row in body.split("<tr>") if "this device" in row][0]
    assert "/revoke-form" not in current_row


def test_another_device_gets_a_sign_out_button(client, auth):
    import app as hub_app
    _signed_in(client, auth)
    hub_app.store.create_session("page@example.com", "other-device", ttl_days=7,
                                 user_agent="Safari on iPhone")
    body = _page(client, auth).text
    assert "/account/sessions/other-device/revoke-form" in body
    assert "Safari on iPhone" in body


def test_a_session_from_before_this_release_is_explained_not_hidden(client, auth):
    """An empty device table on an account that is plainly signed in reads as a
    bug. Say why it is empty instead."""
    import app as hub_app
    from services.session_auth import sign
    hub_app.store.create_user("legacy@example.com", "pw-strong-123")
    client.cookies.clear()
    client.cookies.set(hub_app.COOKIE,
                       sign("legacy@example.com", hub_app.settings.secret_key,
                            ttl_days=7))
    assert "No recorded devices yet" in _page(client, auth).text


def test_an_error_from_a_form_is_shown_on_the_page(client, auth):
    """The form handlers report failure by redirecting with ?error=. A page that
    drops it makes a rejected password look like a form that did nothing."""
    _signed_in(client, auth)
    assert "That password is incorrect." in _page(
        client, auth, "?error=That+password+is+incorrect.").text


def test_the_flash_message_is_escaped(client, auth):
    """?error= is attacker-suppliable via a crafted link — the classic reflected
    XSS sink."""
    _signed_in(client, auth)
    body = _page(client, auth, "?error=%3Cscript%3Ealert(1)%3C/script%3E").text
    assert "<script>alert(1)</script>" not in body


# ═══════════════════════════════════════════ the profile form

def test_the_profile_form_saves_and_returns_to_the_page(client, auth):
    import app as hub_app
    _signed_in(client, auth)
    response = client.post("/account/profile-form", headers=auth,
                           data={"full_name": "Page Person",
                                 "timezone": "Europe/London",
                                 "avatar_url": "https://cdn.example/a.png"})
    assert response.status_code == 303
    assert response.headers["location"].startswith("/account")
    user = hub_app.store.get_user("page@example.com")
    assert user.full_name == "Page Person"
    assert user.timezone == "Europe/London"


def test_clearing_a_field_in_the_form_clears_it(client, auth):
    """A full form posts every field, so an emptied box means "remove this" —
    unlike the JSON PATCH, where an absent key means "leave alone"."""
    import app as hub_app
    _signed_in(client, auth)
    client.post("/account/profile-form", headers=auth,
                data={"full_name": "Page Person", "timezone": "", "avatar_url": ""})
    client.post("/account/profile-form", headers=auth,
                data={"full_name": "", "timezone": "", "avatar_url": ""})
    assert hub_app.store.get_user("page@example.com").full_name is None


def test_the_profile_form_refuses_an_anonymous_caller(client, auth):
    import app as hub_app
    hub_app.store.create_user("page@example.com", "pw-strong-123")
    hub_app.store.update_profile("page@example.com", full_name="Untouched")
    client.cookies.clear()
    response = client.post("/account/profile-form", headers=auth,
                           data={"full_name": "Pwned", "timezone": "",
                                 "avatar_url": ""})
    assert response.status_code == 303 and "/login" in response.headers["location"]
    assert hub_app.store.get_user("page@example.com").full_name == "Untouched"


# ═══════════════════════════════════════════ the session forms

def test_the_revoke_form_ends_that_session(client, auth):
    import app as hub_app
    _signed_in(client, auth)
    hub_app.store.create_session("page@example.com", "old-laptop", ttl_days=7)
    assert client.post("/account/sessions/old-laptop/revoke-form",
                       headers=auth).status_code == 303
    assert not hub_app.store.session_is_valid("old-laptop")


def test_the_revoke_form_cannot_reach_another_users_session(client, auth):
    """The form takes the session id from the URL. Identity comes from the
    cookie, so a guessed id must not be enough."""
    import app as hub_app
    hub_app.store.create_user("victim@example.com", "pw-strong-123")
    hub_app.store.create_session("victim@example.com", "victim-form-session",
                                 ttl_days=7)
    _signed_in(client, auth)
    client.post("/account/sessions/victim-form-session/revoke-form", headers=auth)
    assert hub_app.store.session_is_valid("victim-form-session")


def test_the_revoke_all_form_keeps_the_browser_that_asked(client, auth):
    import app as hub_app
    _signed_in(client, auth)
    hub_app.store.create_session("page@example.com", "old-phone", ttl_days=7)
    assert client.post("/account/sessions/revoke-others-form",
                       headers=auth).status_code == 303
    assert not hub_app.store.session_is_valid("old-phone")
    assert _page(client, auth).status_code == 200


def test_the_session_forms_refuse_an_anonymous_caller(client, auth):
    import app as hub_app
    hub_app.store.create_user("page@example.com", "pw-strong-123")
    hub_app.store.create_session("page@example.com", "survivor", ttl_days=7)
    client.cookies.clear()
    for path in ("/account/sessions/survivor/revoke-form",
                 "/account/sessions/revoke-others-form"):
        response = client.post(path, headers=auth)
        assert "/login" in response.headers["location"], path
    assert hub_app.store.session_is_valid("survivor")


# ═══════════════════════════════════════════ the delete form

def test_the_delete_form_requires_the_typed_confirmation(client, auth):
    import app as hub_app
    _signed_in(client, auth)
    response = client.post("/account/delete-form", headers=auth,
                           data={"password": "pw-strong-123", "confirm": "yes"})
    assert "error=" in response.headers["location"]
    assert hub_app.store.authenticate("page@example.com", "pw-strong-123")


def test_the_delete_form_requires_the_password(client, auth):
    """Same reason as the JSON endpoint: the cookie proves who you are, not that
    you are still at the keyboard."""
    import app as hub_app
    _signed_in(client, auth)
    response = client.post("/account/delete-form", headers=auth,
                           data={"password": "wrong", "confirm": "DELETE"})
    assert "error=" in response.headers["location"]
    assert hub_app.store.authenticate("page@example.com", "pw-strong-123")


def test_the_delete_form_refuses_the_last_owner(client, auth):
    """Deleting the only owner leaves the deployment with no administrator, and
    signup only re-opens when there are no users at all."""
    import app as hub_app
    hub_app.store.create_user("solo@example.com", "pw-strong-123", role="owner")
    for user in hub_app.store.list_users():
        if user.role == "owner" and user.username != "solo@example.com":
            hub_app.store.soft_delete_user(user.username)
    _signed_in(client, auth, "solo@example.com")
    response = client.post("/account/delete-form", headers=auth,
                           data={"password": "pw-strong-123", "confirm": "DELETE"})
    assert "only owner" in response.headers["location"].replace("+", " ").replace(
        "%20", " ")
    assert hub_app.store.authenticate("solo@example.com", "pw-strong-123")


def test_a_confirmed_delete_form_disables_the_account_and_clears_the_cookie(
        client, auth):
    import app as hub_app
    _signed_in(client, auth)
    response = client.post("/account/delete-form", headers=auth,
                           data={"password": "pw-strong-123", "confirm": "DELETE"})
    assert "/login" in response.headers["location"]
    assert hub_app.store.authenticate("page@example.com", "pw-strong-123") is None
    # The cookie is cleared on the way out, so the browser does not keep
    # presenting a session for an account that no longer answers.
    assert "hub_session=" in response.headers.get("set-cookie", "")
    assert _page(client, auth).status_code == 303


def test_the_delete_form_accepts_a_lowercase_confirmation(client, auth):
    """`delete` typed in a hurry is the same intent. The guard is against
    clicking through, not against the shift key."""
    import app as hub_app
    _signed_in(client, auth)
    client.post("/account/delete-form", headers=auth,
                data={"password": "pw-strong-123", "confirm": " delete "})
    assert hub_app.store.authenticate("page@example.com", "pw-strong-123") is None


def test_the_delete_form_refuses_an_anonymous_caller(client, auth):
    import app as hub_app
    hub_app.store.create_user("page@example.com", "pw-strong-123")
    hub_app.store.restore_user("page@example.com")
    hub_app.store.set_password("page@example.com", "pw-strong-123")
    client.cookies.clear()
    response = client.post("/account/delete-form", headers=auth,
                           data={"password": "pw-strong-123", "confirm": "DELETE"})
    assert "/login" in response.headers["location"]
    assert hub_app.store.authenticate("page@example.com", "pw-strong-123")
