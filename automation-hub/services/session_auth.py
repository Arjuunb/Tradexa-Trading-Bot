"""Signed-session token verification, shared.

``app.py`` mints and checks these cookies; the API routers need to read the same
token to answer "who is publishing this?". Rather than reimplement the HMAC in a
second place — where it would inevitably drift and become a forgery hole — the
crypto lives here once and both callers use it.

This module verifies the SIGNATURE and the EXPIRY only. Whether that username
still corresponds to a real account is the caller's business (``app.py`` checks
its user store; a router that only needs an author label does not).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional


def sign(username: str, secret: str, *, ttl_days: int) -> str:
    """``username|expiry|HMAC(secret, username|expiry)``.

    Signed with the server-only secret (HUB_SECRET), never the webhook secret —
    that one is embedded in every authed page, so signing sessions with it would
    let any logged-in user forge an owner token (CR-1)."""
    exp = str(int(time.time()) + int(ttl_days) * 86400)
    msg = f"{username}|{exp}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def verify(token: str, secret: str) -> Optional[str]:
    """The username if the token is authentic and unexpired, else None."""
    try:
        username, exp, sig = (token or "").rsplit("|", 2)
    except ValueError:
        return None
    good = hmac.new(secret.encode(), f"{username}|{exp}".encode(),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    try:
        if int(exp) < time.time():
            return None
    except ValueError:
        return None
    return username


# ------------------------------------------------------- purpose-scoped tokens
def _scoped_key(secret: str, purpose: str) -> bytes:
    """Derive a per-purpose signing key.

    Domain separation, and it is load-bearing. A half-finished sign-in holds a
    "2FA pending" token; if that token could also be presented as a session
    cookie, the second factor would be optional — you would simply skip it.
    Binding the purpose into the KEY rather than the message makes a signature
    minted for one purpose arithmetically unable to validate for another, no
    matter how the fields are re-split.
    """
    return hmac.new(secret.encode(), f"purpose:{purpose}".encode(),
                    hashlib.sha256).digest()


def sign_scoped(subject: str, secret: str, *, purpose: str, ttl_s: int) -> str:
    """A short-lived token valid ONLY for ``purpose``. Same shape as a session
    token, but signed under a different key, so the two are not interchangeable."""
    exp = str(int(time.time()) + int(ttl_s))
    msg = f"{subject}|{exp}"
    sig = hmac.new(_scoped_key(secret, purpose), msg.encode(),
                   hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def verify_scoped(token: str, secret: str, *, purpose: str) -> Optional[str]:
    try:
        subject, exp, sig = (token or "").rsplit("|", 2)
    except ValueError:
        return None
    good = hmac.new(_scoped_key(secret, purpose), f"{subject}|{exp}".encode(),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    try:
        if int(exp) < time.time():
            return None
    except ValueError:
        return None
    return subject
