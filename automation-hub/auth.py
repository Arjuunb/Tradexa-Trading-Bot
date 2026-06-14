"""Password hashing — stdlib only (PBKDF2-HMAC-SHA256).

No third-party crypto. Salts are per-user; verification is constant-time.
Phase 7 replaces the Phase-1 plaintext password comparison.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO = "sha256"
_ITERATIONS = 200_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return (salt_hex, hash_hex). Generates a fresh salt when none given."""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"),
                             bytes.fromhex(salt), _ITERATIONS)
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hex: str) -> bool:
    """Constant-time check of ``password`` against a stored salt + hash."""
    _, computed = hash_password(password, salt)
    return hmac.compare_digest(computed, expected_hex)
