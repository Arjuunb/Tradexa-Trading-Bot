"""Dependency-free HS256 JSON Web Tokens.

A tiny, self-contained JWT (HMAC-SHA256) codec — no third-party library, so it
adds nothing to the deploy footprint and reuses the stdlib the HMAC session
cookie already relies on. Signed with the server-only secret (HUB_SECRET), never
the webhook secret (same rule as the session cookie — see app._sign_session).

This is the primitive behind the app's ``issue_access`` / ``verify_access``
helpers (DSP Sprint 1: "issue JWT alongside HMAC cookie"). The access token is
purely ADDITIVE — the existing signed cookie keeps working unchanged; a request
may authenticate with either.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Optional


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def encode(payload: dict, secret: str, *, ttl_seconds: int) -> str:
    """Sign an HS256 JWT. ``iat``/``exp`` are stamped automatically."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + int(ttl_seconds)}
    seg = (_b64e(json.dumps(header, separators=(",", ":")).encode())
           + "." + _b64e(json.dumps(body, separators=(",", ":")).encode()))
    sig = _b64e(hmac.new(secret.encode(), seg.encode(), hashlib.sha256).digest())
    return f"{seg}.{sig}"


def decode(token: str, secret: str) -> Optional[dict]:
    """Verify signature + expiry; return the claims dict or None. Never raises
    on malformed input — a bad token is simply unauthenticated."""
    try:
        header_b64, body_b64, sig = token.split(".")
    except (ValueError, AttributeError):
        return None
    seg = f"{header_b64}.{body_b64}"
    good = _b64e(hmac.new(secret.encode(), seg.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        body = json.loads(_b64d(body_b64))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    try:
        if int(body.get("exp", 0)) < int(time.time()):
            return None
    except (TypeError, ValueError):
        return None
    return body
