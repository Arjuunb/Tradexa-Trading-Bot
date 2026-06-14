"""Notification dispatch — fan a message out to all configured channels."""
from __future__ import annotations

from typing import Callable, Optional

from notifications import discord, email, telegram


def notify(text: str, subject: str = "Automation Hub alert") -> dict:
    """Send to every channel; returns {channel: delivered?}."""
    return {
        "telegram": telegram.send(text),
        "discord": discord.send(text),
        "email": email.send(subject, text),
    }


class AlertDispatcher:
    """EventBus subscriber that turns engine events into operator alerts.

    Fires on trade closes (TP/SL), risk halts, and run completion. ``send``
    defaults to :func:`notify` (Telegram/Discord/email), which no-ops when no
    channel is configured — so it's safe to attach unconditionally.
    """

    def __init__(self, bot_name: str, send: Optional[Callable[[str], object]] = None):
        self.bot_name = bot_name
        self.send = send or (lambda text: notify(text))
        self.sent: list[str] = []

    def attach(self, bus) -> None:
        bus.subscribe(self)

    def __call__(self, ev: dict) -> None:
        t = ev.get("type")
        msg: Optional[str] = None
        if t == "trade_closed":
            tag = "🎯 TP" if ev.get("pnl", 0) >= 0 else "🛑 SL"
            msg = (f"{tag} {self.bot_name}: {ev.get('symbol','')} "
                   f"PnL {ev.get('pnl', 0):.2f} (R {ev.get('r', 0):.2f})")
        elif t == "run_finished":
            msg = f"🏁 {self.bot_name}: run finished — equity {ev.get('ending_equity', 0):,.2f}"
        if msg:
            self.sent.append(msg)
            try:
                self.send(msg)
            except Exception:  # noqa: BLE001 - alerts must never crash the engine
                pass
