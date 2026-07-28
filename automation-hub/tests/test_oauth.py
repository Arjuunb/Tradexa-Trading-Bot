"""OAuth sign-in — the parts that decide security, tested without a network.

URL construction, state signing and profile parsing are pure; the two network
calls are thin wrappers over urllib and are exercised through the endpoint
tests with a stubbed transport.
"""
import time

import pytest

from database.store import SqliteStore
from services import oauth

SECRET = "test-secret-not-the-real-one"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://hub.example.com")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "github-secret")


# ------------------------------------------------------------ configuration

def test_both_providers_report_available_when_configured():
    a = oauth.available()
    assert a["google"]["available"] is True and a["github"]["available"] is True


def test_a_provider_without_credentials_says_what_is_missing(monkeypatch):
    """A social button that renders but cannot work is worse than an absent
    one — it fails after the user has committed to the flow."""
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    g = oauth.available()["google"]
    assert g["available"] is False and "GOOGLE_CLIENT_SECRET" in g["note"]


def test_without_a_public_url_no_provider_is_available(monkeypatch):
    """The redirect URI is built from it; without one the provider would send
    the user back to nowhere."""
    monkeypatch.delenv("HUB_PUBLIC_URL", raising=False)
    assert all(not v["available"] for v in oauth.available().values())


def test_the_redirect_uri_is_the_callback_route():
    assert (oauth.redirect_uri(oauth.GOOGLE)
            == "https://hub.example.com/auth/oauth/google/callback")


def test_an_unknown_provider_resolves_to_nothing():
    assert oauth.get_provider("facebook") is None
    assert oauth.get_provider("") is None


# -------------------------------------------------------------- authorize url

def test_the_authorize_url_carries_everything_the_provider_needs():
    url = oauth.authorize_url(oauth.GOOGLE, "state-123")
    assert url.startswith(oauth.GOOGLE.authorize_endpoint + "?")
    for part in ("client_id=google-client-id", "response_type=code",
                 "state=state-123", "scope=openid+email+profile"):
        assert part in url
    assert "redirect_uri=https%3A%2F%2Fhub.example.com%2Fauth%2Foauth%2Fgoogle%2Fcallback" in url


def test_the_client_secret_never_appears_in_the_redirect_url():
    """It goes server-to-server at token exchange. In the authorize URL it
    would be handed to the browser, and to anything reading history or logs."""
    assert "google-secret" not in oauth.authorize_url(oauth.GOOGLE, "s")
    assert "github-secret" not in oauth.authorize_url(oauth.GITHUB, "s")


def test_google_is_asked_to_show_the_account_chooser():
    """Without it Google silently reuses whichever account the browser is
    already signed into, which is not what someone clicking 'sign in' means."""
    assert "prompt=select_account" in oauth.authorize_url(oauth.GOOGLE, "s")


# --------------------------------------------------------------------- state

def test_a_signed_state_verifies():
    assert oauth.verify_state(oauth.sign_state(SECRET), SECRET) is True


def test_a_tampered_state_does_not():
    """State is the CSRF guard on the callback: without it an attacker can feed
    a victim's browser a code of their choosing and link accounts silently."""
    s = oauth.sign_state(SECRET)
    assert oauth.verify_state(s + "x", SECRET) is False
    assert oauth.verify_state(s.replace(".", ".x", 1), SECRET) is False


def test_a_state_signed_with_another_secret_does_not_verify():
    assert oauth.verify_state(oauth.sign_state("other-secret"), SECRET) is False


def test_a_stale_state_expires():
    old = oauth.sign_state(SECRET, now=time.time() - oauth.STATE_TTL_S - 1)
    assert oauth.verify_state(old, SECRET) is False


def test_a_state_from_the_future_is_refused():
    ahead = oauth.sign_state(SECRET, now=time.time() + 120)
    assert oauth.verify_state(ahead, SECRET) is False


