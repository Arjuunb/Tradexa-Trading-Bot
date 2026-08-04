"""OAuth 2.0 sign-in with Google and GitHub. Stdlib only (urllib).

The authorization-code flow, without an SDK:

  1. ``authorize_url`` sends the browser to the provider with a signed ``state``
  2. the provider redirects back with a one-time ``code``
  3. ``exchange_code`` trades that code for an access token, server-to-server
  4. ``fetch_profile`` reads the account behind the token

Three decisions worth stating, because getting any of them wrong is a real
vulnerability rather than a bug:

*Accounts are keyed by the provider's subject id, never by email.* Email
addresses get reassigned — a company address released and re-issued to a new
hire, a reclaimed username at a free provider. Matching on email would let
whoever holds the address next inherit the account. The subject id is stable
and belongs to exactly one account for its lifetime.

*``state`` is signed and carries its own expiry.* It is what stops an attacker
from feeding a victim's browser a code of their choosing and silently linking
accounts (CSRF on the callback). We reuse the same HMAC the session cookie
uses, so there is one signing primitive in the codebase, not two.

*An unverified provider email never auto-links.* GitHub will hand back an
address the user has not confirmed; treating that as proof of ownership lets
anyone who can set an email claim the matching local account.

Providers are configured by environment variable and are simply absent when
unset — ``available()`` reports which, so the UI can disable a button with a
reason instead of showing one that fails on click.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

_TIMEOUT_S = 15
STATE_TTL_S = 600          # 10 minutes to complete a redirect round trip


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    authorize_endpoint: str
    token_endpoint: str
    profile_endpoint: str
    scope: str
    client_id_env: str
    client_secret_env: str


GOOGLE = Provider(
    key="google", label="Google",
    authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
    profile_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
    scope="openid email profile",
    client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
)

GITHUB = Provider(
    key="github", label="GitHub",
    authorize_endpoint="https://github.com/login/oauth/authorize",
    token_endpoint="https://github.com/login/oauth/access_token",
    profile_endpoint="https://api.github.com/user",
    scope="read:user user:email",
    client_id_env="GITHUB_CLIENT_ID", client_secret_env="GITHUB_CLIENT_SECRET",
)


# Apple differs from Google and GitHub in three ways, and all three are handled
# below rather than bolted onto the generic path:
#
#   1. The client SECRET is not a static string — it is an ES256 JWT you sign
#      yourself with a .p8 private key, valid for at most 6 months. There is no
#      value to paste into an env var; there is a key to sign with.
#   2. There is no userinfo endpoint. The identity arrives in the `id_token`
#      returned by the token exchange.
#   3. The user's name is sent ONCE, in the first authorization POST, and never
#      again. If you do not capture it then, it is gone for that Apple ID.
APPLE = Provider(
    key="apple", label="Apple",
    authorize_endpoint="https://appleid.apple.com/auth/authorize",
    token_endpoint="https://appleid.apple.com/auth/token",
    # No profile endpoint: the identity is inside the id_token. Empty rather
    # than a plausible-looking URL, so a caller that reaches for it fails
    # loudly instead of GETting something that does not exist.
    profile_endpoint="",
    scope="name email",
    # `client_id` is the Services ID (e.g. com.tradelogx.web), not the App ID.
    client_id_env="APPLE_CLIENT_ID",
    # Unused for Apple — the secret is derived, see apple_client_secret(). Named
    # for the dataclass contract; is_configured() overrides the check.
    client_secret_env="APPLE_PRIVATE_KEY",
)


def apple_client_secret(*, now: Optional[float] = None) -> Optional[str]:
    """Mint Apple's client secret: an ES256 JWT signed with the .p8 key.

    Returns None when Apple is not fully configured or the key cannot be used —
    never a partial or unsigned token, because a malformed client secret fails
    at Apple with an opaque error that is very hard to diagnose from this side.

    The 6-month lifetime is Apple's hard maximum. Minting per request rather
    than caching keeps it simple and costs one signature; the alternative is a
    cache that silently serves an expired secret months from now.
    """
    team = _env("APPLE_TEAM_ID")
    key_id = _env("APPLE_KEY_ID")
    client_id = _env("APPLE_CLIENT_ID")
    private_key = _env("APPLE_PRIVATE_KEY").replace("\\n", "\n")
    if not (team and key_id and client_id and private_key):
        return None
    try:
        import jwt  # PyJWT
        issued = int(now if now is not None else time.time())
        return jwt.encode(
            {"iss": team, "iat": issued,
             # 180 days — just inside Apple's 6-month ceiling.
             "exp": issued + 86400 * 180,
             "aud": "https://appleid.apple.com", "sub": client_id},
            private_key, algorithm="ES256", headers={"kid": key_id})
    except Exception:  # noqa: BLE001 — a bad key is "not configured", not a crash
        return None


def parse_apple_identity(id_token: str) -> Optional["Profile"]:
    """Read the identity out of Apple's id_token.

    The signature is NOT verified here, and that is safe for this flow only
    because the token arrived directly from Apple's token endpoint over TLS in
    response to our authenticated exchange — it is not a token a caller handed
    us. A token received any other way MUST be verified against Apple's JWKS
    before it is trusted; do not reuse this function for one.

    `email` may be a private relay address (…@privaterelay.appleid.com) when the
    user chose "Hide My Email". That is a real, deliverable address and is
    stored as-is — rewriting or rejecting it would break Sign in with Apple's
    headline feature.
    """
    try:
        import jwt
        claims = jwt.decode(id_token, options={"verify_signature": False})
    except Exception:  # noqa: BLE001
        return None
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        return None
    return Profile(provider="apple", subject=subject,
                   email=(claims.get("email") or None),
                   # Apple's `email_verified` arrives as a bool OR the strings
                   # "true"/"false" depending on the flow. Compared as text so
                   # both shapes land on the same answer.
                   email_verified=str(claims.get("email_verified", "")).lower()
                   in ("true", "1"),
                   # Apple sends the name ONCE, in the first authorization
                   # POST — never in the id_token. It is not available here,
                   # and inventing one from the email would be a guess.
                   name=None)


def exchange_apple_code(code: str, base: Optional[str] = None
                        ) -> Optional["Profile"]:
    """Apple's token exchange. Returns the profile, not an access token.

    Apple hands back the identity in the same response, so there is no second
    call — and no access token worth keeping.
    """
    secret = apple_client_secret()
    if not secret:
        return None
    try:
        payload = _post_form(APPLE.token_endpoint, {
            "client_id": _env("APPLE_CLIENT_ID"),
            "client_secret": secret,
            "code": code,
            "redirect_uri": redirect_uri(APPLE, base),
            "grant_type": "authorization_code",
        }, {"Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"})
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None
    id_token = payload.get("id_token")
    return parse_apple_identity(id_token) if id_token else None


PROVIDERS = {p.key: p for p in (GOOGLE, GITHUB, APPLE)}


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def get_provider(key: str) -> Optional[Provider]:
    return PROVIDERS.get((key or "").strip().lower())


def is_configured(p: Provider) -> bool:
    if p.key == "apple":
        # Apple needs four pieces to mint its secret, and a key that actually
        # signs. Checking the env vars alone would advertise a button that
        # fails at Apple with an opaque error.
        return apple_client_secret() is not None
    return bool(_env(p.client_id_env) and _env(p.client_secret_env))


def redirect_uri(p: Provider, base: Optional[str] = None) -> str:
    base = (base if base is not None else _env("HUB_PUBLIC_URL")).rstrip("/")
    return f"{base}/auth/oauth/{p.key}/callback"


def available() -> dict:
    """Which providers can actually complete a sign-in, and what each is missing.

    A social button that is rendered but cannot work is worse than an absent
    one: it fails after the user has committed to the flow.
    """
    out = {}
    public = _env("HUB_PUBLIC_URL")
    for key, p in PROVIDERS.items():
        if p.key == "apple":
            # Apple's four, named individually — "set APPLE_PRIVATE_KEY" would
            # be useless advice when what is actually missing is the team id.
            missing = [e for e in ("APPLE_CLIENT_ID", "APPLE_TEAM_ID",
                                   "APPLE_KEY_ID", "APPLE_PRIVATE_KEY")
                       if not _env(e)]
            if not missing and apple_client_secret() is None:
                missing.append("a valid APPLE_PRIVATE_KEY (.p8, ES256)")
        else:
            missing = [e for e in (p.client_id_env, p.client_secret_env)
                       if not _env(e)]
        if not public:
            missing.append("HUB_PUBLIC_URL")
        out[key] = {
            "label": p.label,
            "available": not missing,
            "note": "" if not missing else f"Set {' and '.join(missing)} to enable {p.label} sign-in.",
            "redirect_uri": redirect_uri(p) if public else "",
        }
    return out


# ------------------------------------------------------------------- state
def sign_state(secret: str, *, now: Optional[float] = None,
               nonce: Optional[str] = None) -> str:
    """A signed, self-expiring CSRF token: ``nonce.issued_at.signature``."""
    nonce = nonce or secrets.token_urlsafe(16)
    issued = int(now if now is not None else time.time())
    payload = f"{nonce}.{issued}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_state(state: str, secret: str, *, now: Optional[float] = None) -> bool:
    try:
        nonce, issued, sig = (state or "").rsplit(".", 2)
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{nonce}.{issued}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False
    try:
        age = (now if now is not None else time.time()) - int(issued)
    except ValueError:
        return False
    return 0 <= age <= STATE_TTL_S


def authorize_url(p: Provider, state: str, base: Optional[str] = None) -> str:
    params = {
        "client_id": _env(p.client_id_env),
        "redirect_uri": redirect_uri(p, base),
        "scope": p.scope,
        "state": state,
        "response_type": "code",
    }
    if p.key == "google":
        # Ask for a fresh consent screen rather than silently reusing whichever
        # Google account the browser happens to be signed into.
        params["prompt"] = "select_account"
    return f"{p.authorize_endpoint}?{urllib.parse.urlencode(params)}"


# ------------------------------------------------------------ network calls
def _post_form(url: str, data: dict, headers: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8") or "{}")


def _get_json(url: str, token: str, extra: Optional[dict] = None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "User-Agent": "TradeLogX-Nexus"}
    headers.update(extra or {})
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8") or "{}")


def exchange_code(p: Provider, code: str, base: Optional[str] = None) -> Optional[str]:
    """Trade the one-time code for an access token. None if the provider refuses."""
    try:
        payload = _post_form(p.token_endpoint, {
            "client_id": _env(p.client_id_env),
            "client_secret": _env(p.client_secret_env),
            "code": code,
            "redirect_uri": redirect_uri(p, base),
            "grant_type": "authorization_code",
        }, {"Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"})
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None
    return payload.get("access_token") or None


@dataclass(frozen=True)
class Profile:
    provider: str
    subject: str            # the stable key we store; never the email
    email: Optional[str]
    email_verified: bool
    name: Optional[str]


def parse_google_profile(data: dict) -> Optional[Profile]:
    sub = data.get("sub")
    if not sub:
        return None
    return Profile(provider="google", subject=str(sub), email=data.get("email"),
                   email_verified=bool(data.get("email_verified")),
                   name=data.get("name"))


def parse_github_profile(user: dict, emails: Optional[list] = None) -> Optional[Profile]:
    """GitHub's /user omits the email when the user keeps it private, so the
    address comes from /user/emails — where each entry carries its own verified
    flag. Only a primary AND verified address counts as proof of ownership."""
    uid = user.get("id")
    if not uid:
        return None
    email, verified = user.get("email"), False
    for e in emails or []:
        if e.get("primary") and e.get("verified"):
            email, verified = e.get("email"), True
            break
    return Profile(provider="github", subject=str(uid), email=email,
                   email_verified=verified, name=user.get("name") or user.get("login"))


def fetch_profile(p: Provider, token: str) -> Optional[Profile]:
    try:
        data = _get_json(p.profile_endpoint, token)
        if p.key == "google":
            return parse_google_profile(data)
        emails = None
        try:
            emails = _get_json("https://api.github.com/user/emails", token)
        except (urllib.error.URLError, ValueError, TimeoutError):
            emails = None          # private emails: proceed unverified, not fail
        return parse_github_profile(data, emails if isinstance(emails, list) else None)
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None
