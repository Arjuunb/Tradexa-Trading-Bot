"""Telegram notifications — Phase 5.

Sends alerts (trade opened/closed, bot paused, risk breach) to a chat. Uses the
stdlib ``urllib`` so there's no extra dependency; no-ops cleanly when unconfigured.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

from config import settings

log = logging.getLogger("hub.telegram")


def send(text: str) -> bool:
    token, chat = settings.telegram_token, settings.telegram_chat_id
    if not token or not chat:
        log.debug("Telegram not configured; skipping: %s", text)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:  # pragma: no cover - network
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram send failed: %s", e)
        return False
