"""Sign in with Apple.

Apple differs from Google and GitHub in ways that make it its own code path,
and every test here exists because one of those differences is a place to get
it wrong:

  · the client secret is an ES256 JWT you sign, not a string you paste
  · there is no userinfo endpoint — the identity is inside the id_token
  · the callback arrives as a POST form, not query parameters
  · the user's name is sent once, at first authorization, and never again
"""
from __future__ import annotations

import importlib

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization          # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec          # noqa: E402


def _p8() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


@pytest.fixture()
def apple(monkeypatch):
    """oauth module with Apple fully configured."""
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.tradelogx.web")
    monkeypatch.setenv("APPLE_TEAM_ID", "ABC123TEAM")
    monkeypatch.setenv("APPLE_KEY_ID", "KEY123")
    monkeypatch.setenv("APPLE_PRIVATE_KEY", _p8())
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://trade-logx.com")
    import services.oauth as o
    return importlib.reload(o)


def _id_token(**claims) -> str:
    return jwt.encode(claims, "k" * 32, algorithm="HS256")


# ═══════════════════════════════════════════ the client secret

def test_the_client_secret_is_a_signed_es256_jwt(apple):
    """Apple has no static secret to paste. This is the piece that is not like
    the other providers."""
    secret = apple.apple_client_secret()
    assert secret and len(secret.split(".")) == 3
    assert jwt.get_unverified_header(secret)["alg"] == "ES256"


def test_the_secret_carries_the_claims_apple_requires(apple):
    body = jwt.decode(apple.apple_client_secret(), options={"verify_signature": False})
    assert body["iss"] == "ABC123TEAM"
    assert body["aud"] == "https://appleid.apple.com"
    assert body["sub"] == "com.tradelogx.web"
    assert jwt.get_unverified_header(apple.apple_client_secret())["kid"] == "KEY123"


def test_the_secret_stays_inside_apples_six_month_ceiling(apple):
    body = jwt.decode(apple.apple_client_secret(), options={"verify_signature": False})
    assert 0 < (body["exp"] - body["iat"]) <= 86400 * 183


def test_a_missing_variable_yields_no_secret_rather_than_a_broken_one(apple,
                                                                     monkeypatch):
    """A malformed client secret fails at Apple with an opaque error that is
    very hard to diagnose from this side."""
    monkeypatch.delenv("APPLE_TEAM_ID")
    import services.oauth as o
    assert importlib.reload(o).apple_client_secret() is None


def test_an_unusable_private_key_yields_no_secret(apple, monkeypatch):
    monkeypatch.setenv("APPLE_PRIVATE_KEY", "-----BEGIN NOT A KEY-----")
    import services.oauth as o
    assert importlib.reload(o).apple_client_secret() is None


# ═══════════════════════════════════════════ configuration reporting

def test_apple_is_only_offered_when_it_can_actually_work(apple):
    """A social button that renders but cannot work is worse than an absent
    one: it fails after the user has committed to the flow."""
    assert apple.is_configured(apple.APPLE) is True
    assert apple.available()["apple"]["available"] is True


def test_an_unconfigured_apple_is_hidden(monkeypatch):
    for var in ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID",
                "APPLE_PRIVATE_KEY"):
        monkeypatch.delenv(var, raising=False)
    import services.oauth as o
    o = importlib.reload(o)
    assert o.is_configured(o.APPLE) is False
    assert o.available()["apple"]["available"] is False


def test_the_missing_variable_is_named_individually(apple, monkeypatch):
    """"Set APPLE_PRIVATE_KEY" is useless advice when the team id is what is
    actually missing."""
    monkeypatch.delenv("APPLE_KEY_ID")
    import services.oauth as o
    assert "APPLE_KEY_ID" in importlib.reload(o).available()["apple"]["note"]


def test_a_present_but_unusable_key_is_reported_as_such(apple, monkeypatch):
    monkeypatch.setenv("APPLE_PRIVATE_KEY", "garbage")
    import services.oauth as o
    note = importlib.reload(o).available()["apple"]["note"]
    assert "valid APPLE_PRIVATE_KEY" in note


def test_the_redirect_uri_matches_the_other_providers_shape(apple):
    assert (apple.redirect_uri(apple.APPLE)
            == "https://trade-logx.com/auth/oauth/apple/callback")


# ═══════════════════════════════════════════ identity from the id_token

def test_the_identity_comes_from_the_id_token(apple):
    profile = apple.parse_apple_identity(
        _id_token(sub="001234.abcdef", email="user@example.com",
                  email_verified="true"))
    assert profile.provider == "apple"
    assert profile.subject == "001234.abcdef"
    assert profile.email == "user@example.com"
    assert profile.email_verified is True


def test_email_verified_is_read_as_both_a_bool_and_a_string(apple):
    """Apple sends it either way depending on the flow."""
    assert apple.parse_apple_identity(_id_token(sub="s", email_verified=True)).email_verified
    assert apple.parse_apple_identity(_id_token(sub="s", email_verified="true")).email_verified
    assert not apple.parse_apple_identity(_id_token(sub="s", email_verified="false")).email_verified


def test_a_private_relay_address_is_kept_as_is(apple):
    """Rewriting or rejecting it would break Sign in with Apple's headline
    feature — and it is a real, deliverable address."""
    profile = apple.parse_apple_identity(
        _id_token(sub="s", email="abc@privaterelay.appleid.com"))
    assert profile.email == "abc@privaterelay.appleid.com"


def test_a_token_without_a_subject_is_refused(apple):
    """The subject is the stable key the account is linked by. Without it there
    is nothing to link to."""
    assert apple.parse_apple_identity(_id_token(email="a@b.c")) is None


def test_garbage_is_refused_rather_than_raising(apple):
    assert apple.parse_apple_identity("not-a-jwt") is None
    assert apple.parse_apple_identity("") is None


def test_the_name_is_not_invented(apple):
    """Apple sends it once, in the first authorization POST — never in the
    id_token. Deriving one from the email would be a guess presented as data."""
    assert apple.parse_apple_identity(_id_token(sub="s", email="jane@x.io")).name is None


# ═══════════════════════════════════════════ routing

def test_apple_is_registered_as_a_provider(apple):
    assert apple.get_provider("apple") is apple.APPLE
    assert "apple" in apple.PROVIDERS


def test_apple_declares_no_profile_endpoint(apple):
    """Empty rather than a plausible-looking URL, so a caller that reaches for
    the generic path fails loudly instead of GETting something that does not
    exist."""
    assert apple.APPLE.profile_endpoint == ""


def test_the_callback_accepts_a_post(apple):
    """Apple uses response_mode=form_post when the scope includes name or
    email. A GET-only route would 405 the whole sign-in."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    client = TestClient(hub_app.app)
    response = client.post("/auth/oauth/apple/callback",
                           data={"code": "x", "state": "bad"},
                           headers={"X-Webhook-Secret": hub_app.settings.webhook_secret},
                           follow_redirects=False)
    # Rejected on the state check — which is the point: it got past routing.
    assert response.status_code != 405
