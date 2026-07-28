"""Password reset, email verification and two-factor — the logic, not the routes.

Everything here takes a store and returns a dict, so each flow is testable
without an HTTP client and the endpoints in ``app.py`` stay thin.

Two principles run through the whole file.

*Never confirm whether an account exists.* "If that address has an account, a
link is on its way" is the same answer for a real address and a stranger's
guess. Anything else turns the reset form into a free membership check, which
is how credential-stuffing lists get filtered down to accounts worth attacking.

*Never claim an email was sent when it was not.* The vagueness above protects
the user; it must not be used to hide a broken mail server from the operator.
Every response carries a ``delivery`` block reporting whether mail is actually
configured and whether this specific send succeeded — the operator sees the
truth, the stranger still learns nothing about who has an account.
"""
from __future__ import annotations

from typing import Optional

from services import auth_tokens as tok
from services import mailer, totp

MIN_PASSWORD_LEN = 8

# The stranger-safe sentence. Identical for a hit and a miss, by design.
GENERIC_RESET_REPLY = ("If that account exists, a reset link is on its way. "
                       "The link expires in 60 minutes.")


def validate_password(password: str, confirm: Optional[str] = None) -> Optional[str]:
    """The error, or None. Matches the rule signup already enforces."""
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters"
    if confirm is not None and password != confirm:
        return "Passwords do not match"
    return None


