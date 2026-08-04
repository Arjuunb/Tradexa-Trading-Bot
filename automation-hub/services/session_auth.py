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


def sign(username: str, secret: str, *, ttl_days: int,
         session_id: str = "") -> str:
    """``username|expiry|HMAC(...)``, or ``username|expiry|sid|HMAC(...)``.

    Signed with the server-only secret (HUB_SECRET), never the webhook secret —
    that one is embedded in every authed page, so signing sessions with it would
    let any logged-in user forge an owner token (CR-1).

    ``session_id`` binds the cookie to a revocable row in ``user_sessions``. It
    is INSIDE the signed message, not appended after the signature: appended, a
    holder could swap in any session id they liked and the HMAC would still
    verify, which would let one user's cookie claim another's session.

    Omitting it produces the original three-part token, byte for byte. That is
    what keeps every cookie issued before the sessions table valid — a format
    change here would sign out every user on deploy.
    """
    exp = str(int(time.time()) + int(ttl_days) * 86400)
    msg = f"{username}|{exp}|{session_id}" if session_id else f"{username}|{exp}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def split_session(token: str, secret: str) -> tuple[Optional[str], str]:
    """``(username, session_id)`` for an authentic token, else ``(None, "")``.

    Handles both shapes — three parts (pre-sessions) and four (bound to a row) —
    by counting fields rather than by ``rsplit``, which on a four-part token
    would silently treat the session id as the signature and reject a valid
    cookie.
    """
    parts = (token or "").split("|")
    if len(parts) == 3:
        username, exp, sig = parts
        session_id = ""
        msg = f"{username}|{exp}"
    elif len(parts) == 4:
        username, exp, session_id, sig = parts
        msg = f"{username}|{exp}|{session_id}"
    else:
        return None, ""
    good = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None, ""
    try:
        if int(exp) < time.time():
            return None, ""
    except (TypeError, ValueError):
        return None, ""
    return username, session_id


def verify(token: str, secret: str) -> Optional[str]:
    """The username if the token is authentic and unexpired, else None."""
    # Delegates, so the two entry points cannot drift into disagreeing about
    # whether a token is valid — which would be a way in.
    username, _sid = split_session(token, secret)
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
