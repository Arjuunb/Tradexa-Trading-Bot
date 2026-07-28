"""TOTP — RFC 6238 time-based one-time passwords. Stdlib only.

No third-party crypto, matching ``auth.py``. Everything here is pure: given a
secret and a timestamp you get a code, so the whole scheme is testable against
the RFC's published vectors rather than against itself.

Two details that are security-relevant rather than cosmetic:

*Skew.* Phone clocks drift and people finish typing late, so ``verify`` accepts
the adjacent steps as well as the current one. One step either way (±30s) is
the usual compromise; widening it multiplies an attacker's guessing odds by the
same factor.

*Replay.* A code stays valid for its whole step, so an observed code can be
reused within that window. ``verify`` returns the matched step so the caller
can record it and refuse the same step twice.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

DIGITS = 6
STEP_S = 30
SKEW_STEPS = 1          # accept the previous and next step (±30s)
SECRET_BYTES = 20       # 160 bits, the RFC 4226 recommendation


def generate_secret() -> str:
    """A fresh base32 secret, in the format authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _decode(secret: str) -> bytes:
    # Authenticator apps show secrets unpadded and often in lowercase with
    # spaces for readability; accept all of that back.
    s = (secret or "").strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8), casefold=True)


def code_at(secret: str, counter: int, digits: int = DIGITS) -> str:
    """The HOTP code for an explicit counter (RFC 4226 dynamic truncation)."""
    mac = hmac.new(_decode(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    truncated = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def code_now(secret: str, at: Optional[float] = None, digits: int = DIGITS) -> str:
    return code_at(secret, int((at if at is not None else time.time()) // STEP_S), digits)


def verify(secret: str, code: str, *, at: Optional[float] = None,
           skew: int = SKEW_STEPS, digits: int = DIGITS) -> Optional[int]:
    """Return the matched time step, or None. The step is the caller's replay key.

    Returns a step rather than a bool precisely so a used code can be burned:
    a bool would leave the same code usable for the rest of its 30-second window.
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != digits:
        return None
    now_step = int((at if at is not None else time.time()) // STEP_S)
    for delta in range(-skew, skew + 1):
        step = now_step + delta
        # constant-time compare: a timing oracle on a 6-digit code is worth having
        if hmac.compare_digest(code_at(secret, step, digits), code):
            return step
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    """The otpauth:// URI an authenticator app scans as a QR code."""
    label = quote(f"{issuer}:{account}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}"
            f"&issuer={quote(issuer, safe='')}&algorithm=SHA1"
            f"&digits={DIGITS}&period={STEP_S}")


# --------------------------------------------------------------- recovery codes
RECOVERY_COUNT = 10


def generate_recovery_codes(count: int = RECOVERY_COUNT) -> list[str]:
    """Single-use codes for a lost phone. Shown once, stored only as hashes.

    Without these, losing the authenticator means losing the account — which is
    how 2FA turns into a self-inflicted lockout.
    """
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"
            for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    """Recovery codes are high-entropy, so a plain SHA-256 is enough — the
    slow-KDF argument applies to guessable human passwords, not to 48 random
    bits. Normalised first so case and stray spaces don't fail a valid code."""
    return hashlib.sha256(normalise_recovery_code(code).encode("utf-8")).hexdigest()


def normalise_recovery_code(code: str) -> str:
    return (code or "").strip().lower().replace(" ", "")
