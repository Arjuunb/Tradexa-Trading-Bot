"""TOTP against RFC 6238.

The published vectors are the point of this file: they prove the implementation
is compatible with what Google Authenticator, 1Password and Authy actually
compute, rather than merely self-consistent. A TOTP that only agrees with
itself passes every round-trip test and still rejects every real phone.
"""
import base64

import pytest

from services import totp

# RFC 6238 Appendix B: the SHA-1 seed is the ASCII string "12345678901234567890".
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()

# (unix time, expected 8-digit code) — the SHA-1 rows of the RFC's table.
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize("at,expected", RFC_VECTORS)
def test_matches_the_rfc_6238_published_vectors(at, expected):
    assert totp.code_now(RFC_SECRET, at=at, digits=8) == expected


def test_the_six_digit_code_is_the_last_six_of_the_eight_digit_one():
    """Authenticator apps show 6 digits; the RFC tabulates 8. They are the same
    number truncated, so this pins our default against the vectors too."""
    for at, expected8 in RFC_VECTORS:
        assert totp.code_now(RFC_SECRET, at=at) == expected8[-6:]


# ------------------------------------------------------------------- secrets

def test_a_generated_secret_is_base32_and_160_bits():
    s = totp.generate_secret()
    assert len(base64.b32decode(s + "=" * (-len(s) % 8))) == 20


def test_two_generated_secrets_differ():
    assert totp.generate_secret() != totp.generate_secret()


def test_a_secret_is_accepted_the_way_an_app_displays_it():
    """Apps show secrets lowercased, spaced in groups, and unpadded."""
    s = totp.generate_secret()
    spaced = " ".join(s[i:i + 4] for i in range(0, len(s), 4)).lower()
    assert totp.code_now(spaced, at=1000) == totp.code_now(s, at=1000)


# -------------------------------------------------------------------- verify

def test_the_current_code_verifies():
    s = totp.generate_secret()
    assert totp.verify(s, totp.code_now(s, at=1000), at=1000) is not None


def test_a_wrong_code_does_not():
    s = totp.generate_secret()
    assert totp.verify(s, "000000", at=1000) is None or totp.code_now(s, at=1000) == "000000"


def test_a_code_from_the_adjacent_step_is_accepted():
    """Phone clocks drift and people type slowly. Rejecting ±30s makes 2FA feel
    broken to users whose clock is a few seconds off."""
    s = totp.generate_secret()
    late = totp.code_now(s, at=1000)
    assert totp.verify(s, late, at=1000 + totp.STEP_S) is not None      # one step later
    assert totp.verify(s, late, at=1000 - totp.STEP_S) is not None      # one step earlier


def test_a_code_two_steps_stale_is_rejected():
    s = totp.generate_secret()
    old = totp.code_now(s, at=1000)
    assert totp.verify(s, old, at=1000 + 3 * totp.STEP_S) is None


def test_verify_returns_the_step_so_a_used_code_can_be_burned():
    """A code stays valid for its whole window, so without a replay key an
    observed code is reusable for up to 30 seconds."""
    s = totp.generate_secret()
    step = totp.verify(s, totp.code_now(s, at=1000), at=1000)
    assert step == 1000 // totp.STEP_S


def test_malformed_input_is_rejected_without_raising():
    s = totp.generate_secret()
    for bad in ("", "abc", "12345", "1234567", "12 34 56", None):
        assert totp.verify(s, bad, at=1000) is None


def test_a_code_for_one_secret_does_not_verify_against_another():
    a, b = totp.generate_secret(), totp.generate_secret()
    assert totp.verify(b, totp.code_now(a, at=1000), at=1000) is None


# ------------------------------------------------------------ provisioning

def test_the_provisioning_uri_carries_what_an_app_needs_to_scan():
    uri = totp.provisioning_uri("ABCDEF", "arjun@example.com", "TradeLogX Nexus")
    assert uri.startswith("otpauth://totp/")
    assert "secret=ABCDEF" in uri and "period=30" in uri and "digits=6" in uri
    assert "TradeLogX%20Nexus" in uri          # issuer is escaped, not dropped
    assert "arjun%40example.com" in uri        # so is the '@' in the account


# -------------------------------------------------------------- recovery codes

def test_recovery_codes_are_distinct_and_plentiful():
    codes = totp.generate_recovery_codes()
    assert len(codes) == totp.RECOVERY_COUNT and len(set(codes)) == totp.RECOVERY_COUNT


def test_a_recovery_code_hash_is_not_the_code():
    c = totp.generate_recovery_codes(1)[0]
    assert totp.hash_recovery_code(c) != c and len(totp.hash_recovery_code(c)) == 64


def test_a_recovery_code_matches_however_it_was_typed():
    """Someone reading these off a printout will use different case and spacing
    than the screen showed."""
    c = totp.generate_recovery_codes(1)[0]
    assert totp.hash_recovery_code(f"  {c.upper()} ") == totp.hash_recovery_code(c)
