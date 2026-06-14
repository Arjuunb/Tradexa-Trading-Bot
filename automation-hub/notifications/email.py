"""Email notifications — Phase 5 stub (stdlib smtplib).

Configure SMTP via env (SMTP_HOST/PORT/USER/PASS, ALERT_EMAIL_TO). No-ops when
unconfigured so callers can fire-and-forget.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("hub.email")


def send(subject: str, body: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    to = os.environ.get("ALERT_EMAIL_TO")
    if not host or not to:
        log.debug("Email not configured; skipping: %s", subject)
        return False
    # pragma: no cover - Phase 5 SMTP wiring
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_USER", "automation-hub")
    msg["To"] = to
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as srv:
            srv.starttls()
            if os.environ.get("SMTP_USER"):
                srv.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
            srv.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Email send failed: %s", e)
        return False
