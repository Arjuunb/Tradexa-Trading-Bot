"""Transactional email for auth flows (reset links, verification links).

Reuses the SMTP settings ``services/alerts.py`` already uses, so a hub with
working trade alerts can send auth mail with no extra configuration. The
difference is the recipient: alerts go to one fixed operator address, these go
to whichever account asked.

The honesty rule applies with unusual force here. "If that address exists, a
link is on its way" is the correct answer to a *stranger* — it refuses to
confirm whether an account exists. It is a lie to the *operator* when no SMTP
host is configured at all, because then no link is on its way to anyone, ever.
``available()`` separates the two: user-facing responses stay deliberately
vague, while the operator gets told plainly that email is not wired up.

Message bodies are built by pure ``render_*`` functions so their content is
testable without a mail server.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Optional

_TIMEOUT_S = 10


def _val(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def smtp_host() -> str:
    return _val("ALERT_SMTP_HOST")


def mail_from() -> str:
    return (_val("HUB_MAIL_FROM") or _val("ALERT_SMTP_USER")
            or "no-reply@tradelogx-nexus.local")


def public_url() -> str:
    """Origin the links point at. Without it a reset email would carry a link
    to localhost, which is worse than no email at all."""
    return _val("HUB_PUBLIC_URL").rstrip("/")


def available() -> dict:
    """Whether auth mail can actually be delivered, and what is missing.

    Follows the ``{"available": false, "note": ...}`` convention used across
    the hub: declare the limit, never paper over it.
    """
    missing = []
    if not smtp_host():
        missing.append("ALERT_SMTP_HOST")
    if not public_url():
        missing.append("HUB_PUBLIC_URL")
    if missing:
        return {"available": False,
                "note": ("Email delivery is not configured — set "
                         + " and ".join(missing)
                         + ". Reset and verification links cannot be sent until then.")}
    return {"available": True, "note": ""}


def send(to: str, subject: str, body: str) -> bool:
    """Deliver one message. False on any failure — the caller must not tell a
    user their mail is on the way when it is not."""
    host = smtp_host()
    if not host or not to:
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = mail_from()
        msg["To"] = to
        msg.set_content(body)
        port = int(_val("ALERT_SMTP_PORT") or 587)
        with smtplib.SMTP(host, port, timeout=_TIMEOUT_S) as s:
            s.starttls()
            user, pw = _val("ALERT_SMTP_USER"), _val("ALERT_SMTP_PASS")
            if user and pw:
                s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 — a mail outage must not 500 the endpoint
        return False


# ------------------------------------------------------------------ bodies
APP_NAME = "TradeLogX Nexus"


def reset_link(token: str, base: Optional[str] = None) -> str:
    return f"{(base if base is not None else public_url())}/auth/reset-password?token={token}"


def verify_link(token: str, base: Optional[str] = None) -> str:
    return f"{(base if base is not None else public_url())}/auth/verify-email?token={token}"


def render_reset(username: str, link: str, ttl_minutes: int) -> tuple[str, str]:
    body = (
        f"Someone asked to reset the password for {username} on {APP_NAME}.\n\n"
        f"Set a new password here:\n{link}\n\n"
        f"The link works once and expires in {ttl_minutes} minutes.\n\n"
        "If this wasn't you, no action is needed — your password has not "
        "changed, and this link can only be used by whoever received this "
        "email. You may want to check that nobody else can read this inbox.\n"
    )
    return f"Reset your {APP_NAME} password", body


def render_verify(username: str, link: str, ttl_hours: int) -> tuple[str, str]:
    body = (
        f"Confirm this address for {username} on {APP_NAME}.\n\n"
        f"{link}\n\n"
        f"The link works once and expires in {ttl_hours} hours.\n\n"
        "If you didn't create this account, you can ignore this email.\n"
    )
    return f"Confirm your {APP_NAME} email", body
