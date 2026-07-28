"""Single-use, expiring tokens for password reset and email verification.

Two rules the rest of the system depends on:

*Only the hash is stored.* A reset token is a temporary password — anyone
holding one can take the account. Storing them in plaintext means a read-only
database leak (a stray backup, a log dump, an errant SELECT) hands over every
account with a pending reset. We store SHA-256 and compare hashes, so what is
at rest cannot be replayed. A fast hash is right here: the token is 256 random
bits, and no attacker is dictionary-guessing that.

*Expiry and single-use are enforced on redemption, not on issue.* A token that
merely looks old must still be refused when presented; checking at redemption
is what makes the guarantee real.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

RESET_TTL_S = 3600            # 1 hour — long enough to find the email, short
                              # enough that a forwarded inbox is not a standing key
VERIFY_TTL_S = 24 * 3600      # 1 day — verification is not urgent
TOKEN_BYTES = 32              # 256 bits

RESET = "reset"
VERIFY = "verify"


@dataclass(frozen=True)
class MintedToken:
    plain: str          # goes in the email link, never persisted
    hashed: str         # persisted, never emailed
    expires_at: str     # ISO-8601 UTC


def hash_token(plain: str) -> str:
    return hashlib.sha256((plain or "").strip().encode("utf-8")).hexdigest()


def mint(ttl_s: int, *, now: Optional[datetime] = None) -> MintedToken:
    plain = secrets.token_urlsafe(TOKEN_BYTES)
    expires = (now or datetime.now(timezone.utc)) + timedelta(seconds=ttl_s)
    return MintedToken(plain=plain, hashed=hash_token(plain),
                       expires_at=expires.isoformat())


def is_expired(expires_at: str, *, now: Optional[datetime] = None) -> bool:
    """Unparseable timestamps count as expired — a token whose expiry we cannot
    read is one we cannot vouch for, and failing closed is the only safe way to
    be wrong here."""
    try:
        exp = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) >= exp