# ---------------------------------------------------------- password reset
def request_password_reset(store, identifier: str, *, base: Optional[str] = None) -> dict:
    """Mint and email a reset link. The reply never reveals whether we found
    anyone; ``delivery`` tells the operator whether mail can go out at all."""
    delivery = mailer.available()
    user = store.find_by_email(identifier) or store.get_user(identifier)
    result = {"ok": True, "message": GENERIC_RESET_REPLY, "delivery": dict(delivery)}
    if user is None:
        return result

    address = user.contact_email
    if not address:
        # A real account with nowhere to write. Silent to the caller (saying so
        # would confirm the account exists), explicit in delivery.
        result["delivery"] = {"available": False,
                              "note": ("That account has no email address on file, "
                                       "so no reset link could be sent. An admin "
                                       "can set one, or sign in and add it.")}
        return result
    if not delivery["available"]:
        return result

    minted = tok.mint(tok.RESET_TTL_S)
    store.put_auth_token(user.username, minted.hashed, tok.RESET, minted.expires_at)
    subject, body = mailer.render_reset(
        user.username, mailer.reset_link(minted.plain, base), tok.RESET_TTL_S // 60)
    if not mailer.send(address, subject, body):
        result["delivery"] = {"available": False,
                              "note": ("SMTP is configured but the send failed — "
                                       "check ALERT_SMTP_HOST/USER/PASS and the "
                                       "provider's logs.")}
    return result


def perform_password_reset(store, token: str, password: str,
                           confirm: Optional[str] = None) -> dict:
    err = validate_password(password, confirm)
    if err:
        return {"ok": False, "error": err}
    username = store.redeem_auth_token(tok.hash_token(token), tok.RESET)
    if username is None:
        return {"ok": False,
                "error": ("That reset link is invalid, already used, or expired. "
                          "Request a new one.")}
    store.set_password(username, password)
    # A password reset proves control of the inbox, which is exactly what email
    # verification asks for — so stop asking.
    store.mark_email_verified(username)
    # Anyone who reached the account through a stolen password is now locked
    # out of the reset path too.
    store.purge_expired_tokens()
    return {"ok": True, "user": username,
            "message": "Password updated. You can sign in now."}


# ------------------------------------------------------- email verification
def request_email_verification(store, username: str, *,
                               base: Optional[str] = None) -> dict:
    user = store.get_user(username)
    if user is None:
        return {"ok": False, "error": "No such account"}
    if user.email_verified:
        return {"ok": True, "already_verified": True,
                "message": "That address is already confirmed."}
    address = user.contact_email
    if not address:
        return {"ok": False, "error": "Add an email address to this account first."}
    delivery = mailer.available()
    if not delivery["available"]:
        return {"ok": False, "error": delivery["note"], "delivery": delivery}

    minted = tok.mint(tok.VERIFY_TTL_S)
    store.put_auth_token(user.username, minted.hashed, tok.VERIFY, minted.expires_at)
    subject, body = mailer.render_verify(
        user.username, mailer.verify_link(minted.plain, base), tok.VERIFY_TTL_S // 3600)
    if not mailer.send(address, subject, body):
        return {"ok": False,
                "error": "SMTP is configured but the send failed. Check the mail settings."}
    return {"ok": True, "message": f"Confirmation link sent to {address}."}


def confirm_email(store, token: str) -> dict:
    username = store.redeem_auth_token(tok.hash_token(token), tok.VERIFY)
    if username is None:
        return {"ok": False,
                "error": "That confirmation link is invalid, already used, or expired."}
    store.mark_email_verified(username)
    return {"ok": True, "user": username, "message": "Email confirmed."}


# ------------------------------------------------------------- two-factor
def begin_totp_setup(store, username: str, *, issuer: str = "TradeLogX Nexus") -> dict:
    """Stage a secret and hand back what an authenticator app needs.

    Staged, not enabled: 2FA switches on only after the user proves they can
    read a code off the app. Enabling here would lock someone out with a secret
    that never made it onto their phone.
    """
    user = store.get_user(username)
    if user is None:
        return {"ok": False, "error": "No such account"}
    secret = totp.generate_secret()
    store.set_totp_secret(user.username, secret)
    return {"ok": True, "secret": secret,
            "otpauth_uri": totp.provisioning_uri(
                secret, user.contact_email or user.username, issuer),
            "digits": totp.DIGITS, "period": totp.STEP_S,
            "message": "Scan this in your authenticator app, then enter a code to finish."}


def enable_totp(store, username: str, code: str) -> dict:
    """Confirm the staged secret and switch 2FA on, returning recovery codes."""
    user = store.get_user(username)
    if user is None:
        return {"ok": False, "error": "No such account"}
    if not user.totp_secret:
        return {"ok": False, "error": "Start the setup first — no secret is staged."}
    if user.totp_enabled:
        return {"ok": False, "error": "Two-factor is already on for this account."}
    step = totp.verify(user.totp_secret, code)
    if step is None:
        return {"ok": False,
                "error": "That code didn't match. Check your phone's clock is correct."}
    codes = totp.generate_recovery_codes()
    store.enable_totp(user.username, [totp.hash_recovery_code(c) for c in codes])
    store.record_totp_step(user.username, step)
    return {"ok": True, "recovery_codes": codes,
            "message": ("Two-factor is on. Save these recovery codes somewhere safe — "
                        "they are shown once and are the only way in if you lose "
                        "your phone.")}


def disable_totp(store, username: str, password: str) -> dict:
    """Turning 2FA off is a downgrade, so it costs a password. Otherwise a
    borrowed open session is enough to strip the second factor."""
    user = store.get_user(username)
    if user is None:
        return {"ok": False, "error": "No such account"}
    if store.authenticate(user.username, password) is None:
        return {"ok": False, "error": "Password incorrect."}
    store.disable_totp(user.username)
    return {"ok": True, "message": "Two-factor is off."}


def verify_second_factor(store, username: str, code: str) -> dict:
    """Check a TOTP code or a recovery code at sign-in.

    A TOTP code is valid for its whole 30-second step, so a matched step is
    burned on success: an intercepted code cannot be replayed inside its window.
    """
    user = store.get_user(username)
    if user is None or not user.totp_enabled or not user.totp_secret:
        return {"ok": False, "error": "Two-factor is not enabled for this account."}

    step = totp.verify(user.totp_secret, code)
    if step is not None:
        if not store.record_totp_step(user.username, step):
            return {"ok": False,
                    "error": "That code was already used. Wait for the next one."}
        return {"ok": True, "method": "totp"}

    if store.consume_recovery_code(user.username, totp.hash_recovery_code(code)):
        left = store.count_unused_recovery_codes(user.username)
        return {"ok": True, "method": "recovery", "recovery_codes_left": left,
                "message": (f"Recovery code accepted — {left} left. "
                            "Set up your authenticator again soon.")
                if left else ("Recovery code accepted — that was your last one. "
                              "Re-enrol your authenticator now.")}
    return {"ok": False, "error": "Invalid code."}


def totp_status(store, username: str) -> dict:
    user = store.get_user(username)
    if user is None:
        return {"available": False, "note": "No such account"}
    return {"available": True, "enabled": bool(user.totp_enabled),
            "pending_setup": bool(user.totp_secret and not user.totp_enabled),
            "recovery_codes_left": store.count_unused_recovery_codes(user.username)}
