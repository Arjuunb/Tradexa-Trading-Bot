"""Telegram notifications — fail-safe, stdlib-only, non-blocking.

Sends bot events (trade opened/closed, risk warnings) to Telegram when
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are configured. Every send runs on a
daemon thread and swallows errors, so notifications never block or crash the
trading pipeline. Email/Discord are out of scope (need extra credentials).
"""
from __future__ import annotations

import threading
import urllib.parse
import urllib.request


class Notifier:
    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token
        self.chat_id = chat_id
        self.notify_trades = True
        self.notify_risk = True

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def dispatch(self, kind: str, title: str, detail: str = "") -> None:
        if not self.configured:
            return
        if kind == "trade" and not self.notify_trades:
            return
        if kind == "risk" and not self.notify_risk:
            return
        self.send_async(f"{title}\n{detail}".strip())

    def send_async(self, text: str) -> None:
        threading.Thread(target=self.send, args=(text,), daemon=True).start()

    def send(self, text: str) -> bool:
        if not self.configured:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
            with urllib.request.urlopen(url, data=data, timeout=5) as r:  # noqa: S310
                return getattr(r, "status", 200) == 200
        except Exception:  # noqa: BLE001 — notifications are best-effort
            return False
