"""Notification dispatch — fan a message out to all configured channels."""
from __future__ import annotations

from notifications import discord, email, telegram


def notify(text: str, subject: str = "Automation Hub alert") -> dict:
    """Send to every channel; returns {channel: delivered?}."""
    return {
        "telegram": telegram.send(text),
        "discord": discord.send(text),
        "email": email.send(subject, text),
    }
