"""Global settings for Automation Hub.

Values come from environment variables (loaded from a local ``.env`` if present)
with safe defaults so the app runs out of the box for development.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Tiny stdlib .env loader (no python-dotenv dependency)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


@dataclass
class Settings:
    # --- auth (Phase 1: single configured operator) ---
    username: str = field(default_factory=lambda: os.environ.get("HUB_USERNAME", "admin"))
    password: str = field(default_factory=lambda: os.environ.get("HUB_PASSWORD", "admin"))
    secret_key: str = field(default_factory=lambda: os.environ.get("HUB_SECRET", "dev-insecure-secret"))

    # --- display ---
    app_name: str = "Automation Hub"
    currency: str = field(default_factory=lambda: os.environ.get("HUB_CURRENCY", "£"))

    # --- defaults for new bots ---
    default_exchange: str = field(default_factory=lambda: os.environ.get("HUB_EXCHANGE", "binance"))
    default_symbol: str = "BTCUSDT"
    default_timeframe: str = "1h"
    starting_cash: float = field(default_factory=lambda: float(os.environ.get("HUB_STARTING_CASH", "10000")))

    # --- risk defaults ---
    risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3

    # --- notifications (Phase 5) ---
    telegram_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))


settings = Settings()
