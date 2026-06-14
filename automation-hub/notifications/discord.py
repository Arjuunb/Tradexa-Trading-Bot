"""Discord notifications — Phase 5 stub (incoming webhook, stdlib urllib)."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger("hub.discord")


def send(text: str) -> bool:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        log.debug("Discord not configured; skipping: %s", text)
        return False
    try:  # pragma: no cover - network
        req = urllib.request.Request(
            webhook, data=json.dumps({"content": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Discord send failed: %s", e)
        return False