def test_malformed_state_is_refused_without_raising():
    for bad in ("", "x", "a.b", "a.b.c", None):
        assert oauth.verify_state(bad, SECRET) is False


def test_two_states_differ():
    assert oauth.sign_state(SECRET) != oauth.sign_state(SECRET)


# ------------------------------------------------------------ profile parsing

def test_a_google_profile_is_keyed_by_subject_not_email():
    p = oauth.parse_google_profile({"sub": "10842", "email": "arjun@example.com",
                                    "email_verified": True, "name": "Arjun"})
    assert p.subject == "10842" and p.provider == "google"
    assert p.email == "arjun@example.com" and p.email_verified is True


def test_a_google_profile_without_a_subject_is_unusable():
    assert oauth.parse_google_profile({"email": "arjun@example.com"}) is None


def test_google_email_verified_false_is_carried_through():
    p = oauth.parse_google_profile({"sub": "1", "email": "a@b.c",
                                    "email_verified": False})
    assert p.email_verified is False


def test_a_github_profile_prefers_the_primary_verified_address():
    """/user omits the email when it is private, so it comes from /user/emails —
    and only a primary AND verified entry counts as proof of ownership."""
    p = oauth.parse_github_profile(
        {"id": 55, "login": "arjuunb", "email": None},
        [{"email": "old@example.com", "primary": False, "verified": True},
         {"email": "arjun@example.com", "primary": True, "verified": True}])
    assert p.subject == "55" and p.email == "arjun@example.com"
    assert p.email_verified is True


def test_an_unverified_github_address_is_not_marked_verified():
    """Anyone can add an address to a GitHub account. Treating that as proof
    would let them claim the matching local account."""
    p = oauth.parse_github_profile(
        {"id": 55, "login": "arjuunb", "email": "claimed@example.com"},
        [{"email": "claimed@example.com", "primary": True, "verified": False}])
    assert p.email_verified is False


def test_a_github_profile_with_private_email_still_identifies_the_account():
    p = oauth.parse_github_profile({"id": 55, "login": "arjuunb", "email": None}, None)
    assert p.subject == "55" and p.email_verified is False


def test_a_github_profile_without_an_id_is_unusable():
    assert oauth.parse_github_profile({"login": "arjuunb"}, None) is None


# ------------------------------------------------------------------ linking

@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(tmp_path / "hub.db")
    s.create_user("arjun@example.com", "password-12345", role="owner")
    return s


def test_a_linked_identity_resolves_back_to_the_local_account(store):
    store.link_oauth("google", "10842", "arjun@example.com", "arjun@example.com")
    u = store.find_by_oauth("google", "10842")
    assert u is not None and u.username == "arjun@example.com"


def test_an_unlinked_subject_resolves_to_nobody(store):
    assert store.find_by_oauth("google", "99999") is None


def test_the_same_subject_on_a_different_provider_is_a_different_identity(store):
    """Provider ids are only unique within a provider. Keying on the id alone
    would let a GitHub user id collide with a Google one."""
    store.link_oauth("google", "42", "arjun@example.com")
    assert store.find_by_oauth("github", "42") is None


def test_relinking_the_same_identity_does_not_duplicate_it(store):
    store.link_oauth("google", "10842", "arjun@example.com")
    store.link_oauth("google", "10842", "arjun@example.com")
    assert len(store.list_oauth_links("arjun@example.com")) == 1


def test_unlinking_removes_the_sign_in_route(store):
    store.link_oauth("google", "10842", "arjun@example.com")
    store.unlink_oauth("google", "arjun@example.com")
    assert store.find_by_oauth("google", "10842") is None
    assert store.list_oauth_links("arjun@example.com") == []


def test_links_are_listed_for_the_account_that_owns_them(store):
    store.create_user("someone-else", "password-12345")
    store.link_oauth("google", "10842", "arjun@example.com")
    assert store.list_oauth_links("someone-else") == []
