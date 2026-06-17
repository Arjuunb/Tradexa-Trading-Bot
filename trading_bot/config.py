"""Configuration for the standalone Python trading-bot workspace.

This UI module talks to the existing Automation Hub backend over HTTP, so it has
no engine logic of its own — set BOT_API_BASE to the running backend.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    api_base: str = os.environ.get("BOT_API_BASE", "http://localhost:8000")
    webhook_secret: str = os.environ.get("BOT_WEBHOOK_SECRET", "dev-webhook-secret")
    app_name: str = os.environ.get("BOT_APP_NAME", "Tradexa Bot Workspace")
    request_timeout: int = int(os.environ.get("BOT_REQUEST_TIMEOUT", "10"))


settings = Settings()
