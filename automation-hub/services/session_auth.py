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
